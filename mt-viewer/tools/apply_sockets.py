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
    """UE FRotator (degrees) -> (x, y, z, w) quaternion in UE space.

    This is UE's own FRotator::Quaternion order (roll, then pitch about Y, then yaw).
    An earlier variant put the pitch term on X, which produced a mirrored tilt -- the
    wheel reclined away from the driver instead of toward them.
    """
    p, y, r = (math.radians(v) / 2.0 for v in (pitch, yaw, roll))
    sp, cp = math.sin(p), math.cos(p)
    sy, cy = math.sin(y), math.cos(y)
    sr, cr = math.sin(r), math.cos(r)
    return (
        cr * sp * sy - sr * cp * cy,
        -cr * sp * cy - sr * cp * sy,
        cr * cp * sy - sr * sp * cy,
        cr * cp * cy + sr * sp * sy,
    )


def ue_to_gltf_quat(q):
    """UE axes -> glTF axes, using the same conjugation the part transforms use."""
    try:
        from mk_manifest import ue_to_gltf_quat as convert
    except ModuleNotFoundError:  # also allow `python -m unittest` from the repo root
        from tools.mk_manifest import ue_to_gltf_quat as convert
    return convert(q)


def main():
    if len(sys.argv) < 3:
        print("usage: apply_sockets.py <manifest.json> <build-dir>", file=sys.stderr)
        return 2
    manifest_path, glb_dir = sys.argv[1], sys.argv[2]
    with open(manifest_path) as f:
        manifest = json.load(f)

    # every socket discovered across this vehicle's meshes, keyed by socket name
    sockets = {}
    for path in glob.glob(os.path.join(glb_dir, "**", "*.sockets.json"), recursive=True):
        with open(path) as f:
            socket_data = json.load(f)
        for s in socket_data:
            sockets.setdefault(s["name"], s)

    moved = []
    dropped = []
    kept_parts = []
    for part in manifest.get("parts", []):
        key = part.get("id") or part.get("mesh")
        sock = sockets.get(key)
        at_origin = all(abs(v) < 1e-6 for v in part.get("position", [0, 0, 0]))
        already_mounted = str(part.get("mountedOn") or "").startswith("socket:")
        if key == "SteeringWheel" and not at_origin:
            part.pop("hidden", None)  # a later blueprint supplied an explicit mount
        if key == "SteeringWheel" and at_origin and not sock and not already_mounted:
            # MTVehicleBaseBP supplies this component to every vehicle. Without the
            # body socket there is no valid mount point (trailers), so hide it rather
            # than staging it at the origin. Keep the part so a later socket export
            # can recover the real mount without regenerating the whole manifest.
            part["hidden"] = True
            dropped.append(key)
            kept_parts.append(part)
            continue
        if not sock:
            kept_parts.append(part)
            continue
        if key == "SteeringWheel":
            part.pop("hidden", None)
        if not (at_origin or already_mounted):
            kept_parts.append(part)
            continue  # the blueprint places it itself; trust that
        lx, ly, lz = sock["loc"]
        part["position"] = [round(lx / 100.0, 5), round(lz / 100.0, 5), round(-ly / 100.0, 5)]
        rx, ry, rz, rw = ue_to_gltf_quat(rotator_quat(*sock["rot"]))
        part["rotation"] = [round(rx, 6), round(ry, 6), round(rz, 6), round(rw, 6)]
        part["mountedOn"] = "socket:" + key
        moved.append(key)
        kept_parts.append(part)
    manifest["parts"] = kept_parts

    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=1)
    if moved:
        print("  socket-mounted: " + ", ".join(sorted(set(moved))))
    if dropped:
        print("  no socket, hidden: " + ", ".join(sorted(set(dropped))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
