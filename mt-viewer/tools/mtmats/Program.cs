// mtmats — resolve EVERY material a mesh's slots reference, via CUE4Parse's
// material-graph parameter extractor (CMaterialParams2), and decode the diffuse
// texture to PNG.
//
// Why: the glTF exporter only reports *named* texture parameters, so materials
// whose base colour comes from an unexposed TextureSample node export as empty
// (`HasTopDiffuse:false`, no textures) and render white — e.g. the PolygonCity
// material on car wheels. GetParams(CMaterialParams2) walks the graph instead.
//
// usage: mtmats <pakDir> <usmapPath> <aesKey0x> <meshesJson> <outDir>
// output: <outDir>/mesh_materials.json  + <outDir>/tex/*.png
using CUE4Parse.FileProvider;
using CUE4Parse.UE4.Assets.Exports;
using CUE4Parse.UE4.Assets.Exports.Material;
using CUE4Parse.UE4.Assets.Exports.StaticMesh;
using CUE4Parse.UE4.Assets.Exports.Texture;
using CUE4Parse.UE4.Objects.Core.Misc;
using CUE4Parse.UE4.Objects.Core.Math;
using CUE4Parse.UE4.Versions;
using CUE4Parse.Encryption.Aes;
using CUE4Parse.MappingsProvider.Usmap;
using CUE4Parse_Conversion.Textures;
using System.Collections;
using System.Text.Json;
using System.IO;

var argv = Environment.GetCommandLineArgs().Skip(1).ToArray();
if (argv.Length < 5) { Console.WriteLine("usage: mtmats <pak> <usmap> <key> <meshesJson> <outDir>"); return 2; }
var pakDir = argv[0]; var usmapPath = argv[1]; var aesKey = argv[2]; var jsonPath = argv[3]; var outDir = argv[4];
Directory.CreateDirectory(Path.Combine(outDir, "tex"));

var provider = new DefaultFileProvider(pakDir, SearchOption.AllDirectories, false,
    new VersionContainer(EGame.GAME_UE5_5));
provider.MappingsContainer = new FileUsmapTypeMappingsProvider(usmapPath);
provider.Initialize();
provider.SubmitKey(new FGuid(), new FAesKey(aesKey));
try { provider.LoadLocalization(); } catch { }

string DeRepeat(string p)
{
    var parts = p.Split('/');
    if (parts.Length >= 2 && parts[^1] == parts[^2]) return string.Join("/", parts.Take(parts.Length - 1));
    return p;
}
string? Resolve(string path)
{
    foreach (var c in new[] { path, DeRepeat(path) })
        if (provider.TryGetGameFile(c, out _)) return c;
    var de = DeRepeat(path);
    var keys = provider.Files.Keys
        .Where(k => k.StartsWith(de + ".") && k.EndsWith(".uasset", StringComparison.OrdinalIgnoreCase))
        .Select(DeRepeat).Distinct().ToList();
    return keys.Count > 0 ? keys[0] : null;
}

string? EncodePng(UTexture tex)
{
    try
    {
        var ct = TextureDecoder.Decode(tex);
        if (ct == null) return null;
        var bytes = TextureEncoder.Encode(ct, ETextureFormat.Png, false, out var ext);
        if (bytes == null || bytes.Length == 0) return null;
        var name = Path.GetFileName(tex.GetPathName()).Replace(".", "_") + ".png";
        var dest = Path.Combine(outDir, "tex", name);
        if (!File.Exists(dest)) File.WriteAllBytes(dest, bytes);
        return "tex/" + name;
    }
    catch (Exception ex) { Console.WriteLine($"    tex ERR {ex.GetType().Name}: {ex.Message}"); return null; }
}

var items = JsonSerializer.Deserialize<List<Item>>(File.ReadAllText(jsonPath),
    new JsonSerializerOptions { PropertyNameCaseInsensitive = true })!;
var result = new Dictionary<string, List<object>>();
var seenMat = new HashSet<string>();

