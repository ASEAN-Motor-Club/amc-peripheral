#!/usr/bin/env python3
"""mk_manifest.py — Motor Town vehicle blueprint -> viewer manifest + mesh list.

Reads one `out/<Vehicle>_parsed.json` (UAssetTool batch output) and emits:

  <out>/meshes_<Vehicle>.json   [{"name": "Body", "path": "MotorTown/Content/..."}]
                                unique meshes, de-duplicated by pak path
  <out>/<Vehicle>.json          viewer manifest (v2, world-space transforms)

World transforms are composed by walking the AttachParent chain by ObjectName
(AttachParent.Index is unreliable across vehicles). Positions are converted to
**metres** and rotations to a glTF-space quaternion (UE is Z-up/X-forward; glTF
is Y-up), so the viewer places parts without any further conversion:

    C   = rotation of -90 deg about X   ((x,y,z)_ue -> (x,z,-y))
    p'  = C . p_ue / 100
    q'  = qC * q_ue * qC^-1
    s'  = (sx, sz, sy)

Rotator values are degrees (Pitch, Yaw, Roll) — they only resolve because
UAssetTool::ExtractPropertyValue now has a RotatorPropertyData case.
"""
import json
import math
import os
import sys

PAK_ROOT = "MotorTown/Content"


# ---------------------------------------------------------------- quaternions
def q_from_ue_rotator(pitch_deg, yaw_deg, roll_deg):
    """UE FRotator -> quaternion (x,y,z,w) in UE axes.

    UE applies Yaw about Z, Pitch about Y, Roll about X, in that order
    (R = Rz(yaw) * Ry(pitch) * Rx(roll)).
    """
    def axis_quat(ax, ay, az, deg):
        h = math.radians(deg) * 0.5
        s = math.sin(h)
        return (ax * s, ay * s, az * s, math.cos(h))

    qy = axis_quat(0, 0, 1, yaw_deg)
    qp = axis_quat(0, 1, 0, pitch_deg)
    qr = axis_quat(1, 0, 0, roll_deg)
    return q_mul(q_mul(qy, qp), qr)


def q_mul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    )


def q_conj(q):
    return (-q[0], -q[1], -q[2], q[3])


def q_normalize(q):
    n = math.sqrt(sum(c * c for c in q)) or 1.0
    return tuple(c / n for c in q)


def q_rotate(q, v):
    x, y, z, w = q
    vx, vy, vz = v
    # t = 2 * cross(q.xyz, v)
    tx = 2 * (y * vz - z * vy)
    ty = 2 * (z * vx - x * vz)
    tz = 2 * (x * vy - y * vx)
    return (
        vx + w * tx + (y * tz - z * ty),
        vy + w * ty + (z * tx - x * tz),
        vz + w * tz + (x * ty - y * tx),
    )


QC = q_from_ue_rotator(0.0, 0.0, -90.0)  # (x,y,z)_ue -> (x,z,-y)
QC_INV = q_conj(QC)


def ue_to_gltf_quat(q_ue):
    q = q_mul(q_mul(QC, q_ue), QC_INV)
    return q_normalize(q)


# ------------------------------------------------------------------ extraction
def vec(prop, key):
    """RelativeLocation / RelativeScale3D are {_StructType, <key>:{X,Y,Z}}."""
    if not isinstance(prop, dict):
        return None
    inner = prop.get(key)
    if not isinstance(inner, dict):
        return None
    return (float(inner.get("X", 0)), float(inner.get("Y", 0)), float(inner.get("Z", 0)))


def rot(prop):
    """RelativeRotation is {_StructType, RelativeRotation:{Pitch,Yaw,Roll}}."""
    if not isinstance(prop, dict):
        return None
    inner = prop.get("RelativeRotation")
    if isinstance(inner, dict):
        return (float(inner.get("Pitch", 0)), float(inner.get("Yaw", 0)), float(inner.get("Roll", 0)))
    if isinstance(inner, list) and len(inner) == 3:
        return tuple(float(v) for v in inner)
    return None


