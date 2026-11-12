#!/bin/bash
# restage_inherit.sh — re-stage the six reskins whose livery list lives on the base
# blueprint (Bongo_Bus, Elisa2_Police, Muhan_Police, NukePolice, NukeTaxi,
# Zydro_Police). Needed after body_material_data() learned the base fallback.
set -uo pipefail
ROOT=/opt/data/workspace/mt-viewer
LOG=$ROOT/build/restage_inherit.log
: >"$LOG"
for V in Bongo_Bus Elisa2_Police Muhan_Police NukePolice NukeTaxi Zydro_Police; do
  S=$(echo "$V" | tr 'A-Z' 'a-z')
  echo "=== $V -> $S" | tee -a "$LOG"
  if bash "$ROOT/tools/stage_vehicle.sh" "$V" "$S" >>"$LOG" 2>&1; then
    n=$(python3 -c "import json;print(len(json.load(open('$ROOT/site/$S/materials.json')).get('bodyVariants') or []))")
    echo "    ok variants=$n" | tee -a "$LOG"
  else
    echo "    FAILED $V" | tee -a "$LOG"
  fi
done
python3 "$ROOT/tools/make_index.py" "$ROOT/site" | tee -a "$LOG"
echo "DONE" | tee -a "$LOG"
