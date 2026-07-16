#!/bin/bash
# open_tab.sh — SUPERSEDED thin shim. The whole tab lifecycle — open (with recovery
# from camofox's flaky create-500), health-check, self-heal on a dropped tab, and
# .runtab persistence — now lives in ONE place: cfx.py (`ensure_tab` / `open_tab`).
# This script is kept only so existing callers keep working; it just delegates, so
# there is no second copy of the logic to drift out of sync.
#
#   bash open_tab.sh   # -> prints a LIVE job-apply tab id and (re)writes .runtab
#
# Unlike the old hand-rolled version it REUSES the current tab when it's still
# alive (sources .runtab first) instead of always opening a fresh one, so it no
# longer churns tabs toward the 8-tab cap on every call.
set -u
cd "$(dirname "$0")"
source .jobenv
[ -f .runtab ] && source .runtab            # pick up the last tab so a live one is reused
export CFX_TAB_FILE="$PWD/.runtab"          # ensure_tab persists the (re)opened id here
exec python3 sites/_common/scripts/cfx.py ensure-tab