def pak_path(game_path):
    """/Game/Cars/Models/Boxy/Body/Body -> MotorTown/Content/Cars/Models/Boxy/Body/Body

    De-repetition and the tolerant fallback happen inside the C# extractor, which
    is the side that can enumerate the pak.
    """
    if game_path.startswith("/Game/"):
        return PAK_ROOT + game_path[len("/Game"):]
    return game_path


def merge_base(exports, base_exports):
    """Variant inheritance: a *_Bus / *_Police / *_Ambulance blueprint only
    serializes its own overrides — the mesh assignments live on the base class.
    Fill every property the child left empty from the base component of the same
    ExportName; child values win where present."""
    child = {}
    for e in exports:
        if e.get("ExportName"):
            child.setdefault(e["ExportName"], e)

    merged, used = [], set()
    for b in base_exports:
        name = b.get("ExportName")
        c = child.get(name)
        if c is None:
            merged.append(b)
            continue
        props = dict(b.get("Properties") or {})
        for k, v in (c.get("Properties") or {}).items():
            if v not in (None, [], {}):
                props[k] = v
        merged.append({"ExportName": name, "Class": c.get("Class") or b.get("Class"), "Properties": props})
        used.add(name)
    for name, c in child.items():
        if name not in used:
            merged.append(c)
    return merged


def find_base(name, parsed_dir):
    """Progressive '_'-suffix stripping until a sibling blueprint with meshes exists."""
    parts = name.split("_")
    for i in range(len(parts) - 1, 0, -1):
        cand = "_".join(parts[:i])
        path = os.path.join(parsed_dir, cand + "_parsed.json")
        if os.path.exists(path) and cand != name:
            return cand, path
    return None, None


def colour_data(exports, vehicle=""):
    """Default paints live on the vehicle CDO, not on the materials.

    ColorSlots  -- the paint regions the vehicle exposes (Body_01, Body_02, Window,
                   Seat_01 ...) with their default colour/metallic/roughness.
    BodyColors  -- the paint variants the game picks from at random on spawn. Each
                   entry maps slot key -> RGBA; alpha 0 means "slot not painted", so
                   the ColorSlot default applies.
    """
    cdo = next((e for e in exports
                if str(e.get("ExportName", "")).startswith("Default__" + vehicle + "_")), None)
    if cdo is None:
        cdo = next((e for e in exports if str(e.get("ExportName", "")).startswith("Default__")), None)
    if not cdo:
        return {"colorSlots": {}, "paints": []}
    pr = cdo.get("Properties") or {}

    slots = {}
    for ent in (pr.get("ColorSlots") or {}).get("Entries", []) or []:
        v = ent.get("Value") or {}
        dc = ((v.get("DefaultColor") or {}).get("DefaultColor") or {})
        slots[ent.get("Key")] = {
            "name": v.get("DisplayName"),
            "defaultColor": [dc.get("R", 255), dc.get("G", 255), dc.get("B", 255), dc.get("A", 255)],
            "metallic": v.get("DefaultMetallic"),
            "roughness": v.get("DefaultRoughness"),
            "useAlpha": bool(v.get("bUseColorAlpha")),
        }

    paints = []
    for pc in pr.get("BodyColors") or []:
        scheme = {}
        for ent in ((pc.get("Colors") or {}).get("Entries") or []):
            c = ((ent.get("Value") or {}).get("Colors") or {})
            scheme[ent.get("Key")] = [c.get("R", 0), c.get("G", 0), c.get("B", 0), c.get("A", 0)]
        if scheme:
            paints.append(scheme)
    return {"colorSlots": slots, "paints": paints}


