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


def has_wheel_socket(build_dir):
    for path in glob.glob(os.path.join(build_dir, "**", "*.sockets.json"), recursive=True):
        try:
            if any(s.get("name") == "SteeringWheel" for s in json.load(open(path))):
                return True
        except Exception:
            continue
    return False


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

    if has_wheel_socket(build_dir):
        return 0

    # Which package carries the cabin socket varies by model: the Atlas keeps it on
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
    targets = body_like + others
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
        for cand in cands:
            if not cand:
                continue
            # /Game/... form that the pak tools expect
            game = "/Game/" + cand.split("Content/", 1)[-1] if "Content/" in cand else cand
            out = os.path.join(build_dir, mesh + ".sockets.json")
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
                if any(x.get("name") == "SteeringWheel" for x in data):
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
            if "SteeringWheel" in names:
                return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
