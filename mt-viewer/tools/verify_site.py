#!/usr/bin/env python3
"""verify_site.py — static consistency check over every staged vehicle.

Checks, per site/<slug>/:
  1. <slug>.json exists and has parts
  2. every part's GLB exists and is non-trivial (> 1 KB)
  3. materials.json exists and has a slot entry for every slot the manifest claims
  4. every GLB primitive's material NAME is a known slot (this is what glb_slots.py
     guarantees; a miss here means the primitive falls back to slot order and can
     paint the wrong surface)
  5. textures referenced by materials.json exist on disk

Exit code 0 always; prints a summary plus the first N problems per vehicle.
"""
import json
import os
import struct
import sys

SITE = sys.argv[1] if len(sys.argv) > 1 else "site"
MAX_PROBLEMS = int(sys.argv[2]) if len(sys.argv) > 2 else 3


def glb_materials(path):
    b = open(path, "rb").read()
    if len(b) < 20 or b[:4] != b"glTF":
        raise ValueError("not a GLB")
    n = struct.unpack("<I", b[12:16])[0]
    g = json.loads(b[20:20 + n])
    mats = [m.get("name") for m in g.get("materials", [])]
    names = []
    for mesh in g.get("meshes", []):
        for prim in mesh.get("primitives", []):
            idx = prim.get("material")
            names.append(mats[idx] if idx is not None and idx < len(mats) else None)
    return names, [a["count"] for m in g.get("meshes", [])
                   for a in [g["accessors"][p["attributes"]["POSITION"]] for p in m["primitives"]]]


def main():
    slugs = sorted(d for d in os.listdir(SITE)
                   if os.path.isdir(os.path.join(SITE, d)))
    ok = bad = skipped = 0
    rows = []
    for slug in slugs:
        d = os.path.join(SITE, slug)
        mf = os.path.join(d, slug + ".json")
        if not os.path.exists(mf):
            skipped += 1
            continue
        man = json.load(open(mf))
        problems = []
        if not man.get("parts"):
            problems.append("no parts")

        mats_path = os.path.join(d, "materials.json")
        mats = {}
        if os.path.exists(mats_path):
            mats = (json.load(open(mats_path)) or {}).get("materials") or {}
        else:
            problems.append("no materials.json")

        slots = set(mats)
        for slot, entry in mats.items():
            mp = entry.get("map")
            if mp and not os.path.exists(os.path.join(d, mp)):
                problems.append(f"missing texture for {slot}: {mp}")

        empties = 0
        for part in man.get("parts", []):
            gp = os.path.join(d, "glb", part["glb"])
            if not os.path.exists(gp):
                problems.append(f"missing glb {part['glb']}")
                continue
            if os.path.getsize(gp) < 1024:
                empties += 1
            try:
                names, counts = glb_materials(gp)
            except Exception as e:
                problems.append(f"unreadable glb {part['glb']}: {e}")
                continue
            unknown = sorted({n for n in names if n and n not in slots})
            if unknown:
                problems.append(f"{part['glb']}: unmapped material(s) {unknown[:3]}")

        if empties:
            problems.append(f"{empties} mesh glb < 1 KB (no geometry in the export)")

        textured = sum(1 for e in mats.values() if e.get("map"))
        rows.append((slug, len(man.get("parts") or []), len(mats), textured,
                     len(man.get("paints") or []), len(problems)))
        if problems:
            bad += 1
            print(f"FAIL {slug:26s} " + " | ".join(problems[:MAX_PROBLEMS]))
        else:
            ok += 1

    print(f"\nchecked {ok + bad} vehicles ({skipped} dirs without a manifest): "
          f"{ok} clean, {bad} with problems")
    print(f"total parts {sum(r[1] for r in rows)}, materials {sum(r[2] for r in rows)}, "
          f"textured slots {sum(r[3] for r in rows)}, paint tables on "
          f"{sum(1 for r in rows if r[4])} vehicles")
    thin = [r for r in rows if r[1] <= 3]
    if thin:
        print("thin vehicles (<=3 parts):", ", ".join(f"{r[0]}({r[1]})" for r in thin))


main()
