#!/usr/bin/env python3
"""fetch_sockets.py — pull a vehicle's mesh sockets straight out of the pak.

The geometry exporter does not always write a GLB for shared parts, and when it
doesn't it writes no sockets sidecar either — which left ~50 vehicles with their
steering wheel at the blueprint origin. The sockets are readable regardless, so
when a vehicle has no sidecar this fetches them for the body mesh and drops them
where apply_sockets.py looks.

usage: fetch_sockets.py <manifest.json> <meshes.json> <sockets-dir>
"""
import glob
import json
import os
import subprocess
import sys
import tempfile

PAK_SOCKETS = "/opt/data/scripts/pak_sockets.sh"
# Many vehicles share the same part packages (Dashboard_02, SideMirror...), and every
# lookup costs a dotnet start, so remember what each package contains.
CACHE_PATH = "/opt/data/cache/scratch/sockets/_pkg_cache.json"
# parts whose package is the one that carries the cabin sockets
BODY_PART_IDS = ("Mesh", "Body", "Body_01")
SOCKET_PART_SLOTS = {"RearWing", "TrailerHitch", "TaxiRoofSign"}
EXACT_SOCKET_IDS = {"SteeringWheel", "Exhaust_Left", "Exhaust_Right"}


def required_sockets(manifest, attachments_only=False):
    targets = set()
    for part in manifest.get("parts", []):
        if part.get("attachSocket"):
            targets.add(part["attachSocket"])
        if part.get("partSlot") in SOCKET_PART_SLOTS:
            targets.add(part["partSlot"])
        if not attachments_only and part.get("id") in EXACT_SOCKET_IDS:
            targets.add(part["id"])
    return targets


def available_sockets(build_dir):
    names = set()
    for path in glob.glob(os.path.join(build_dir, "**", "*.sockets.json"), recursive=True):
        try:
            names.update(s.get("name") for s in json.load(open(path)))
        except Exception:
            continue
    return names


def sidecar_path(build_dir, mesh, candidate, index):
    # Alternates can be different packages (frame vs mirrors). Never let a later
    # candidate overwrite the sockets already recovered for an earlier one.
    basename = candidate.rstrip("/").split("/")[-1] or "package"
    return os.path.join(build_dir, f"{mesh}__{index}_{basename}.sockets.json")


def main():
    if len(sys.argv) < 4:
        print("usage: fetch_sockets.py <manifest.json> <meshes.json> <sockets-dir>", file=sys.stderr)
        return 2
    man_path, meshes_path, build_dir = sys.argv[1:4]
    manifest = json.load(open(man_path))
    try:
        meshes = json.load(open(meshes_path))
    except Exception:
        return 0
    by_name = {m.get("name"): m for m in meshes if isinstance(m, dict)}

    attachments_only = len(sys.argv) > 4 and sys.argv[4] == "--attachments-only"
    needed = required_sockets(manifest, attachments_only)
    if not needed or needed.issubset(available_sockets(build_dir)):
        return 0

    # Which package carries the socket varies by model: the Atlas keeps steering
    # the Cab, the Boxy on a part that isn't the body at all. Try the body-ish parts
    # first, then every other part, stopping as soon as one yields a wheel socket.
    body_like, others = [], []
    for part in manifest.get("parts", []):
        mesh = part.get("mesh")
        if not mesh:
            continue
        if part.get("id") in BODY_PART_IDS or mesh in ("Body", "Cab"):
            body_like.append(mesh)
        else:
            others.append(mesh)
    # Hook/Hook_6x4 sockets live on model-specific frames, not wheel packages.
    # Probe every Cars/Models mesh before shared parts to avoid 45-second wheel misses.
    model_like = [mesh for mesh in others
                  if "/Cars/Models/" in str((by_name.get(mesh) or {}).get("path") or "")]
    model_like.sort(key=lambda mesh: 0 if any(
        token in mesh.lower() for token in ("frame", "body", "chassis")) else 1)
    if any(name.lower().startswith("hook") for name in needed):
        targets = model_like + body_like + [mesh for mesh in others if mesh not in model_like]
    else:
        targets = body_like + model_like + [mesh for mesh in others if mesh not in model_like]
    seen = set()
    for mesh in [t for t in targets if t]:
        if mesh in seen:
            continue
        seen.add(mesh)
        item = by_name.get(mesh)
        if not item:
            continue
        cands = [item.get("path")] + list(item.get("alt") or [])
        # The pak stores a mesh at Models/<Model>/<Asset> while the blueprint names
        # Models/<Model>/<Asset>/<Asset>; add the de-repeated spelling for mesh lists
        # generated before that candidate was added.
        derepeat = []
        for c in cands:
            parts = (c or "").split("/")
            if len(parts) >= 2 and parts[-1] == parts[-2]:
                derepeat.append("/".join(parts[:-1]))
        cands = [c for c in cands if c] + derepeat
        for index, cand in enumerate(cands):
            if not cand:
                continue
            # /Game/... form that the pak tools expect
            game = "/Game/" + cand.split("Content/", 1)[-1] if "Content/" in cand else cand
            out = sidecar_path(build_dir, mesh, cand, index)
            os.makedirs(os.path.dirname(out), exist_ok=True)
            cache = {}
            try:
                cache = json.load(open(CACHE_PATH))
            except Exception:
                cache = {}
            if game in cache:
                data = cache[game]
                if not data:
                    continue
                with open(out, "w") as f:
                    json.dump(data, f, indent=1)
                print(f"  sockets {mesh} <- {cand} (cached): {len(data)} {[x.get('name') for x in data][:4]}")
                if needed.issubset(available_sockets(build_dir)):
                    return 0
                continue
            tmp = tempfile.mktemp(suffix=".json", dir="/opt/data/cache/scratch")
            try:
                subprocess.run(["bash", PAK_SOCKETS, game, tmp],
                               capture_output=True, timeout=45)
            except Exception:
                continue
            if not os.path.exists(tmp):
                continue
            try:
                data = json.load(open(tmp))
            except Exception:
                continue
            cache[game] = data
            with open(CACHE_PATH, "w") as cf:
                json.dump(cache, cf)
            if not data:
                os.unlink(tmp)
                continue
            with open(out, "w") as f:
                json.dump(data, f, indent=1)
            os.unlink(tmp)
            names = [s.get("name") for s in data]
            print(f"  sockets {mesh} <- {cand}: {len(data)} {names[:4]}")
            if needed.issubset(available_sockets(build_dir)):
                return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
