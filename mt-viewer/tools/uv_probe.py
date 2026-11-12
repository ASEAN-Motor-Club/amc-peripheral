#!/usr/bin/env python3
"""Probe the spare UV channels of a vehicle's body mesh.

The decal positions in CharacterVehicle.config are implausible as world coordinates
(Vamos3 reaches X=-601 on a 4.05 m body), and every body GLB carries TEXCOORD_0..7,
so the likely story is that decals are baked into the render target through a
dedicated UV channel. This prints each channel's actual range so the mapping can be
solved instead of guessed.

usage: uv_probe.py site/<slug>/glb/<Mesh>.glb
"""
import json
import struct
import sys

CT = {5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2), 5123: ("H", 2),
      5125: ("I", 4), 5126: ("f", 4)}
NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}


def load_glb(path):
    d = open(path, "rb").read()
    jlen = struct.unpack("<I", d[12:16])[0]
    j = json.loads(d[20:20 + jlen])
    off = 20 + jlen
    blen = struct.unpack("<I", d[off:off + 4])[0]
    bin_ = d[off + 8:off + 8 + blen]
    return j, bin_


def accessor_range(j, bin_, idx):
    a = j["accessors"][idx]
    bv = j["bufferViews"][a["bufferView"]]
    fmt, size = CT[a["componentType"]]
    n = NCOMP[a["type"]]
    stride = bv.get("byteStride") or size * n
    base = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    lo = [float("inf")] * n
    hi = [float("-inf")] * n
    for i in range(a["count"]):
        o = base + i * stride
        vs = struct.unpack_from("<" + fmt * n, bin_, o)
        for k, v in enumerate(vs):
            if v < lo[k]:
                lo[k] = v
            if v > hi[k]:
                hi[k] = v
    return lo, hi


def main(path):
    j, bin_ = load_glb(path)
    for m in j.get("meshes", []):
        for pr in m["primitives"]:
            attrs = pr["attributes"]
            chans = sorted(k for k in attrs if k.startswith("TEXCOORD_"))
            if not chans:
                continue
            cnt = j["accessors"][attrs["POSITION"]]["count"]
            print(f"{m.get('name')} ({cnt} verts)")
            for c in chans:
                lo, hi = accessor_range(j, bin_, attrs[c])
                print(f"  {c}: u[{lo[0]:.3f},{hi[0]:.3f}] v[{lo[1]:.3f},{hi[1]:.3f}]")


if __name__ == "__main__":
    main(sys.argv[1])
