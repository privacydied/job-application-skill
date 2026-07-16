#!/usr/bin/env bash
# volume_loop.sh — persistent LinkedIn Easy-Apply driver toward a big target.
# Re-sources fresh EA inventory each cycle (clearing soft cooldown so rotation surfaces
# new postings), then drains the queue headlessly via apply_queue.py. Self-heals the tab.
#
# Logging: writes directly to volume-loop.log (NOT piped through tail, which buffers).
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
source .jobenv.run
export APPLY_TARGET=300

LOG="volume-loop.log"
MAX_CYCLES="${1:-60}"
TARGET_APPLIED="${2:-100}"
BASE_APPLIED=115

stamp(){ date '+%Y-%m-%dT%H:%M:%S'; }
log(){ echo "$(stamp) $*" | tee -a "$LOG"; }

clear_cooldown(){
  # keep only hackney/wttj (fixed-key boards); drop linkedin/indeed/csj so refresh re-sources
  python3 - <<'PY'
import csv
try:
    rows=list(csv.reader(open('board-cooldown.csv')))
except FileNotFoundError:
    rows=[]
keep=[r for r in rows if r and r[0] in ('hackney','wttj')]
with open('board-cooldown.csv','w',newline='') as f:
    w=csv.writer(f); w.writerows(keep)
PY
}

applied_total(){
  awk -F',' 'NR>1 && $1 ~ /2026-07-15/ && $6=="Applied"{c++} END{print c+0}' application-tracker.csv
}

log "=== volume_loop start: target +$TARGET_APPLIED applied (cumulative 115+$TARGET_APPLIED), max $MAX_CYCLES cycles ==="
for c in $(seq 1 "$MAX_CYCLES"); do
  CUR=$(applied_total)
  if [ "$CUR" -ge $((BASE_APPLIED + TARGET_APPLIED)) ]; then
    log "REACHED cumulative target (115+$TARGET_APPLIED=$((BASE_APPLIED+TARGET_APPLIED))). stopping."
    break
  fi
  log "CYCLE $c — applied_today=$CUR (target cumulative $((BASE_APPLIED+TARGET_APPLIED)))"
  # self-heal tab before each cycle
  python3 - <<'PY' || true
import sys
sys.path.insert(0,'sites/_common/scripts')
import cfx
try:
    cfx.set_tab(cfx.ensure_tab(persist=False))
except Exception as e:
    print("tab heal failed:", e)
PY
  clear_cooldown
  log "  -> refresh source (linkedin EA, no JD screen) + drain queue"
  python3 scripts/apply_queue.py --refresh --force --no-screen --boards linkedin \
     --ats linkedin-easyapply >> "$LOG" 2>&1
  rc=$?
  CUR2=$(applied_total)
  delta=$((CUR2 - CUR))
  log "  -> apply_queue rc=$rc | cycle delta applied_today: +$delta (now $CUR2)"
  if [ "$rc" -eq 9 ]; then
    log "  -> tab dead signal; will re-heal next cycle"
  fi
  # brief breathing pause so LinkedIn inventory can rotate
  sleep 20
done
log "=== volume_loop done. final applied_today=$(applied_total) ==="
