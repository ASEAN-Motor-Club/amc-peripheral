#!/bin/bash
# stage_all.sh — stage every vehicle blueprint in the parsed extraction.
# Resumable: vehicles already present in site/<slug>/ are skipped, so an
# interrupted run can just be restarted. One pak mount per vehicle, sequential
# (~45-90 s each), so the full catalogue is a long job — run it under nohup/tmux
# or a background task, not in a foreground turn.
#
# usage: stage_all.sh [limit] [filter-regex]
set -uo pipefail
ROOT=/opt/data/workspace/mt-viewer
PARSED=/opt/data/workspace/amc-server/mt-pak-extract-wt-0719/out
LIMIT=${1:-0}
FILTER=${2:-.}
LOG=$ROOT/build/stage_all.log
mkdir -p "$ROOT/build"

# A vehicle blueprint is any parsed asset that contains an MTVehicleRootComponent
# export; that is the reliable marker across cars, trucks, buses and trailers.
mapfile -t VEHICLES < <(grep -l "MTVehicleRootComponent" "$PARSED"/*_parsed.json 2>/dev/null \
  | xargs -n1 basename | sed 's/_parsed\.json$//' | sort)

echo "$(date -u +%H:%M:%S) ${#VEHICLES[@]} vehicle blueprints" | tee -a "$LOG"
n=0; done_n=0
for V in "${VEHICLES[@]}"; do
  echo "$V" | grep -qiE "$FILTER" || continue
  SLUG=$(echo "$V" | tr '[:upper:]' '[:lower:]')
  if [ -f "$ROOT/site/$SLUG/$SLUG.json" ] && [ "${FORCE:-0}" != "1" ]; then
    done_n=$((done_n+1)); continue
  fi
  n=$((n+1))
  [ "$LIMIT" -gt 0 ] && [ "$n" -gt "$LIMIT" ] && { echo "limit $LIMIT reached" | tee -a "$LOG"; break; }
  echo "=== $(date -u +%H:%M:%S) staging $V -> $SLUG" | tee -a "$LOG"
  if bash "$ROOT/tools/stage_vehicle.sh" "$V" "$SLUG" >>"$LOG" 2>&1; then
    echo "    ok" | tee -a "$LOG"
  else
    echo "    FAILED $V" | tee -a "$LOG"
  fi
done
python3 "$ROOT/tools/make_index.py" "$ROOT/site" | tee -a "$LOG"
echo "$(date -u +%H:%M:%S) done: staged $n new, $done_n already present" | tee -a "$LOG"
