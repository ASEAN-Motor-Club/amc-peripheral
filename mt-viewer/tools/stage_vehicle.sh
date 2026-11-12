#!/bin/bash
# stage_vehicle.sh — manifest -> GLB+textures export -> viewer asset dir.
# usage: stage_vehicle.sh <GameVehicleName> [<slug>]
#   e.g. stage_vehicle.sh Atlas_6x4_Semi semi
# Output: site/<slug>/{<slug>.json, glb/, materials.json, textures/}
# Runs the CUE4Parse export through tools/build.sh (host, env-safe).
set -euo pipefail
V=${1:?vehicle name}
SLUG=${2:-$(echo "$V" | tr '[:upper:]' '[:lower:]')}
ROOT=/opt/data/workspace/mt-viewer
PARSED=/opt/data/workspace/amc-server/mt-pak-extract-wt-0719/out
BUILD=$ROOT/build/$SLUG-mat
SITE=$ROOT/site/$SLUG

python3 "$ROOT/tools/mk_manifest.py" "$PARSED" "$ROOT/staged" "$V"
mkdir -p "$BUILD"
# geometry (+ the exporter's own material sidecars/textures, harmless extras)
bash /opt/data/scripts/hostrun.sh "$ROOT/tools/build.sh" "$BUILD" "$ROOT/staged/meshes_$V.json" --materials --no-build \
  | grep -E "OK |ERR |SKIP |DONE" || true
# material-graph params + decoded textures (this is what the viewer actually uses)
bash /opt/data/scripts/hostrun.sh "$ROOT/tools/mtmats.sh" "$ROOT/staged/meshes_$V.json" "$BUILD" "$ROOT/staged/${V}_materials.json" \
  | grep -E "^===|slot |WROTE" || true
rm -rf "$SITE/materials.json" "$SITE/textures" "$SITE/glb"
mkdir -p "$SITE"
python3 "$ROOT/tools/bake_materials.py" "$BUILD" "$SITE"
cp "$ROOT/staged/$V.json" "$SITE/$SLUG.json"
# parts the game mounts on a mesh socket (the steering wheel) carry no blueprint
# offset -- snap them onto the socket the extractor wrote next to the GLBs
python3 "$ROOT/tools/apply_sockets.py" "$SITE/$SLUG.json" "$BUILD" || true
# wheel meshes hang off the inner sidewall; centre them on the hub the blueprint gives
python3 "$ROOT/tools/fit_wheels.py" "$SITE/$SLUG.json" "$SITE/glb" || true
# rewrite the manifest so part glb filenames match the flat glb/ dir
python3 - "$SITE/$SLUG.json" <<'PY'
import json, sys
p = sys.argv[1]
m = json.load(open(p))
m["slug"] = p.rsplit("/", 1)[-1].replace(".json", "")
json.dump(m, open(p, "w"), indent=1)
PY
du -sh "$SITE" | sed 's/^/staged: /'