def build(parsed_json_path, vehicle, out_dir, parsed_dir=None, inherit=True):
    data = json.load(open(parsed_json_path))
    exports = data["Data"]["Exports"]
    inherited_from = None
    if inherit and not any(
        isinstance((e.get("Properties") or {}).get("StaticMesh"), dict)
        and (e["Properties"]["StaticMesh"] or {}).get("Path")
        for e in exports
    ):
        base, base_path = find_base(vehicle, parsed_dir or os.path.dirname(parsed_json_path))
        if base:
            base_exports = json.load(open(base_path))["Data"]["Exports"]
            exports = merge_base(exports, base_exports)
            inherited_from = base
            print(f"  {vehicle}: no meshes of its own -> inheriting geometry from {base}")

    by_name = {}
    for e in exports:
        n = e.get("ExportName")
        if n and n not in by_name:
            by_name[n] = e

    def world(export, depth=0):
        """Compose this export's transform with its ancestors' (UE space)."""
        p = export.get("Properties") or {}
        loc = vec(p.get("RelativeLocation"), "RelativeLocation") or (0.0, 0.0, 0.0)
        scl = vec(p.get("RelativeScale3D"), "RelativeScale3D") or (1.0, 1.0, 1.0)
        r = rot(p.get("RelativeRotation"))
        q = q_from_ue_rotator(*r) if r else (0.0, 0.0, 0.0, 1.0)

        ap = p.get("AttachParent")
        parent = by_name.get(ap.get("ObjectName")) if isinstance(ap, dict) else None
        if parent is None or depth > 8:
            return loc, q, scl
        ploc, pq, pscl = world(parent, depth + 1)
        # world = parent * local
        scaled = (loc[0] * pscl[0], loc[1] * pscl[1], loc[2] * pscl[2])
        rotated = q_rotate(pq, scaled)
        wloc = (ploc[0] + rotated[0], ploc[1] + rotated[1], ploc[2] + rotated[2])
        wq = q_normalize(q_mul(pq, q))
        wscl = (pscl[0] * scl[0], pscl[1] * scl[1], pscl[2] * scl[2])
        return wloc, wq, wscl

    meshes, seen, parts = [], {}, []
    for e in exports:
        p = e.get("Properties") or {}
        sm = p.get("StaticMesh")
        if not (isinstance(sm, dict) and sm.get("Type") == "Import" and sm.get("Path")):
            continue
        game_path = sm["Path"]
        key = pak_path(game_path)
        name = os.path.basename(game_path.rstrip("/")) or "mesh"
        if key not in seen:
            seen[key] = name
            meshes.append({"name": name, "path": key})
        loc, q, scl = world(e)
        # UE cm -> metres, axis swap (x, z, -y)
        pos_m = (loc[0] / 100.0, loc[2] / 100.0, -loc[1] / 100.0)
        q_gltf = ue_to_gltf_quat(q)
        parts.append({
            "id": e.get("ExportName"),
            "class": e.get("Class"),
            "mesh": name,
            "glb": name + ".glb",
            "position": [round(v, 5) for v in pos_m],
            "rotation": [round(v, 6) for v in q_gltf],
            "scale": [round(scl[0], 5), round(scl[2], 5), round(scl[1], 5)],
        })

    os.makedirs(out_dir, exist_ok=True)
    manifest = {
        "format": 2,
        "vehicle": vehicle,
        "inheritedFrom": inherited_from,
        "source": os.path.basename(parsed_json_path),
        "units": "metres",
        "parts": parts,
        **colour_data(exports, vehicle),
    }
    with open(os.path.join(out_dir, vehicle + ".json"), "w") as f:
        json.dump(manifest, f, indent=1)
    with open(os.path.join(out_dir, "meshes_" + vehicle + ".json"), "w") as f:
        json.dump(meshes, f, indent=1)
    print(f"{vehicle}: {len(parts)} mounts, {len(meshes)} unique meshes")
    return manifest, meshes


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print(__doc__)
        print("usage: mk_manifest.py <out_dir_of_parsed_json> <vehicle> <out_dir> [more vehicles...]")
        sys.exit(2)
    parsed_dir, out_dir = sys.argv[1], sys.argv[2]
    for vehicle in sys.argv[3:]:
        build(os.path.join(parsed_dir, vehicle + "_parsed.json"), vehicle, out_dir, parsed_dir=parsed_dir)
