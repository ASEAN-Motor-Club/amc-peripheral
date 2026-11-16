# Motor Town vehicle decal UV mechanism — recovered spec

Status: exact shader-5020 equations transcribed and implemented in the viewer; live game-bake residual unverified.
Last update: 2026-11-16. Client under test: Motor Town 0.7.19 / Build 1111 (Steam AppID 1369670).

The authoritative math is in `decal-projection-equations.md`; the tested CPU implementation is
`tools/decal_projection.py`, and the browser implementation is `site/js/decal-projection.js`.
All 1,171 production layers were cross-checked at three local positions each between the Python
and JavaScript implementations (14,052 UV coordinates, maximum absolute difference 1.14e-13).

> **2026-11-16 correction:** the earlier “non-standard DXBC container / section framing” diagnosis
> below is superseded. The archive code region is compressed; readable chunk tags were compressed-stream
> literals. Using the documented `FSerializedShaderArchive` layout resolves material map 266 to exactly
> three shaders (indices 5019–5021), with a code base of 734,498 and the final entry ending exactly at EOF.
> Their `8C 0A` streams require Oodle decompression. Follow `decal-constants-plan.md`, not the obsolete
> byte-carving and container-reconstruction work below.

## Objective

Recover the exact transform the game applies to a decal layer so the web viewer can
reproduce it verbatim instead of approximating. Acceptance was defined as a per-pixel
numeric residual between the viewer's projection and the game's own baked `DecalRT`.

## What is PROVEN (live objects, this client)

A decal is **not** stamped into mesh UV space. It is a **box projection baked to a render
target**, then consumed by the body material.

1. `UMTDecalBaker` (exactly 1 instance, lives in the world) owns:
   - `BoundsActor` — an `AActor`/`StaticMeshActor` that defines the projection box.
   - `SceneCaptureComponent2D` + `ScratchUndilatedRT`, `DilatedBoundsRT`, `DilatedNormalRT`
     (1024²), plus `BoundDilateMaterial`-style material instances.
2. The capture renders, from the decal's direction, the mesh's **position inside the box**
   (`LocalBounds`) and its **normals** (`LocalNormal`), dilated to avoid seam bleeding.
3. The brush material `M_DecalBounds_Test` samples the decal texture through those two maps
   into the mesh's UV space, writing into a per-mesh `FMTDecalTargetMesh { UTextureRenderTarget2D* DecalRT; UStaticMesh* StaticMesh; }`
   held in `UMTDecalComponent.TargetMeshComponents` (a `TMap`).
4. Body materials (`M_BodyDecalable`, `M_Body_Decal_Star`) sample those RTs. 30 pooled
   `DecalActiveLayerRT` targets exist at **2048²**.

This explains the shader contract seen in the cooked material: `LocalBounds` and `LocalNormal`
are *drivers*, not parameters the game sets per layer — they are produced by the baker.

## Parameter contract (from the cooked material's NameMap)

`/Game/Materials/VehicleDecal/M_DecalBounds_Test`, 57 name entries, includes:

`PositionX`, `PositionY`, `Roll`, `Yaw`(rotation group incl. `PitchDown`), `Coverage`,
`CurrentLayerTexture`, `LocalBounds`, `LocalNormal`, `DecalUVChannel`, `LayerIndex`,
`Flip`, `Mirror`, `OppositeCull`, `BackFaceCull`, `Highlight`, `IsAlphaOnlyTexture`,
`Color`, `BaseLayer`, `DefaultTexture`.

Plugin path confirms the family:
`/Game/AdvancedDecal/Materials/MaterialBrushes/BoundsBased/Utils/T_PreviewSphereLocalBounds`.

`PositionX`/`PositionY` are **scalars**, not a vector — consistent with an in-plane offset
whose units are decided by C++, not by the material.

## Where the per-layer transform actually lives

`UMTDecalLayer` (`/Script/MotorTown.MTDecalLayer`, size 0xD8) holds only:
`Texture` (soft), `LoadedTexture`, `BrushMaterial`, `DynamicBrushMaterial`.
There is **no** position/rotation/scale field on the layer object.

