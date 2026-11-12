#!/bin/bash
# fix_origin_wheels.sh — place steering wheels that are still at the blueprint origin.
#
# Their bodies carry a SteeringWheel socket in the pak, but no sockets sidecar was
# written for them, so apply_sockets had nothing to mount against. For each affected
# vehicle: read the body package's sockets straight from the pak, snap the wheel, and
# re-centre the road wheels.
#
# usage: fix_origin_wheels.sh [slug...]   (default: every manifest with a wheel at origin)
set -uo pipefail
ROOT=/opt/data/workspace/mt-viewer
SOCK=/opt/data/cache/scratch/sockets
mkdir -p "$SOCK"

list_origin() {
  python3 - <<'PY'
import glob, json, os
for f in sorted(glob.glob("/opt/data/workspace/mt-viewer/site/*/*.json")):
    if f.endswith("materials.json"):
        continue
    try:
        m = json.load(open(f))
    except Exception:
        continue
    if not isinstance(m, dict) or "parts" not in m:
        continue
    sw = [p for p in m["parts"] if "SteeringWheel" in str(p.get("id", ""))]
    if sw and all(abs(v) < 1e-6 for v in sw[0]["position"]):
        print(os.path.basename(os.path.dirname(f)))
PY
}

if [ "$#" -gt 0 ]; then
  slugs=("$@")
else
  mapfile -t slugs < <(list_origin)
fi

fixed=0; still=0
for slug in "${slugs[@]}"; do
  man="$ROOT/site/$slug/$slug.json"
  [ -f "$man" ] || continue
  V=$(python3 -c "import json;print(json.load(open('$man'))['vehicle'])" 2>/dev/null)
  meshes="$ROOT/staged/meshes_$V.json"
  [ -f "$meshes" ] || { echo "skip $slug (no mesh list)"; continue; }
  dir="$SOCK/$slug"
  mkdir -p "$dir"
  out=$(python3 "$ROOT/tools/fetch_sockets.py" "$man" "$meshes" "$dir" 2>&1 | tail -1)
  [ -n "$out" ] && echo "  $slug: $out"
  python3 "$ROOT/tools/apply_sockets.py" "$man" "$dir" >/dev/null 2>&1
  python3 "$ROOT/tools/fit_wheels.py" "$man" "$ROOT/site/$slug/glb" >/dev/null 2>&1
  if python3 -c "
import json,sys
m=json.load(open('$man'))
sw=[p for p in m['parts'] if 'SteeringWheel' in str(p.get('id',''))][0]
sys.exit(0 if any(abs(v)>1e-6 for v in sw['position']) else 1)"; then
    fixed=$((fixed+1))
  else
    still=$((still+1)); echo "  STILL AT ORIGIN: $slug"
  fi
done
echo "wheels placed: $fixed, still at origin: $still"
