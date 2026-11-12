#!/usr/bin/env python3
"""apply_sockets.py — mount parts that the game places on a mesh socket.

Some parts carry no transform in the blueprint: the steering wheel's component sits
at the origin and the game puts it on the body mesh's `SteeringWheel` socket at
runtime (MTVehicle::bUseSteeringWheelSocketAsPivot). Staged as-is it lands at the
centre of the car, on the floor.

The extractor writes `<Mesh>.sockets.json` next to each GLB; this step snaps a part
onto the socket that shares its name when the blueprint gave no offset of its own.

usage: apply_sockets.py <manifest.json> <build-dir>
"""
import glob
import json
import math
import os
import sys


def rotator_quat(pitch, yaw, roll):
    """UE FRotator (degrees) -> (x, y, z, w) quaternion in UE space."""
    p, y, r = (math.radians(v) / 2.0 for v in (pitch, yaw, roll))
    sp, cp = math.sin(p), math.cos(p)
    sy, cy = math.sin(y), math.cos(y)
    sr, cr = math.sin(r), math.cos(r)
    return (
        sr * cp * cy - cr * sp * sy,
        cr * sp * cy + sr * cp * sy,
        cr * cp * sy - sr * sp * cy,
        cr * cp * cy + sr * sp * sy,
    )


def ue_to_gltf_quat(q):
    """UE axes -> glTF axes, using the same conjugation the part transforms use."""
    from mk_manifest import ue_to_gltf_quat as convert
    return convert(q)


def main():
    if len(sys.argv) < 3:
        print("usage: apply_sockets.py <manifest.json> <build-dir>", file=sys.stderr)
        return 2
    manifest_path, glb_dir = sys.argv[1], sys.argv[2]
    manifest = json.load(open(manifest_path))

    # every socket discovered across this vehicle's meshes, keyed by socket name
    sockets = {}
    for path in glob.glob(os.path.join(glb_dir, "**", "*.sockets.json"), recursive=True):
        for s in json.load(open(path)):
            sockets.setdefault(s["name"], s)

    moved = []
    for part in manifest.get("parts", []):
        key = part.get("id") or part.get("mesh")
        sock = sockets.get(key)
        if not sock:
            continue
        at_origin = all(abs(v) < 1e-6 for v in part.get("position", [0, 0, 0]))
        if not at_origin:
            continue  # the blueprint already places it; trust that
        lx, ly, lz = sock["loc"]
        part["position"] = [round(lx / 100.0, 5), round(lz / 100.0, 5), round(-ly / 100.0, 5)]
        rx, ry, rz, rw = ue_to_gltf_quat(rotator_quat(*sock["rot"]))
        part["rotation"] = [round(rx, 6), round(ry, 6), round(rz, 6), round(rw, 6)]
        part["mountedOn"] = "socket:" + key
        moved.append(key)

    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=1)
    if moved:
        print("  socket-mounted: " + ", ".join(sorted(set(moved))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
