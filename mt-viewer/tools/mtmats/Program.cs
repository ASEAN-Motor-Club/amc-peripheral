// mtmats — resolve EVERY material a mesh's slots reference, via CUE4Parse's
// material-graph parameter extractor (CMaterialParams2), and decode the diffuse
// texture to PNG.
//
// Why: the glTF exporter only reports *named* texture parameters, so materials
// whose base colour comes from an unexposed TextureSample node export as empty
// (`HasTopDiffuse:false`, no textures) and render white — e.g. the PolygonCity
// material on car wheels. GetParams(CMaterialParams2) walks the graph instead.
//
// usage: mtmats <pakDir> <usmapPath> <aesKey0x> <meshesJson> <outDir> [extraMaterialsJson]
//   extraMaterialsJson: optional JSON array of pak paths. Those materials are not
//   attached to any mesh but still need extracting — vehicle BodyMaterialList
//   entries (liveries/decals such as M_Taxi_01, M_Decal_03, M_Body_With_Decal)
//   are swapped onto the body at runtime and are not referenced by any slot.
//   They come back under result["__materials__"][path].
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
if (argv.Length < 5) { Console.WriteLine("usage: mtmats <pak> <usmap> <key> <meshesJson> <outDir> [extraMaterialsJson]"); return 2; }
var pakDir = argv[0]; var usmapPath = argv[1]; var aesKey = argv[2]; var jsonPath = argv[3]; var outDir = argv[4];
var extrasPath = argv.Length > 5 ? argv[5] : null;
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
        if (tex.PlatformData != null && tex.Format == EPixelFormat.PF_Unknown && Enum.TryParse<EPixelFormat>(tex.PlatformData.PixelFormat, out var pixelFormat))
            typeof(UTexture).GetProperty(nameof(UTexture.Format))!.SetValue(tex, pixelFormat);
        var ct = TextureDecoder.Decode(tex);
        if (ct == null)
        {
            Console.WriteLine($"    tex NULL {tex.GetPathName()} fmt={tex.Format} type={tex.GetType().Name} platform={(tex.PlatformData == null ? "null" : "present")}");
            return null;
        }
        var bytes = TextureEncoder.Encode(ct, ETextureFormat.Png, false, out var ext);
        if (bytes == null || bytes.Length == 0) return null;
        var name = Path.GetFileName(tex.GetPathName()).Replace(".", "_") + ".png";
        var dest = Path.Combine(outDir, "tex", name);
        if (!File.Exists(dest)) File.WriteAllBytes(dest, bytes);
        return "tex/" + name;
    }
    catch (Exception ex) { Console.WriteLine($"    tex ERR {ex.GetType().Name}: {ex.Message}"); return null; }
}

// One material -> its full parameter set. Material instances inherit everything
// from their parent chain, and GetParams on an MIC returns only the instance's own
// overrides, so walk the chain and merge child-first (first value wins).
object Describe(UUnrealMaterial mat, string label)
{
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
    var textureObjects = new Dictionary<string, UTexture>();
    var colors = new Dictionary<string, float[]>();
    var scalars = new Dictionary<string, float>();
    bool translucent = false;
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
                if (kv.Value is UTexture tex2)
                {
                    var key = kv.Key?.ToString() ?? "?";
                    textures.TryAdd(key, tex2.GetPathName());
                    textureObjects.TryAdd(key, tex2);
                }
        if (pp.Colors is IDictionary pd)
            foreach (DictionaryEntry kv in pd)
                if (kv.Value is FLinearColor lc)
                    colors.TryAdd(kv.Key?.ToString() ?? "?", new[] { lc.R, lc.G, lc.B, lc.A });
        if (pp.Scalars is IDictionary sd)
            foreach (DictionaryEntry kv in sd)
                if (kv.Value is float f) scalars.TryAdd(kv.Key?.ToString() ?? "?", f);
    }
    var p2 = paramsAll.Count > 0 ? paramsAll[0] : new CMaterialParams2();

    string? SelectTexture(string semantic)
    {
        bool Has(string value, string needle) => value.Contains(needle, StringComparison.OrdinalIgnoreCase);
        bool Placeholder(string value) => Has(value, "RT_") || Has(value, "ActiveLayerCRT2D") || Has(value, "UE4_LOGO_CARD");
        var candidates = textureObjects.Keys.Where(k => !Placeholder(k) && !Placeholder(textureObjects[k].GetPathName())).ToList();
        if (semantic == "baseColor")
        {
            foreach (var preferred in new[] { "Base Color Texture", "BaseColor", "Diffuse" })
            {
                var hit = candidates.FirstOrDefault(k => k == preferred);
                if (hit != null) return hit;
            }
            var palette = candidates.FirstOrDefault(k =>
                (Has(k, "colorPalette") || Has(k, "Palette_") || Has(k, "Texture_01_A")) &&
                !Has(k, "rough") && !Has(k, "metal") && !Has(k, "normal") && !Has(k, "emissive"));
            if (palette != null) return palette;
            return candidates.FirstOrDefault(k => k == "PM_Diffuse" && !Has(textureObjects[k].GetPathName(), "rough"));
        }
        var needle = semantic switch {
            "roughness" => "rough", "metallic" => "metal", "normal" => "normal", "emissive" => "emissive",
            _ => "__never__"
        };
        return candidates.FirstOrDefault(k => Has(k, needle) || Has(textureObjects[k].GetPathName(), needle));
    }

    var maps = new Dictionary<string, string>();
    var mapAssets = new Dictionary<string, string>();
    foreach (var semantic in new[] { "baseColor", "roughness", "metallic", "normal", "emissive" })
    {
        var key = SelectTexture(semantic);
        if (key == null) continue;
        var texture = textureObjects[key];
        mapAssets[semantic] = texture.GetPathName();
        var encoded = EncodePng(texture);
        if (encoded != null) maps[semantic] = encoded;
    }
    maps.TryGetValue("baseColor", out var png);
    mapAssets.TryGetValue("baseColor", out var diffuseAsset);

    Console.WriteLine($"  {label} -> {mat.GetPathName()} [{mat.GetType().Name}] chain={chain.Count} blend={p2.BlendMode} tr={translucent} " +
                      $"diffuse={p2.HasTopDiffuse} tex={string.Join(",", textures.Keys)} col={string.Join(",", colors.Keys)} scl={string.Join(",", scalars.Keys)} png={png}");

    return new
    {
        slot = label,
        material = mat.GetPathName(),
        materialName = Path.GetFileName(mat.GetPathName()),
        cls = mat.GetType().Name,
        chain = chain.Select(c => c.GetPathName()).ToList(),
        blendMode = p2.BlendMode.ToString(),
        translucent,
        masked = p2.BlendMode.ToString() == "BLEND_Masked",
        hasDiffuse = p2.HasTopDiffuse,
        textures,
        maps,
        mapAssets,
        colors,
        scalars,
        diffusePng = png,
        diffuseTex = diffuseAsset,
    };
}

