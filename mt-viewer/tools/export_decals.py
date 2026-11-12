#!/usr/bin/env python3
"""Export the 412 base-game decal textures to PNG for the viewer."""
import json, os, subprocess, sys

WT = "/opt/data/workspace/amc-server/mt-pak-extract-wt-0719"
TOOL = os.path.join(WT, "tools/ue4-dds-tools/src/main.py")
SITE = "/opt/data/workspace/mt-viewer/site/decals"
OUT = os.path.join(SITE, "tex")
TMP = "/opt/data/cache/scratch/decalexp"

decals = json.load(open(os.path.join(SITE, "decals.json")))["decals"]
os.makedirs(OUT, exist_ok=True)
os.makedirs(TMP, exist_ok=True)

ok = fail = 0
missing = []
for d in decals:
    name = d["name"]
    src = os.path.join(WT, "out", name + ".uasset")
    if not os.path.exists(src):
        missing.append(name); fail += 1; continue
    dest_dir = os.path.join(OUT, d["category"])
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, name + ".png")
    if os.path.exists(dest):
        ok += 1; continue
    r = subprocess.run([sys.executable, TOOL, src, "--mode", "export", "--version", "5.5",
                        "--export_as", "png", "--save_folder", TMP],
                       capture_output=True, text=True, timeout=120)
    if os.path.exists(os.path.join(TMP, name + ".png")):
        os.replace(os.path.join(TMP, name + ".png"), dest)
        ok += 1
    else:
        fail += 1
        if fail < 5:
            print("FAIL", name, (r.stdout or "")[-120:], (r.stderr or "")[-160:])
print(f"decal textures: ok={ok} fail={fail}")
if missing:
    print("missing from out/:", missing[:10], f"({len(missing)})")
