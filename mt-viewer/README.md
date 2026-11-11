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
tools/glb_slots.py       rewrite GLB materials so each primitive carries its slot name
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

### Broken blueprint mesh paths

Some blueprints name a mesh that isn't in the pak — variants point at the base
model's folder, and a few names simply don't exist. Exports silently produced no
file, so those vehicles rendered with a missing body. Handled in two places:

- `tools/mesh_overrides.json` — verified `Vehicle|blueprintPath` → real asset path.
  Every entry was confirmed by exporting the candidate and reading the exporter's
  `OK <name> <- <path>` line. Do not add entries by guessing: Goliath ships
  `Body4` and `Body_6` and has **no** `Body_10` at all, so the pattern lies.
- `mk_manifest.mesh_alts()` — heuristic fallbacks (vehicle-name suffix, sibling
  model folders) emitted as `alt` paths that `mtglb`/`mtmats` try in order.

Two consequences worth remembering: the exporter must rename its output to the
**part** name (CUE4Parse writes `Body_6.glb` when it resolved a fallback asset, and
every consumer looks for `Body.glb`), and `mtmats` must resolve the same fallback
paths or the mesh ends up with geometry but no materials.

`tools/verify_site.py` is the regression check: it walks every staged vehicle and
fails a slug when a part's GLB is missing/empty, a texture is missing, or a GLB
primitive carries a material name that isn't a known slot.

### Paints: ColorSlots, BodyColors, and how a body gets its colour

Paint is **not** in the material. It is on the vehicle CDO, and `mk_manifest.py`
copies it into the manifest:

- `colorSlots` — the regions the vehicle exposes (`Body_01`, `Body_02`, `Window`,
  `Seat_01`, …) with their default colour, metallic and roughness. These keys are
  the same strings as the mesh's **material slot names**, which is why the GLB is
  rewritten to name each primitive after its slot.
- `paints` — the `BodyColors` array: the handful of default paint schemes the game
  picks from at random on spawn. One slot = whole-vehicle colour; several slots =
  two-tone (the Atlas tanker paints its cab `Body_01` and its tank `Body_02`).

**The alpha channel is not an "unset" flag.** Boxy's four default paints are navy,
charcoal, light grey and white; three of them carry alpha 0. Reading alpha 0 as
"no colour" silently discards three quarters of every vehicle's default paints.
Alpha is only meaningful for slots flagged `bUseColorAlpha` (glass). A slot the
scheme doesn't mention keeps its `ColorSlot` default.

The viewer exposes both: a dropdown over the vehicle's own default variants
(`?scheme=N`) and a free colour picker that paints `Body_*` only (`?paint=%23c9302c`).

### Data facts that are NOT bugs

- **Stock bodies default to a paint, not to white.** `M_Body` is `Color #FFFFFF`
  because the colour is supplied at runtime; the manifest supplies it.
- **`M_Palette` is the livery atlas** (`Palette_PolygonCity_Texture_01_A`,
  1024², shared by every vehicle) and covers the whole shell as its own primitive.
- **Lamps** expose only runtime scalars (`HeadLight`/`BrakeLight` = 0), so their
  emissive colour is a deliberate choice, flagged `"synthetic": "lamp"`.
- **`M_Mirror`'s only texture is `UE4_LOGO_CARD`** — a placeholder standing in
  for an in-game render target. Mirrors get a metal finish, `"synthetic":"mirror"`.
- A material that resolves to nothing is rendered neutral dark and flagged
  `"synthetic": "no-data"` rather than blowing out to white.

### The GLB trap: section order is not slot order

CUE4Parse emits primitives in **section order** with a correct material reference,
which is not the UE material-slot order and not the order of the glTF material
array. Boxy's `Body.glb` emits the `M_Palette` section first (8405 verts, the whole
shell) and `M_Body` second (2500) — so mapping primitive *index* to slot *index*
paints the wrong surface and the van ignores every colour change. `tools/glb_slots.py`
rewrites each GLB so every primitive carries its slot name, matching on the
primitive's original material name and taking the next unused slot that owns it.
That rewrite is also what lets `Body_01` and `Body_02` (same `M_Body` asset) hold
different colours.

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
- default paints, mean RGB over model pixels: navy `?scheme=0` (85,109,146),
  charcoal `?scheme=1` (85,103,133), white `?scheme=3` (161,159,161) — three
  different renders from the same vehicle, which is the check that proves the
  CDO paint is reaching the surface rather than a material default

## Status / known limitations

- Catalogue: **174 of 175 staged vehicles pass `tools/verify_site.py`** (every
  part has geometry, every texture is on disk, every GLB primitive carries a known
  slot name). 1794 parts, 2355 material slots, 639 textured.
- **`goliath10` has no body asset in the pak.** Its blueprint points at
  `Models/Goliath/Body/Body`, which does not exist, and no `Body*` sibling matches
  a 10-wheel variant — the other Goliath models ship `Body4` and `Body_6` only.
  Its 25 wheels/fifth-wheel parts stage fine, the body is absent. Treat as cut or
  unfinished content, not an extraction bug.
- `brcuda`/`edit1` render from `Models/Muscle_01/Body` (their blueprint names a
  `Brcuda` folder that doesn't exist) — the shell is complete but the **door panel
  is missing** in the render; the door isn't a separate component in the blueprint
  and isn't in the body mesh's sections.
- `goliath6` stages as a lowboy deck + gooseneck with **no cab**; the Goliath
  family appears to be trailer-side models whose tractor isn't referenced.
- Verified end to end on Boxy (van), Panther (roadster), Atlas_6x4_Semi
  (tractor), Atlas_6x2_Tanker (two-tone: cab `Body_01`, tank `Body_02`),
  Atlas_6x2_Dryvan (blue cab, charcoal box), Bongo_Bus (variant, geometry and
  paints inherited from `Bongo`).
- **35 of 175 vehicle blueprints ship no paint data at all.** Their parsed
  blueprint has no `Default__<Vehicle>_C` export, so there is no `ColorSlots`
  and no `BodyColors` to read: `brcuda, cheetahmk1, conter_*, dinky_*, edit1,
  elisataxi, formulascm, fox, gunthoo*, kart_01, liliput, nuketaxi, panther,
  police, policeinterceptor1, raven, savannah, scm_kart_one, scooty, spider,
  tavan, tavan_ambulance, terra, trailer_30ft_tanker_01, trailer_small_cage_01,
  vista, vulcan, zero` (plus `mtvehiclebasebp`, which is a base class, not a
  vehicle). These render with the material default — Panther comes out white —
  and the colour picker still works. Do not invent a table for them.
- Trailer/attachment-only blueprints and aircraft-style parts are unverified.
- Assets are version-locked: the pak, usmap and key move together. A GLB built
  for the wrong game version does not error, it renders wrong.
- The catalogue run is sequential, ~20 s per vehicle after the pak is warm;
  run it as a background job, not in a foreground session.
