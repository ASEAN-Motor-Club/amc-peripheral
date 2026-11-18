# Workshop vehicle wireframe placeholders

Each workshop vehicle key gets a 960×540 wireframe image rendered from the
**real viewer**, so parts, pivots and sockets are assembled exactly as the 3D
viewer assembles them.

## Pipeline

1. `build_manifest.py` resolves every distinct workshop vehicle key to a viewer
   directory slug. It fails rather than guessing when a key is unresolved or
   two keys collide.
2. `capture_placeholders.py` runs on the Windows render host, loads
   `AMC_WORKSHOP_VIEWER_URL`, waits for `window.__syncFrame.rendered`, swaps the
   assembled meshes to one wireframe material, renders on black and screenshots
   the canvas.
3. `compose_placeholders.py` screen-blends the black-background line art onto
   the shared workshop background and writes WebP.

The app maps keys to files through `amc_peripheral/workshop/placeholder_vehicles.json`
and the `vehicle_placeholder` Jinja filter.

## Inputs

- `vehicles.json` from the deployed viewer catalogue
- a JSON list of distinct `vehicle_key` values from the workshop DB
- `AMC_WORKSHOP_VIEWER_URL` (private origin:
  `http://100.126.244.10:7004/vehicles/index.html`)

## Commands

```bash
python3 scripts/placeholder_wireframes/build_manifest.py \
  --vehicles-json /path/to/vehicles.json \
  --keys-json /path/to/workshop_keys.json \
  --out amc_peripheral/workshop/placeholder_vehicles.json
```

On the Windows host:

```powershell
C:\Users\freeman\AppData\Local\Programs\Python\Python310\python.exe `
  D:\amc-placeholders\capture_placeholders.py `
  --manifest D:\amc-placeholders\placeholder_vehicles.json `
  --out D:\amc-placeholders\raw `
  --slugs boxy,atlas_8x4_dump,conter_lead_20ft --force
```

Then pull the raw PNGs and composite:

```bash
python3 scripts/placeholder_wireframes/compose_placeholders.py \
  --raw /path/to/raw --out amc_peripheral/workshop/static/placeholders
```

Use the same pinned viewer origin and camera (`iso`, the viewer default) for
every batch. Do not use `preview.glb`: it is only the viewer's loading
silhouette and is removed once the full parts arrive.
