#!/bin/bash
# sweep_manifests.sh — regenerate every staged manifest without re-exporting geometry.
#
# The catalogue was staged while four generator fixes were landing (socket-mounted
# parts, hub-centred wheels, duplicate paint keys, duplicate colour slots), so the
# vehicles staged before each fix still carry the old defects. Regenerating the
# manifest from the parsed blueprints is cheap; the GLBs and textures on disk are
# unaffected and are reused as-is.
#
# usage: sweep_manifests.sh [slug...]   (default: every dir under site/)
set -uo pipefail
ROOT=/opt/data/workspace/mt-viewer
PARSED=/opt/data/workspace/amc-server/mt-pak-extract-wt-0719/out
SITE=$ROOT/site

if [ "$#" -gt 0 ]; then
  slugs=("$@")
else
  mapfile -t slugs < <(cd "$SITE" && for d in */; do echo "${d%/}"; done | sort)
fi

ok=0; fail=0
for slug in "${slugs[@]}"; do
  man="$SITE/$slug/$slug.json"
  [ -f "$man" ] || { echo "skip $slug (no manifest)"; continue; }
  V=$(python3 -c "import json;print(json.load(open('$man'))['vehicle'])" 2>/dev/null)
  [ -n "$V" ] || { echo "FAIL $slug (no vehicle name)"; fail=$((fail+1)); continue; }

  if ! python3 "$ROOT/tools/mk_manifest.py" "$PARSED" "$ROOT/staged" "$V" >/dev/null 2>&1; then
    echo "FAIL $slug (mk_manifest)"; fail=$((fail+1)); continue
  fi
  cp "$ROOT/staged/$V.json" "$man"
  python3 "$ROOT/tools/apply_sockets.py" "$man" "$ROOT/build/$slug-mat" >/dev/null 2>&1 || true
  python3 "$ROOT/tools/fit_wheels.py" "$man" "$SITE/$slug/glb" >/dev/null 2>&1 || true
  python3 - "$man" <<'PY'
import json, sys
p = sys.argv[1]
m = json.load(open(p))
m["slug"] = p.rsplit("/", 1)[-1].replace(".json", "")
json.dump(m, open(p, "w"), indent=1)
PY
  ok=$((ok+1))
done
echo "sweep done: ok=$ok fail=$fail"