=> The transform is stored as **scalar/vector parameters on `DynamicBrushMaterial`** (a MID
created by `UMTDecalComponent` from `BrushMaterial` + the layer's authored values), and the
authored values arrive as `FMTDecalLayer` structs inside `FMTVehicleDecal.DecalLayers`.

## Data evidence (production saves, 1171 layers across 45 vehicles)

- All 1171 layers sit inside ±1000 on both Position axes (X p05 −278 / p95 144,
  Y p05 −73 / p95 278) → reads as **per-mille of the mesh's local bounds**, not cm/m.
- `DecalScale` observed 0.06 … 4.37; `Stretch` 0.43 … 5.12.
- Every one of the 412 Decals DataTable rows binds `BrushMaterial = M_DecalBounds_Test`.

## The one unknown

The exact function
`uv = f(localPos, LocalBounds, PositionX, PositionY, Rotation, DecalScale, Stretch, Coverage, DecalUVChannel)`
— specifically the units of `PositionX/Y` relative to `LocalBounds`, and whether
`DecalScale` multiplies a bounds dimension before `TextureScale`.

## How to close it (the experiment that still needs doing)

Any of these produces the missing numbers. All require a **live decal**, which is the blocker.

1. **Manual (cheapest, ~10 s of a human):** load the profile, open any vehicle's decal
   editor in the garage. Then read:
   - `MTDecalBaker.BoundsActor` world transform (this is the projection box pose),
   - each layer's `DynamicBrushMaterial` scalar/vector params,
   - the mesh's local bounds,
   for 3–5 layers, and solve the transform from the correspondences.
2. **Sweep (after 1):** set `PositionX`/`DecalScale` on the MID to known values, export the
   `DecalRT`, and fit. Residual against the game bake is the acceptance test.
3. **Native mod:** a C++ UE4SS mod can build `FMTVehicleDecal`, read the `TMap`, and
   `ReadPixels` the RT. `mt-cam-hook` already has the cross-compile pipeline.

## Attempt: decompile the plugin (2026-11-13)

The plugin cannot be decompiled, because it is not a binary. Zero DLLs ship for it
(no plugin folder, and every DLL under `Binaries/Win64` is a third-party upscaler/SDL/boost).
Only four assets from it are cooked into the pak:

- `AdvancedDecal/Materials/RT_ActivePreview`, `RT_LayerPreview`
- `AdvancedDecal/Materials/MaterialBrushes/BoundsBased/Utils/T_PreviewSphereLocalBounds`
- `AdvancedDecal/Materials/MaterialFunctions/MF_CombineDecalLayers`  ← the real per-layer math
- `AdvancedDecal/Materials/MaterialBrushes/Text/Roboto`

Their graphs are stripped (`PKG_FilterEditorOnly`), so there is no Blueprint bytecode to read.
The marketplace description confirms the design: *"UV independent Mesh Decal Projection …
projects, packs and bakes all decal texture to the mesh UV"*, 3 CanvasRenderTarget2D per actor.

**The math survives only as compiled DXBC.** Progress made:

- Extracted `ShaderArchive-MotorTown-PCD3D_SM5-PCD3D_SM5.ushaderbytecode` with the Rust
  extractor's `--raw` mode → **56,636,716 bytes**, containing **14,449 DXBC blobs**
  (first `DXBC` magic at offset 734,547; directory occupies the first ~734 KB).
- Archive header: `uint32 2` (version), `uint32 678` (shader maps), then **678 × 20-byte
  map hashes** at offset 8, then `uint32 14486` and **14,486 × 20-byte shader hashes** at 13,572,
  then the map-entry table at 303,292.
- **The material is identified inside the archive**: `M_DecalBounds_Test.uexp` contains the
  20-byte map hash at **index 266**. So its compiled shaders are present and locatable.

Remaining step: finish the directory parse (map entry → shader indices → code offset/size).
Map entry 266 reads as `(2958, 34)`; the candidate index list at `308724 + 4*34` is
`[1, 11507, 21, 3064, 2, 11528, 21, 3066, 5, 11549, 21, 3071]` (all < 14486, so a real list),
but the entry field order is not yet settled. Alternative that needs no directory at all:
carve every blob by `DXBC` magic + the TotalSize field at offset 24, then disassemble with
`vkd3d-compiler` and filter for the decal brush's signature.

## DXBC attempt — what worked, where it stalled (2026-11-13)

Worked and reusable:

- `--raw` extraction of `ShaderArchive-MotorTown-PCD3D_SM5-PCD3D_SM5.ushaderbytecode` →
  **56,636,716 bytes**, 14,449 `DXBC` magics, directory in the first ~734 KB.
- **Reverse-engineered the DXBC checksum.** It is MD5 over bytes `[20:]` of the container with a
  non-standard final block: `num_bits = len*8` written as a u32 *before* the leftover tail (not after),
  and `num_bits2 = (num_bits >> 2) | 1` placed in the last word of the padding block. Implemented in
  `dxbcsum2.py`; **verified against vkd3d**, which accepts a container whose checksum field we compute
  this way (it then fails on later fields, proving the checksum itself is right). The checksum UE stores
  in the file does not match this algorithm, so UE rewrites or strips it.
- Material→archive link: `M_DecalBounds_Test.uexp` contains the 20-byte map hash at **index 266** of the
  archive's 678-entry map-hash table.
- Sample shader's section list recovered: `ISGN` at +30 (70 B), `OSGN` at +108 (18 B), `SHEX` at +134.

Stalled on: UE's container framing is not the D3D one. The header is 30 bytes (not 32), the field at
+20 reads `0x030afc01` where D3D expects version `1`, and neither the `ISGN` payload nor the `SHEX`
payload starts with the D3D structures — the `ISGN` body has no plausible element count at any 4-byte
alignment in +34..+46, and **there is no `0xFFFE0500` shader-model token anywhere in the first shader**,
so the `SHEX` section is not a raw SM5 token stream. Building a canonical container from the extracted
sections gets past the checksum and the chunk table, then dies in signature parsing (E0008) or compile
(-3). Conclusion: extracting the decal shader needs UE's own section format reversed first — a second
format-reversing project on top of the one just finished.

### Cheaper paths, in order of cost

1. **One live decal** (~10 s of a human): load the profile, open a vehicle's decal editor. Read
   `MTDecalBaker.BoundsActor` transform + `DynamicBrushMaterial` params + mesh bounds, solve the transform.
2. **Native baker in Ghidra**: the exe is already loaded in `/var/lib/rea/work/spike5`. The baker is one
   function; it answers "what is Position converted from" — the half the shader would not answer anyway.
3. Continue the shader route only if (1) and (2) are both refused.

## Runtime routes that DO NOT work (do not retry)

| Route | Result |
|---|---|
| `v.Net_Decal = {DecalLayers={L}}` + `OnRep_Decal()` | returns true, array stays empty |
| `v:ServerSetDecal({DecalLayers={L}})` | returns ok, `Layers` stays 0 |
| `pc:ServerSpawnVehicle({... Decal={...}})` | **hangs the game thread** (0x380 struct) |
| `cont.Layers:Add(StaticConstructObject(MTDecalLayer))` | `Add` unsupported / array null |
| `KismetRenderingLibrary:ExportRenderTarget` | returns true, **writes no file** |
| `M_DecalBounds_Test` MID search | 10,401 MIDs, **0** parented to it |
| Menu clicks (SetCursorPos / SendInput abs+rel / PostMessage) | game ignores all; keys work |
| `W_Button_C.OnClicked:Broadcast()` on `WidgetTree.Drive` | fires, game never reacts |
| `ForEachProperty` / `ForEachFunction` / `GetSuperStruct` | freeze the game thread |

Root cause for the first three: UE4SS silently drops a nested `TArray<FStruct>` inside a
struct. Flat struct writes work (`SetControlRotation` round-trips exactly), so this is
specific to nested arrays, not to structs in general.

## State of the world (observed, not inferred)

- 517 `MTVehicle` actors in `Jeju_World`; **all 517** have a `DecalComponent`.
- 516 of those have a **null** `DecalContainer` (the wrapper is truthy in Lua — check `IsValid()`).
- Exactly 1 valid container exists, on `EnfoGT_C_2147455502`, and its `Layers` array is
  inaccessible/empty.
- => no vehicle in a console-loaded world carries decals, and none can be given one from Lua.
