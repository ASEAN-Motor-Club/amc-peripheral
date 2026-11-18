#!/bin/bash
# restage_bodyvariants.sh — re-stage only the blueprints whose CDO carries a
# BodyMaterialList (liveries/decals), plus the two vehicles whose body mesh path
# was resolved from the uasset import table (Brcuda, Edit1).
# Resumable: appends to build/restage.log, skips nothing (always re-stages).
set -uo pipefail
ROOT=/opt/data/workspace/mt-viewer
LOG=$ROOT/build/restage.log
mkdir -p "$ROOT/build"
: >"$LOG"
mapfile -t LIST < "$ROOT/build/bodyvariants.txt"
EXTRA=(Brcuda Edit1)
echo "$(date -u +%H:%M:%S) re-staging ${#LIST[@]} body-variant blueprints + ${#EXTRA[@]} mesh fixes" | tee -a "$LOG"
for V in "${LIST[@]}" "${EXTRA[@]}"; do
  [ -z "$V" ] && continue
  SLUG=$(echo "$V" | tr '[:upper:]' '[:lower:]')
  echo "=== $(date -u +%H:%M:%S) $V -> $SLUG" | tee -a "$LOG"
  if bash "$ROOT/tools/stage_vehicle.sh" "$V" "$SLUG" >>"$LOG" 2>&1; then
    echo "    ok" | tee -a "$LOG"
  else
    echo "    FAILED $V" | tee -a "$LOG"
  fi
done
python3 "$ROOT/tools/make_index.py" "$ROOT/site" | tee -a "$LOG"
echo "$(date -u +%H:%M:%S) DONE rstaged=$(( ${#LIST[@]} + ${#EXTRA[@]} ))" | tee -a "$LOG"