List<Dictionary<string, object>> SectionSlots(UStaticMesh sm)
{
    try
    {
        var type = sm.GetType();
        object? renderData = (object?)type.GetProperty("LODModels")?.GetValue(sm)
            ?? type.GetProperty("RenderData")?.GetValue(sm)
            ?? type.GetProperty("LODs")?.GetValue(sm);
        if (renderData is not null && renderData is not Array)
        {
            var rdType = renderData.GetType();
            renderData = rdType.GetProperty("LODs")?.GetValue(renderData)
                ?? rdType.GetField("LODs", System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)?.GetValue(renderData);
        }
        if (renderData is not Array lods || lods.Length == 0 || lods.GetValue(0) is not { } lod) return new List<Dictionary<string, object>>();
        var lodType = lod.GetType();
        var sections = (lodType.GetProperty("Sections") ?? lodType.GetProperty("Sections_GENERAL"))?.GetValue(lod) as Array;
        if (sections == null) return new List<Dictionary<string, object>>();
        var rows = new List<Dictionary<string, object>>();
        foreach (var section in sections)
        {
            if (section == null) continue;
            var sectionType = section.GetType();
            object? Get(string name) => (object?)sectionType.GetProperty(name)?.GetValue(section)
                ?? sectionType.GetField(name, System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)?.GetValue(section);
            if (Get("MaterialIndex") is not int index || index < 0 || index >= sm.StaticMaterials.Length) return new List<Dictionary<string, object>>();
            var triangles = Get("NumTriangles") is int count ? count : -1;
            rows.Add(new Dictionary<string, object> {
                ["slot"] = sm.StaticMaterials[index].MaterialSlotName.Text,
                ["triangles"] = triangles,
            });
        }
        return rows;
    }
    catch (Exception ex)
    {
        Console.WriteLine($"    section mapping failed: {ex.Message}");
        return new List<Dictionary<string, object>>();
    }
}

var items = JsonSerializer.Deserialize<List<Item>>(File.ReadAllText(jsonPath),
    new JsonSerializerOptions { PropertyNameCaseInsensitive = true })!;
var result = new Dictionary<string, object>();
var sectionResults = new Dictionary<string, List<Dictionary<string, object>>>();

foreach (var it in items)
{
    var meshPath = Resolve(it.Path) ?? it.Alt.Select(Resolve).FirstOrDefault(x => x != null);
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
        slots.Add(Describe(mat, slotName));
    }
    result[it.Name] = slots;
    sectionResults[it.Name] = SectionSlots(sm);
}
result["__sections__"] = sectionResults;

// materials that no mesh slot points at (vehicle body/livery variants)
if (extrasPath != null && File.Exists(extrasPath))
{
    var extras = JsonSerializer.Deserialize<List<string>>(File.ReadAllText(extrasPath)) ?? new List<string>();
    var mats = new Dictionary<string, object>();
    foreach (var raw in extras)
    {
        var path = Resolve(raw);
        if (path == null) { Console.WriteLine($"=== extra {raw}: NOT FOUND"); continue; }
        Console.WriteLine($"=== extra {raw}");
        try
        {
            var mo = await provider.LoadPackageObjectAsync(path);
            if (mo is UUnrealMaterial um) mats[raw] = Describe(um, "extra");
            else Console.WriteLine($"  not a material: {mo?.GetType().Name}");
        }
        catch (Exception ex) { Console.WriteLine($"  load ERR {ex.GetType().Name}: {ex.Message}"); }
    }
    result["__materials__"] = mats;
}

File.WriteAllText(Path.Combine(outDir, "mesh_materials.json"),
    JsonSerializer.Serialize(result, new JsonSerializerOptions { WriteIndented = true }));
Console.WriteLine($"WROTE {Path.Combine(outDir, "mesh_materials.json")}");
return 0;

class Item { public string Name { get; set; } = ""; public string Path { get; set; } = ""; public List<string> Alt { get; set; } = new(); }
