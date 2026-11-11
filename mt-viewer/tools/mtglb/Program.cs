// mtglb — export Motor Town vehicle part meshes to glTF/GLB with materials.
// Usage: mtglb <pakDir> <usmapPath> <aesKey0x> <outDir> <meshesJson> [--materials]
//   meshesJson: [{"name":"Body","path":"MotorTown/Content/Cars/Models/Boxy/Body/Body"}, ...]
//
// Differences from the original prototype:
//  * ExportMaterials is a CLI switch (materials need libSkiaSharp.so + libfontconfig.so.1
//    on the runtime path — see build.sh which sets LD_LIBRARY_PATH).
//  * Tolerant pak path resolution: the pak stores meshes flat, dropping the
//    per-asset subfolder repeat (`.../Wheels/SRT_FR/SRT_FR` -> `.../Wheels/SRT_FR`),
//    so a naive translate fails for most wheels. resolve() de-repeats, then
//    searches pak keys by prefix and takes the unique de-repeated candidate.
using CUE4Parse.FileProvider;
using CUE4Parse.UE4.Assets.Exports.StaticMesh;
using CUE4Parse.UE4.Objects.Core.Misc;
using CUE4Parse.UE4.Versions;
using CUE4Parse.Encryption.Aes;
using CUE4Parse.MappingsProvider.Usmap;
using CUE4Parse_Conversion;
using CUE4Parse_Conversion.Meshes;
using System.Text.Json;
using System.IO;

var argv = Environment.GetCommandLineArgs().Skip(1).ToArray();
if (argv.Length >= 3 && argv[0] == "--find")
{
    // Diagnostic: list pak keys for an asset leaf, e.g. --find <pakDir> Body
    var dp = new DefaultFileProvider(argv[1], SearchOption.AllDirectories, false,
        new VersionContainer(EGame.GAME_UE5_5));
    dp.Initialize();
    if (argv.Length >= 4 && argv[3].Length >= 32)
        dp.SubmitKey(new FGuid(), new FAesKey(argv[3]));
    var needle = argv[2].Trim('/');
    if (needle.StartsWith("try:"))
    {
        // Existence probe: --find <pakDir> try:<path>[,<path>...]
        foreach (var cand in needle.Substring(4).Split(','))
            Console.WriteLine($"{(dp.TryGetGameFile(cand, out _) ? "YES" : "no ")} {cand}");
        return 0;
    }
    if (needle == "*")
    {
        foreach (var k in dp.Files.Keys.Take(15)) Console.WriteLine(k);
        Console.WriteLine($"total keys: {dp.Files.Count}");
        return 0;
    }
    foreach (var k in dp.Files.Keys
                 .Where(k => k.EndsWith("/" + needle + ".uasset", StringComparison.OrdinalIgnoreCase)
                          || k.EndsWith("/" + needle + "/" + needle + ".uasset", StringComparison.OrdinalIgnoreCase))
                 .Select(DeRepeatStatic)
                 .Distinct()
                 .OrderBy(k => k))
        Console.WriteLine(k);
    return 0;
}
if (argv.Length < 5) { Console.WriteLine("usage: mtglb <pakDir> <usmapPath> <aesKey0x> <outDir> <meshesJson> [--materials]"); return 2; }
var pakDir = argv[0];
var usmapPath = argv[1];
var aesKey = argv[2];
var outDir = argv[3];
var jsonPath = argv[4];
bool wantMaterials = argv.Contains("--materials");
Directory.CreateDirectory(outDir);

var provider = new DefaultFileProvider(pakDir, SearchOption.AllDirectories, false,
    new VersionContainer(EGame.GAME_UE5_5));
provider.MappingsContainer = new FileUsmapTypeMappingsProvider(usmapPath);
provider.Initialize();
provider.SubmitKey(new FGuid(), new FAesKey(aesKey));
try { provider.LoadLocalization(); } catch (Exception) { Console.WriteLine("no localization, continuing"); }

string DeRepeat(string p) => DeRepeatStatic(p);

