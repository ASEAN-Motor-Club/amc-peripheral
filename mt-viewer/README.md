# Motor Town Vehicle 3D Viewer

Interactive three.js viewer for Motor Town vehicles, served as a static site.

## Contents

- `index.html` — the viewer (three.js + OrbitControls + GLTFLoader loaded from CDN)
- `boxy.json` — reassembly manifest for the Boxy: part → GLB mesh, position, scale
- `glb/*.glb` — exported part meshes (Body, wheels, mirrors, doors, steering)
- `preview.png` — rendered proof image of the assembled vehicle

## Reassembly model

Vehicle parts (body, doors, hood, wheels, mirrors) are stored as separate
meshes in the game PAK. `boxy.json` maps each part to a GLB plus the relative
transform (position in **UE cm**, scale) read from the vehicle blueprint, so
the exact same rest position occurs on the frontend.

**Units:** blueprint positions are UE/unreal centimetres; the exported GLB
geometry is in metres — the viewer divides positions by 100 to reassemble at
the correct scale. See the `motortown-vehicle-gltf-extract` skill for how the
GLBs are produced (CUE4Parse, `usmap` v4, .NET 10).

## Build

Plain static site — no build step. Nix copies the assets to `$out`:

```bash
nix build .#mtViewer.package   # or via the flake's default package option
```

Served by nginx at `vehicles.<domain>` with a stable symlink at
`/var/www/nix-static/mt-viewer` (see `flake.nix`).

## Status / known limitations

- **Proof of concept** — single vehicle (Boxy), not yet the full catalogue.
- GLB meshes are exported with **no materials** (`ExportMaterials=false`);
  the viewer force-applies a flat grey material. Texture baking is the
  remaining blocker (SkiaSharp native lib missing on the NixOS host).
- Scale-up to all 168 vehicles is future work.