#!/usr/bin/env python3
"""fit_wheels.py — centre each wheel on its hub instead of hanging it off the pivot.

The wheel meshes are authored with their origin at the inner sidewall, not at the
middle of the tyre: Stinger_FR spans z -0.379..+0.064 around its own origin. Applied
as-is the whole tyre sits outboard of the hub, which reads as a track far wider than
the body and tyres jammed against the fender lips.

Blueprint RelativeLocation is the hub position, so shifting each wheel by the lateral
centre of its own mesh puts the tyre where the game shows it: the outer sidewall
lands on the body's widest point rather than beyond it.

usage: fit_wheels.py <manifest.json> <glb-dir>
"""
import json
import os
import struct
import sys


def pos_bbox(path):
    """Lateral/vertical extents from the GLB's POSITION accessors."""
    d = open(path, "rb").read()
    ln = struct.unpack("<I", d[12:16])[0]
    j = json.loads(d[20:20 + ln])
    mn = [1e9] * 3
    mx = [-1e9] * 3
    for mesh in j.get("meshes", []):
        for pr in mesh["primitives"]:
            a = j["accessors"][pr["attributes"]["POSITION"]]
            for i in range(3):
                mn[i] = min(mn[i], a["min"][i])
                mx[i] = max(mx[i], a["max"][i])
    return mn, mx


def main():
    if len(sys.argv) < 3:
        print("usage: fit_wheels.py <manifest.json> <glb-dir>", file=sys.stderr)
        return 2
    manifest_path, glb_dir = sys.argv[1], sys.argv[2]
    manifest = json.load(open(manifest_path))
    moved = []
    for part in manifest.get("parts", []):
        if "Wheel" not in str(part.get("class", "")):
            continue
        if part.get("hubCentred"):
            continue  # already shifted on an earlier pass
        glb = os.path.join(glb_dir, part.get("glb") or (part["mesh"] + ".glb"))
        if not os.path.exists(glb):
            continue
        mn, mx = pos_bbox(glb)
        s = part.get("scale") or [1, 1, 1]
        centre_z = (mn[2] + mx[2]) / 2.0 * s[2]
        if abs(centre_z) < 1e-6:
            continue
        part["position"][2] = round(part["position"][2] - centre_z, 5)
        part["hubCentred"] = True
        moved.append(part.get("id"))
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=1)
    if moved:
        print("  hub-centred wheels: " + ", ".join(str(m) for m in moved))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
