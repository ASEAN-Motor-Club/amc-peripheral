# Decal Transform Recovery Plan

> **For Hermes:** Execute the offline extraction and analysis tasks first. Do not implement viewer placement from a guessed model.

**Goal:** Recover the exact Motor Town decal projection equations and constants, then implement them in the viewer with numeric validation.

**Architecture:** Extract the three compiled shaders belonging to `M_DecalBounds_Test` from the existing shader archive, decompress them, disassemble/decompile them, and map their constant-buffer slots back to the material parameters. Use native code and live objects only to answer questions the shader cannot answer. Implement the viewer only after the equations are written down.

**Tech Stack:** Python 3, the client's Oodle library, `d3dasm`/vkd3d, CUE4Parse/UAssetTool, Ghidra only if needed, three.js/GLSL for the final viewer implementation.

---

## 1. Review of the previous plan

The previous plan had five material errors:

1. **The DXBC diagnosis was wrong.** The shader archive's code region is compressed. Readable `DXBC`, `ISGN`, `OSGN`, and `SHEX` strings mixed with invalid numeric fields were compressed-stream literals, not a non-standard UE container. UE shader archives normally compress shader code, and existing tooling handles both the archive and decompression.[3][5][6]
2. **Path C was incorrectly deferred.** The archive format is documented and CUE4Parse publishes the exact structures: 16-byte `FShaderMapEntry`, 17-byte `FShaderCodeEntry`, preload entries, then shader indices.[4] There is no remaining archive-format research project.
3. **The live-capture trigger was insufficient.** The plugin documentation says a layer is opened for editing and `F` finishes/bakes it. Opening only the vehicle editor does not guarantee an active `BoundsActor` or editable layer.[2]
4. **The proposed MID sweep had the causality backwards.** `DynamicBrushMaterial` parameters are downstream outputs. Changing `PositionX` on the MID would not prove how source layer data moves `BoundsActor`; it might only alter a preview or be overwritten on the next update.
5. **The viewer work repeated the rejected approach.** Implementing another parameterized guess before recovering the equations would create another unfalsifiable renderer. Constants and projection code must come after the recovered specification, not before.

The acceptance criteria were also too weak: “all 1171 production layers reproduce” is not measurable without game ground truth. Production data can check invariants and coverage; accuracy requires live or rendered reference measurements.

## 2. New evidence that changes the route

The official plugin documentation confirms a UV-independent projection that is baked into mesh UV render targets, with active layer editing and explicit bake/finish behaviour.[1][2]

Using the documented `FSerializedShaderArchive` layout against the already extracted archive gives:

- Archive version: **2**.
- Shader maps: **678**; unique shaders: **14,486**.
- `M_DecalBounds_Test` map: **index 266**.
- Map entry 266: `ShaderIndicesOffset=7060`, `NumShaders=3`, `FirstPreloadIndex=1636`, `NumPreloadEntries=1`.
- Referenced shader indices: **5019, 5020, 5021**.
- Compressed/uncompressed sizes:
  - 5019: **4119 / 14442** bytes.
  - 5020: **2775 / 8273** bytes.
  - 5021: **4120 / 11951** bytes.
- Shader code base: **734,498**.
- The final shader entry ends exactly at archive EOF: **56,636,716**. This independently validates the directory parse.
- The three blobs begin with `8C 0A`, the Oodle family signature; direct LZ4 decompression of shader 5021 fails. Decompression must try Oodle first, matching the existing extractor's behaviour.[5][6]

This reduces the shader problem from “identify one shader among 14,449 compressed streams” to “decompress and disassemble three known shaders.”

## 3. Execution tasks

### Phase A — extract and read the three shaders (primary, autonomous)

#### Task A1: Write a standalone archive extractor

**Files:**
- Create: `tools/extract_decal_shaders.py`
- Test: `tools/tests/test_extract_decal_shaders.py`
- Input: `build/shader_archive_sm5.bin`
- Output: `build/decal_shaders/manifest.json` and three compressed blobs.

**Implementation requirements:**
- Parse the archive using the published structures, not magic scanning:[4]
  - `uint32 version`
  - `TArray<FSHAHash> ShaderMapHashes` (20-byte hashes here)
  - `TArray<FSHAHash> ShaderHashes`
  - `TArray<FShaderMapEntry>` (`uint32 ShaderIndicesOffset, NumShaders, FirstPreloadIndex, NumPreloadEntries`)
  - `TArray<FShaderCodeEntry>` (`uint64 Offset; uint32 Size, UncompressedSize; uint8 Frequency`)
  - `TArray<FFileCachePreloadEntry>` (`int64 Offset, Size`)
  - `TArray<uint32> ShaderIndices`
  - compressed shader bytes
