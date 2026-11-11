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

string DeRepeat(string p)
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
    if (resolved == null) { Console.WriteLine($"  SKIP notfound: {item.Path}"); fail++; continue; }
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
}
