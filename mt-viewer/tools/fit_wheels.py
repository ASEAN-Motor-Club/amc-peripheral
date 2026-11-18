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


def _matrix(node):
    """Column-major 4x4 for a glTF node's local transform."""
    if "matrix" in node:
        m = node["matrix"]
        return [[m[c * 4 + r] for c in range(4)] for r in range(4)]
    tx, ty, tz = node.get("translation", (0, 0, 0))
    qx, qy, qz, qw = node.get("rotation", (0, 0, 0, 1))
    sx, sy, sz = node.get("scale", (1, 1, 1))
    # quaternion -> rotation matrix, then T * R * S
    xx, yy, zz = qx * qx, qy * qy, qz * qz
    xy, xz, yz = qx * qy, qx * qz, qy * qz
    wx, wy, wz = qw * qx, qw * qy, qw * qz
    r = [
        [1 - 2 * (yy + zz), 2 * (xy - wz), 2 * (xz + wy)],
        [2 * (xy + wz), 1 - 2 * (xx + zz), 2 * (yz - wx)],
        [2 * (xz - wy), 2 * (yz + wx), 1 - 2 * (xx + yy)],
    ]
    return [
        [r[0][0] * sx, r[0][1] * sy, r[0][2] * sz, tx],
        [r[1][0] * sx, r[1][1] * sy, r[1][2] * sz, ty],
        [r[2][0] * sx, r[2][1] * sy, r[2][2] * sz, tz],
        [0, 0, 0, 1],
    ]


def _mul(a, b):
    return [[sum(a[r][k] * b[k][c] for k in range(4)) for c in range(4)] for r in range(4)]


def _transform(m, p):
    return [sum(m[r][k] * p[k] for k in range(3)) + m[r][3] for r in range(3)]


def _normalised(v, accessor):
    if not accessor.get("normalized"):
        return float(v)
    return max(float(v) / 32767.0, -1.0) if accessor.get("componentType") == 5122 else float(v)


def scene_bbox(path):
    """World-space bounds, including node translation/scale/rotation.

    ``pos_bbox`` originally read accessor min/max directly. Quantised wheel GLBs
    keep the mesh centred but move it sideways with a node translation; ignoring
    that made a wheel look centred when its rendered tyre was 0.1–0.2 m outboard.
    """
    d = open(path, "rb").read()
    ln = struct.unpack("<I", d[12:16])[0]
    j = json.loads(d[20:20 + ln])
    mn = [1e9] * 3
    mx = [-1e9] * 3
    node_parent = {}
    for i, node in enumerate(j.get("nodes", [])):
        for child in node.get("children", []):
            node_parent[child] = i

    def walk(index, parent):
        node = j["nodes"][index]
        world = _mul(parent, _matrix(node))
        if "mesh" in node:
            for mesh in [j["meshes"][node["mesh"]]]:
                for pr in mesh["primitives"]:
                    accessor = j["accessors"][pr["attributes"]["POSITION"]]
                    a_min, a_max = accessor["min"], accessor["max"]
                    for corner in (
                        (a_min[0], a_min[1], a_min[2]),
                        (a_min[0], a_min[1], a_max[2]),
                        (a_min[0], a_max[1], a_min[2]),
                        (a_min[0], a_max[1], a_max[2]),
                        (a_max[0], a_min[1], a_min[2]),
                        (a_max[0], a_min[1], a_max[2]),
                        (a_max[0], a_max[1], a_min[2]),
                        (a_max[0], a_max[1], a_max[2]),
                    ):
                        p = _transform(world, [
                            _normalised(corner[0], accessor),
                            _normalised(corner[1], accessor),
                            _normalised(corner[2], accessor),
                        ])
                        for k in range(3):
                            mn[k] = min(mn[k], p[k])
                            mx[k] = max(mx[k], p[k])
        for child in node.get("children", []):
            walk(child, world)

    roots = [i for i in range(len(j.get("nodes", []))) if i not in node_parent]
    for root in roots:
        walk(root, [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])
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
        mn, mx = scene_bbox(glb)
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