- Locate the material by the 20-byte hash found in `M_DecalBounds_Test.uexp`; assert it is map 266.
- Resolve map 266 through `ShaderIndices`; assert the result is exactly `[5019, 5020, 5021]`.
- Assert the final referenced byte range ends at EOF and every range is inside the file.
- Record hashes, indices, offsets, compressed sizes, and uncompressed sizes in `manifest.json`.

**Tests:**
- A synthetic archive fixture verifies all array walks, deduplicated shader indices, truncation rejection, and EOF accounting.
- A real-archive smoke test asserts the values listed in §2.
- Expected result: three blobs written; no `DXBC` magic required in compressed data.

#### Task A2: Decompress with the game's Oodle library

**Files:**
- Create: `tools/decompress_shader_oodle.ps1` or a small C++ helper based on `decompress_shader.cpp`.[6]
- Output: `build/decal_shaders/5019.dxbc`, `5020.dxbc`, `5021.dxbc`.

**Implementation requirements:**
- Run on the Windows desktop so the client's own `oo2core_*_win64.dll` can be loaded; do not download a replacement DLL.
- Try Oodle first for the `8C 0A` streams. LZ4 remains a fallback for other archives, not the expected path here.[3][6]
- Allocate the exact `UncompressedSize` from the manifest and verify the decompressor's returned length.
- Locate the `DXBC` container inside each decompressed shader payload; validate version `1`, the container's total-size field, chunk count, and bounds before writing the `.dxbc` file.

**Verification:**
- Decompressed lengths are exactly **14442**, **8273**, and **11951** bytes.
- Each extracted DXBC passes `vkd3d-compiler` or `d3dasm` parsing without checksum rewriting or container reconstruction.
- If this fails, stop and inspect the decompression call; do not return to byte carving.

#### Task A3: Disassemble and decompile all three shaders

**Files:**
- Output: `build/decal_shaders/*.asm` and `build/decal_shaders/*.hlsl`.
- Tooling: `d3dasm` first; vkd3d `d3d-asm` as an independent cross-check. `HLSLDecompiler` is an optional second decompiler.[7][8]

**Steps:**
- Disassemble all three, not a filtered subset.
- Identify shader stage from the program token and record resource bindings and the material constant-buffer accesses.
- Cross-check the pixel shader's arithmetic between disassembly and decompilation; where they disagree, the disassembly wins.
- Save tool versions and commands in `build/decal_shaders/README.md`.

**Exit criterion:** the pixel shader's arithmetic is readable and the constant-buffer slots used for position, rotation, scale/stretch, local bounds/normals, culling, and channel selection are enumerated.

### Phase B — recover the equations and upstream meaning

#### Task B1: Map material parameters to constant-buffer slots

**Files:**
- Modify if needed: `tools/mtglb/Program.cs`
- Input: `M_DecalBounds_Test.uasset/.uexp`
- Output: `build/decal_shaders/material-preshader.json`, `build/decal_shaders/parameter-map.json`.

**Steps:**
- Export the material resource/preshader data and its parameter metadata. Reuse the UE5.5 preshader-to-uniform-buffer logic from UEShaderMapExtractor rather than guessing packed float positions.[5]
- Join `PositionX`, `PositionY`, `PitchDown`, `Yaw`, `Roll`, `Stretch`, `Coverage`, `DecalScale`, `DecalUVChannel`, `LocalBounds`, `LocalNormal`, and the layer flags to the constant-buffer offsets observed in Phase A.
- Mark each parameter as `mapped`, `unused`, or `unresolved`; do not silently drop unresolved fields.

**Fallback:** if preshader export is blocked, infer slot identity only from a live MID differential capture, not from parameter order.

#### Task B2: Write the exact projection specification

**File:** `.hermes/plans/decal-uv-mechanism.md`

Transcribe, in order:

1. Construction of the local position/normal inputs from the bounds and normal captures.
2. Position offset and sign conventions.
3. Projection-axis/channel selection.
4. Quaternion/rotator construction and rotation order.
5. `DecalScale`, `Stretch`, `TextureScale`, and `Coverage` operations, including reciprocals and centre pivots.
6. Flip/mirror/backface/opposite-cull behaviour and UV clipping.
7. Final texture-sample coordinates and render-target blend semantics.

Every equation must cite the shader file and instruction range it came from. Unknown upstream conversions must be listed separately rather than filled with plausible constants.

