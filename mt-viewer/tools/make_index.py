#!/usr/bin/env python3
"""make_index.py — build site/vehicles.json (the viewer's vehicle picker).

Scans site/<slug>/<slug>.json + materials.json and writes a small catalogue:
[{slug, vehicle, parts, inheritedFrom, materials, textured}]
"""
import json
import os
import sys


def main(site_dir):
    out = []
    for slug in sorted(os.listdir(site_dir)):
        d = os.path.join(site_dir, slug)
        man = os.path.join(d, slug + ".json")
        if not os.path.isdir(d) or not os.path.exists(man):
            continue
        try:
            m = json.load(open(man))
        except Exception:
            continue
        mats = {}
        mp = os.path.join(d, "materials.json")
        if os.path.exists(mp):
            mats = json.load(open(mp)).get("materials", {})
        out.append({
            "slug": slug,
            "vehicle": m.get("vehicle", slug),
            "parts": len(m.get("parts", [])),
            "inheritedFrom": m.get("inheritedFrom"),
            "materials": len(mats),
            "textured": sum(1 for v in mats.values() if v.get("map")),
        })
    dest = os.path.join(site_dir, "vehicles.json")
    json.dump(out, open(dest, "w"), indent=1)
    print(f"{dest}: {len(out)} vehicles")
    for v in out:
        print(f"  {v['slug']:14s} parts={v['parts']:3d} mats={v['materials']:3d} "
              f"textured={v['textured']:2d} inherited={v['inheritedFrom']}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "site")
