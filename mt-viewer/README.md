# Motor Town Vehicle 3D Viewer

Interactive three.js viewer for Motor Town vehicles, served as a static site.
Geometry **and materials** come from the game's client PAK; nothing is hand-made.

## What is in here

```
index.html               viewer (three.js from CDN, no build step)
tools/mk_manifest.py     vehicle blueprint -> reassembly manifest (world transforms)
tools/mtglb/             CUE4Parse exporter: mesh -> GLB per part
tools/mtmats/            CUE4Parse material-graph params -> per-slot textures/colours
tools/bake_materials.py  extractor output -> materials.json + deduped textures
tools/stage_vehicle.sh   one vehicle: manifest -> GLB -> materials -> site/<slug>/
tools/stage_all.sh       every vehicle blueprint, resumable
tools/make_index.py      site/vehicles.json (the viewer's vehicle picker)
tools/compare_shots.py   numeric A/B between two headless screenshots
tools/png_sample.py      tiny PNG reader used by the checks above
default.nix              Nix static package for the site
```

Generated assets (`site/<slug>/`: manifest, `glb/`, `textures/`,
`materials.json`) are **not** in git — they are ~1-6 MB per vehicle and are
regenerated per game version. Keep them on the web host or in a release.
`boxy.json` / `glb/` / `preview.png` are the pre-materials prototype and are
superseded by `site/<slug>/`.

## Reassembly model

Vehicle parts (body, doors, wheels, mirrors) are separate meshes in the game
PAK. `mk_manifest.py` walks the blueprint's component `AttachParent` chain,
composes world transforms and emits `{part, glb, position, quaternion, scale}`
per part, deduped by pak path.

**Units / axes:** blueprint `RelativeLocation` is UE centimetres, Z-up,
X-forward; part geometry is exported in metres. The conversion happens once in
`mk_manifest.py`: `p' = (x, z, -y)/100`, scale `(sx, sz, sy)`, rotation
conjugated by −90° about X. The viewer applies those world transforms directly.

**Variants:** `Bongo_Bus`, `Truck_Police` and friends serialize no mesh
assignments — the geometry lives on the base class. `mk_manifest.py` detects a
mesh-less blueprint, strips `_`-suffixed name segments until a sibling blueprint
with meshes exists, and merges the base's component transforms under the child's
overrides. The manifest records `inheritedFrom`.

## How materials work (the easy-to-get-wrong part)

`CUE4Parse` with `ExportMaterials=true` does **not** write glTF PBR materials.
It writes, per mesh, a mirrored tree of UE material JSON + decoded PNGs, and
leaves GLB materials as bare names (`{"name":"M_Body","pbrMetallicRoughness":{}}`).
Two passes are therefore needed:

1. `mtglb` — geometry, material **slot names** preserved per primitive.
2. `mtmats` — per slot `UMaterialInterface.GetParams(CMaterialParams2)`, walking
   the `UMaterialInstance.Parent` chain (an MI returns only its own overrides).
   This is the only pass that finds materials whose base colour hangs off an
   **unnamed** `TextureSample` node — car wheels are exactly that case, and they
   render white without it.

`bake_materials.py` emits `materials.json` keyed by material name:
baseColor / metalness / roughness / opacity / alphaMode / map / roughnessMap /
metalnessMap / normalMap. The viewer builds one `MeshStandardMaterial` per name.

### Data facts that are NOT bugs

- **Stock bodies are white.** `M_Body` is `Color #FFFFFF`, Metallic 0.3,
  Roughness 0.5, no texture — the game applies paint at the paint shop. The
  viewer ships a paint picker for this (`?paint=%23c9302c` also works).
- **`M_Palette` is the livery atlas** (`Palette_PolygonCity_Texture_01_A`,
  1024², shared by every vehicle).
- **Lamps** expose only runtime scalars (`HeadLight`/`BrakeLight` = 0), so their
  emissive colour is a deliberate choice, flagged `"synthetic": "lamp"`.
- **`M_Mirror`'s only texture is `UE4_LOGO_CARD`** — a placeholder standing in
  for an in-game render target. Mirrors get a metal finish, `"synthetic":"mirror"`.
- A material that resolves to nothing is rendered neutral dark and flagged
  `"synthetic": "no-data"` rather than blowing out to white.

## Build

Requires: client PAK, its AES key, matching usmap, .NET 10 SDK, and — for texture
decode — `libSkiaSharp.so` + `libfontconfig.so.1` on `LD_LIBRARY_PATH` (see
`tools/mtglb/build.sh` and `tools/mtmats.sh`, which keep those assignments inside
the scripts rather than on a command line).

```bash
tools/stage_vehicle.sh Boxy boxy        # one vehicle -> site/boxy/
tools/stage_all.sh                      # whole catalogue, resumable
tools/stage_all.sh 10 '^(Zino|Tavan)'   # limit + filter
python3 tools/make_index.py site        # refresh site/vehicles.json
```

Serve `site/` and open `index.html?vehicle=<slug>`.

### Verifying without a human looking at it

`index.html?sync` renders exactly one frame (no rAF loop) for headless capture;
`tools/compare_shots.py a.png b.png` reports mean per-pixel difference and mean
RGB over model pixels — enough to prove a material change reached the GPU:

- textured vs `?plain` (flat clay): 37% of body-band pixels change, |diff| 46/765
- `?paint=#c9302c` vs default: body band mean (143,143,145) → (106,21,34)
- tyres: lit pixels in the lower band drop 17.6k → 8.7k when rubber replaces clay

## Status / known limitations

- Verified end to end on Boxy (van), Panther (roadster), Atlas_6x4_Semi
  (tractor), Bongo_Bus (variant, geometry inherited from `Bongo`).
- Trailer/attachment-only blueprints and aircraft-style parts are unverified.
- Assets are version-locked: the pak, usmap and key move together. A GLB built
  for the wrong game version does not error, it renders wrong.
- The catalogue run is sequential (one pak mount per vehicle, ~60-90 s each);
  run it as a background job, not in a foreground session.