foreach (var it in items)
{
    var meshPath = Resolve(it.Path);
    if (meshPath == null) { Console.WriteLine($"=== {it.Name}: NOT FOUND"); continue; }
    var obj = await provider.LoadPackageObjectAsync(meshPath);
    if (obj is not UStaticMesh sm) { Console.WriteLine($"=== {it.Name}: not a StaticMesh"); continue; }
    var slots = new List<object>();
    Console.WriteLine($"=== {it.Name}");
    foreach (var s in sm.StaticMaterials)
    {
        var slotName = s.MaterialSlotName.Text;
        UUnrealMaterial? mat = null;
        try { mat = s.MaterialInterface.Load() as UUnrealMaterial; } catch { }
        if (mat == null) { Console.WriteLine($"  slot '{slotName}': null"); continue; }

        // Material instances inherit everything from their parent chain, and
        // GetParams on an MIC returns only the instance's own overrides — so walk
        // the chain and merge child-first (first value wins).
        var chain = new List<UUnrealMaterial>();
        {
            UUnrealMaterial? cur = mat;
            int guard = 0;
            while (cur != null && guard++ < 6)
            {
                if (!chain.Contains(cur)) chain.Add(cur);
                cur = (cur as UMaterialInstance)?.Parent;
            }
        }

        var textures = new Dictionary<string, string>();
        var colors = new Dictionary<string, float[]>();
        var scalars = new Dictionary<string, float>();
        bool translucent = false;
        UTexture? firstTex = null;
        var paramsAll = new List<CMaterialParams2>();

        foreach (var m2 in chain)
        {
            var pp = new CMaterialParams2();
            try { m2.GetParams(pp, EMaterialFormat.FirstLayer); }
            catch (Exception ex) { Console.WriteLine($"    GetParams ERR on {m2.GetPathName()}: {ex.Message}"); }
            paramsAll.Add(pp);
            if (!translucent && pp.IsTranslucent) translucent = true;
            if (pp.Textures is IDictionary td)
                foreach (DictionaryEntry kv in td)
                    if (kv.Value is UObject t2)
                        textures.TryAdd(kv.Key?.ToString() ?? "?", t2.GetPathName());
            if (pp.Colors is IDictionary pd)
                foreach (DictionaryEntry kv in pd)
                    if (kv.Value is FLinearColor lc)
                        colors.TryAdd(kv.Key?.ToString() ?? "?", new[] { lc.R, lc.G, lc.B, lc.A });
            if (pp.Scalars is IDictionary sd)
                foreach (DictionaryEntry kv in sd)
                    if (kv.Value is float f) scalars.TryAdd(kv.Key?.ToString() ?? "?", f);
            if (firstTex == null && pp.TryGetFirstTexture2d(out var dt) && dt != null) firstTex = dt;
        }
        var p2 = paramsAll[0];

        string? png = null;
        if (firstTex != null) png = EncodePng(firstTex);

        Console.WriteLine($"  slot '{slotName}' -> {mat.GetPathName()} [{mat.GetType().Name}] chain={chain.Count} blend={p2.BlendMode} tr={translucent} " +
                          $"diffuse={p2.HasTopDiffuse} tex={string.Join(",", textures.Keys)} col={string.Join(",", colors.Keys)} scl={string.Join(",", scalars.Keys)} png={png}");

        slots.Add(new
        {
            slot = slotName,
            material = mat.GetPathName(),
            materialName = Path.GetFileName(mat.GetPathName()),
            cls = mat.GetType().Name,
            chain = chain.Select(c => c.GetPathName()).ToList(),
            blendMode = p2.BlendMode.ToString(),
            translucent,
            masked = p2.BlendMode.ToString() == "BLEND_Masked",
            hasDiffuse = p2.HasTopDiffuse,
            textures,
            colors,
            scalars,
            diffusePng = png,
        });
    }
    result[it.Name] = slots;
}

File.WriteAllText(Path.Combine(outDir, "mesh_materials.json"),
    JsonSerializer.Serialize(result, new JsonSerializerOptions { WriteIndented = true }));
Console.WriteLine($"WROTE {Path.Combine(outDir, "mesh_materials.json")}");
return 0;

class Item { public string Name { get; set; } = ""; public string Path { get; set; } = ""; }