static string DeRepeatStatic(string p)
{
    var parts = p.Split('/');
    if (parts.Length >= 2 && parts[^1] == parts[^2])
        return string.Join("/", parts.Take(parts.Length - 1));
    return p;
}

// Resolve a translated asset path to an actual pak key.
string? Resolve(string path)
{
    var candidates = new List<string> { path };
    var de = DeRepeat(path);
    if (de != path) candidates.Add(de);
    foreach (var c in candidates)
        if (provider.TryGetGameFile(c, out _)) return c;

    foreach (var c in candidates)
    {
        var keys = provider.Files.Keys
            .Where(k => k.StartsWith(c + ".") && k.EndsWith(".uasset", StringComparison.OrdinalIgnoreCase))
            .Select(DeRepeat)
            .Distinct()
            .ToList();
        if (keys.Count == 1) return keys[0];
        if (keys.Count > 1) { Console.WriteLine($"  AMBIGUOUS {c}: {string.Join(", ", keys.Take(4))}"); return keys[0]; }
    }
    return null;
}

var items = JsonSerializer.Deserialize<List<MeshItem>>(File.ReadAllText(jsonPath),
    new JsonSerializerOptions { PropertyNameCaseInsensitive = true });
Console.WriteLine($"Exporting {items.Count} meshes from {pakDir} (materials={wantMaterials})");
int ok = 0, fail = 0;
foreach (var item in items)
{
    var resolved = Resolve(item.Path);
    if (resolved == null)
        foreach (var alt in item.Alt)
        {
            resolved = Resolve(alt);
            if (resolved != null) { Console.WriteLine($"  ALT {item.Name} <- {alt}"); break; }
        }
    if (resolved == null) { Console.WriteLine($"  SKIP notfound: {item.Path} (+{item.Alt.Count} alts)"); fail++; continue; }
    try
    {
        var uobj = await provider.LoadPackageObjectAsync(resolved);
        if (uobj is not UStaticMesh) { Console.WriteLine($"  SKIP notstaticmesh: {resolved} ({uobj?.GetType().Name})"); fail++; continue; }
        var exporter = new Exporter(uobj, new ExporterOptions {
            MeshFormat = EMeshFormat.Gltf2,
            ExportMaterials = wantMaterials,
        });
        string safe = string.Join("_", item.Name.Split(Path.GetInvalidFileNameChars()));
        var sub = Directory.CreateDirectory(Path.Combine(outDir, safe));
        if (exporter.TryWriteToDir(sub, out var label, out var savedPath))
        {
            // The conversion names the file after the asset it loaded, which differs
            // from the part name when we resolved a fallback path (CUE4Parse would
            // write Body_6.glb where the part is Body). Pin it to the part name.
            var want = Path.Combine(sub.FullName, safe + ".glb");
            if (!string.Equals(savedPath, want, StringComparison.Ordinal))
            {
                if (File.Exists(want)) File.Delete(want);
                File.Move(savedPath, want);
                savedPath = want;
            }
            var size = new FileInfo(savedPath).Length / 1024;
            Console.WriteLine($"  OK {item.Name} <- {resolved} -> {Path.GetFileName(savedPath)} ({size} KB)");
            ok++;
        }
        else { Console.WriteLine($"  WARN {item.Name}: no export written"); fail++; }
    }
    catch (Exception ex) { Console.WriteLine($"  ERR {item.Path}: {ex.GetType().Name}: {ex.Message}"); fail++; }
}
Console.WriteLine($"DONE ok={ok} fail={fail}");
return fail == 0 ? 0 : 1;

class MeshItem
{
    public string Name { get; set; } = "";
    public string Path { get; set; } = "";
    // Fallback pak paths when the blueprint names a mesh that doesn't exist: variants
    // are stored in the base model's folder under a suffixed mesh name (Goliath10 ->
    // Models/Goliath/Body10/Body10, Brcuda -> Models/Muscle_01/Body/Body).
    public List<string> Alt { get; set; } = new();
}
