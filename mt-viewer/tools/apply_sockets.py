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


def q_mul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    )


def q_rotate(q, v):
    x, y, z, w = q
    vx, vy, vz = v
    return (
        (1 - 2 * (y * y + z * z)) * vx + 2 * (x * y - z * w) * vy + 2 * (x * z + y * w) * vz,
        2 * (x * y + z * w) * vx + (1 - 2 * (x * x + z * z)) * vy + 2 * (y * z - x * w) * vz,
        2 * (x * z - y * w) * vx + 2 * (y * z + x * w) * vy + (1 - 2 * (x * x + y * y)) * vz,
    )


def socket_transform(sock):
    lx, ly, lz = sock["loc"]
    position = [lx / 100.0, lz / 100.0, -ly / 100.0]
    rotation = ue_to_gltf_quat(rotator_quat(*sock["rot"]))
    sx, sy, sz = sock.get("scale") or [1, 1, 1]
    return position, rotation, [sx, sz, sy]


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
        if key == "SteeringWheel" and part.get("mesh") == "Handlebar":
            # Zero's motorcycle handlebar is authored in vehicle space and has no
            # SCS AttachToName. The generic steering-socket fallback moved it twice.
            part["position"] = [0, 0, 0]
            part["rotation"] = [0, 0, 0, 1]
            part["scale"] = [1, 1, 1]
            part.pop("mountedOn", None)
            part.pop("socketLocal", None)
            part.pop("hidden", None)
            kept_parts.append(part)
            continue
        explicit_socket = part.get("attachSocket")
        slot = part.get("partSlot")
        native_dashboard_socket = (
            part.get("class") == "MTDashboard" and not explicit_socket
            and "SteeringWheel" in sockets
        )
        socket_name = explicit_socket or ("SteeringWheel" if native_dashboard_socket else (slot if slot in sockets else key))
        sock = sockets.get(socket_name)
        at_origin = all(abs(v) < 1e-6 for v in part.get("position", [0, 0, 0]))
        already_mounted = str(part.get("mountedOn") or "") == "socket:" + str(socket_name)
        if key == "SteeringWheel" and not at_origin:
            part.pop("hidden", None)
        if key == "SteeringWheel" and at_origin and not sock and not already_mounted:
            part["hidden"] = True
            dropped.append(key)
            kept_parts.append(part)
            continue
        if not sock:
            kept_parts.append(part)
            continue
        if key == "SteeringWheel":
            part.pop("hidden", None)
        # An SCS AttachToName is authoritative. Other origin-pivot parts may use
        # their namesake socket; meshSpace=vehicle prevents a second transform.
        if (key == "SteeringWheel" and part.get("meshSpace") == "vehicle"
                and not explicit_socket and not already_mounted):
            # This mesh's exported root already contains its vehicle-space cabin
            # transform; applying the steering socket would place it twice.
            kept_parts.append(part)
            continue
        steering_local_offset = key == "SteeringWheel" and all(
            abs(v) <= 0.1 for v in part.get("position", [0, 0, 0])
        )
        if not explicit_socket and not (at_origin or steering_local_offset or already_mounted or native_dashboard_socket):
            kept_parts.append(part)
            continue
        if already_mounted:
            local = part.get("socketLocal") or {
                "position": [0, 0, 0], "rotation": [0, 0, 0, 1], "scale": [1, 1, 1]
            }
        else:
            local = {
                "position": list(part.get("position") or [0, 0, 0]),
                "rotation": list(part.get("rotation") or [0, 0, 0, 1]),
                "scale": list(part.get("scale") or [1, 1, 1]),
            }
        spos, squat, sscale = socket_transform(sock)
        if native_dashboard_socket:
            # A centered dashboard must not inherit the steering wheel's lateral
            # offset. The socket supplies only longitudinal/height alignment.
            spos[2] = 0.0
        lpos = local["position"]
        scaled = [lpos[i] * sscale[i] for i in range(3)]
        rotated = q_rotate(squat, scaled)
        part["position"] = [round(spos[i] + rotated[i], 5) for i in range(3)]
        part["rotation"] = [round(v, 6) for v in q_mul(squat, local["rotation"])]
        part["scale"] = [round(sscale[i] * local["scale"][i], 5) for i in range(3)]
        part["socketLocal"] = local
        part["mountedOn"] = "socket:" + socket_name
        if native_dashboard_socket:
            part["socketLateralCentered"] = True
        else:
            part.pop("socketLateralCentered", None)
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