#### Task B3: Resolve only the remaining upstream unknowns

Use the cheapest route that answers the actual unknown:

- **Static native code:** targeted Ghidra analysis of the per-layer MID-building function and its `SetScalarParameterValue` callers. This is for source-data → MID conversion only, not another broad binary search.
- **Live passive capture:** with a layer actively open for editing, dump the source layer values, `BoundsActor` transform, MID values, and mesh bounds in the same snapshot.[2]
- **Controlled differential capture:** change the *source* layer value through the real editor or a native mod, then capture both source and outputs. Never use a MID-only write as evidence of the upstream transform.

Exit when every field needed by the viewer is either recovered or explicitly proven unused.

### Phase C — verify, then implement the viewer

#### Task C1: Build a CPU reference implementation and tests

**Files:**
- Create: `site/js/decal-projection.js`
- Create: `site/js/decal-projection.test.js`
- Create: `site/js/decal-constants.js` only for recovered constants, with source references.

**Tests:**
- Synthetic position/normal/UV cases derived from the decompiled shader, including zero rotation, ±90°, ±180°, minimum/maximum scale, stretch, channel changes, flip/mirror, and culling.
- Compare CPU results against independently evaluated HLSL expressions to floating-point tolerance.
- Test the production dataset for coverage and exceptions, but label this a sanity test—not proof of visual accuracy.

#### Task C2: Implement the three.js projection from the same specification

**Files:**
- Modify: `site/index.html` only if the current single-file structure is retained.
- Otherwise create focused shader/projection modules and import them from `site/index.html`.

Requirements:
- One implementation of the recovered transform; no vehicle-specific exceptions and no alternate “candidate” modes.
- A `?dcheck=1` diagnostic that exposes calculated box/transform values and wireframes for debugging, not for acceptance.
- Preserve the `?v=` cache-busting rule when deployed assets change.

#### Task C3: Numeric acceptance against the game

For at least five live layers spanning the real ranges:

- Capture source values, mesh bounds, MID outputs, and `BoundsActor` transform while the layer is active.
- Compare predicted transform/projection values against the captured values within floating-point tolerance.
- If rendered-footprint validation is required, use a native `ReadPixels` capture or a controlled screenshot with programmatic pixel measurement. Do not use visual model judgement as the measurement.
- Target footprint error: **≤2% of the mesh bounding-box diagonal**, with any larger residual treated as an unresolved equation error.

If no live session is available, report “offline equations recovered, live accuracy unverified”; do not claim the acceptance test passed.

## 4. Order and stop conditions

1. **Phase A** — fully autonomous and now bounded to three known shaders.
2. **Phase B1/B2** — recover and document the math.
3. **Phase B3** — only for explicitly listed unknowns.
4. **Phase C** — implementation starts only after the specification is complete.
5. Ghidra and native-mod work are fallbacks for named unknowns, not default next steps.

Stop conditions:
- If Oodle decompression fails, diagnose the decompressor call; do not resume raw DXBC carving.
- If the three shaders do not contain the expected projection inputs, revalidate the material→map hash link before expanding the search.
- If only upstream semantics remain, write the exact unknown list before opening Ghidra or requesting a live session.

## 5. Definition of done

- Three shaders extracted with byte counts and valid DXBC containers.
- Disassembly/decompilation archived with tool versions.
- Parameter-to-cbuffer map and exact projection equations documented with instruction references.
- No unresolved field silently approximated.
- Viewer tests implement the documented equations without per-vehicle fudge.
- Numeric game validation passes, or its absence is reported explicitly.

## Sources

[1] https://www.unrealengine.com/marketplace/en-US/product/advanced-decal-component — Advanced Decal Component — official marketplace listing
[2] https://drive.google.com/file/d/1855cxL39eJsqyp5Kvz6gjPCgeo8k52XV/view?usp=sharing — Advanced Decal Component V3 documentation
[3] https://en.imzlp.com/posts/26943 — UE shader archive format and compression
[4] https://github.com/FabianFG/CUE4Parse/blob/master/CUE4Parse/UE4/Shaders/FSerializedShaderArchive.cs — CUE4Parse FSerializedShaderArchive layout
[5] https://github.com/wistfulhopes/ueshadermapextractor — UEShaderMapExtractor
[6] https://github.com/wistfulhopes/ueshadermapextractor/blob/main/decompress_shader.cpp — UEShaderMapExtractor shader decompression
[7] https://github.com/coconutbird/d3dasm — d3dasm DXBC disassembler and HLSL decompiler
[8] https://github.com/Quon/HLSLDecompiler — HLSLDecompiler
