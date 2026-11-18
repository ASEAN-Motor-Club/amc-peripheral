#!/usr/bin/env python3
"""Export the KoreanArt DID decal variants (not listed in the base Decals table).

The workshop can reference KoreanArt_01_<kind>_DID_<id> keys, but Decals.uasset only
lists the unnumbered rows, so these textures were never exported to the viewer. The
uassets are already in the game extraction; this writes their PNGs and appends the
matching catalogue rows.
"""
import json, os, subprocess, sys

WT = "/opt/data/workspace/amc-server/mt-pak-extract-wt-0719"
TOOL = os.path.join(WT, "tools/ue4-dds-tools/src/main.py")
SITE = "/opt/data/workspace/mt-viewer/site/decals"
OUT = os.path.join(SITE, "tex")
TMP = "/opt/data/cache/scratch/decalexp-variants"
CATEGORY = "KoreanArt_01"

catalog_path = os.path.join(SITE, "decals.json")
catalog = json.load(open(catalog_path))
known = {d["key"] for d in catalog["decals"]}
os.makedirs(OUT, exist_ok=True)
os.makedirs(TMP, exist_ok=True)

variant_uassets = sorted(
    f for f in os.listdir(os.path.join(WT, "out"))
    if f.endswith(".uasset") and "_DID_" in f
)
ok = fail = added = 0
for filename in variant_uassets:
    name = filename[:-len(".uasset")]
    src = os.path.join(WT, "out", filename)
    dest_dir = os.path.join(OUT, CATEGORY)
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, name + ".png")
    if not os.path.exists(dest):
        r = subprocess.run(
            [sys.executable, TOOL, src, "--mode", "export", "--version", "5.5",
             "--export_as", "png", "--save_folder", TMP],
            capture_output=True, text=True, timeout=180)
        produced = os.path.join(TMP, name + ".png")
        if os.path.exists(produced):
            os.replace(produced, dest)
        else:
            fail += 1
            print("FAIL", name, (r.stdout or "")[-120:], (r.stderr or "")[-160:])
            continue
    ok += 1
    key = f"{CATEGORY}_{name}"
    if key not in known:
        catalog["decals"].append({
            "key": key,
            "category": CATEGORY,
            "name": name,
            "texture": f"Materials/Decal/DecalTextures/{CATEGORY}/{name}",
            "cost": 100,
            "flags": 0,
        })
        known.add(key)
        added += 1

catalog["decals"].sort(key=lambda d: d["key"])
with open(catalog_path, "w") as fh:
    json.dump(catalog, fh, indent=0)
    fh.write("\n")
print(f"DID decal variants: exported={ok} fail={fail} catalog_added={added}")
