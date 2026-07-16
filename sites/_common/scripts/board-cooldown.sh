#!/bin/bash
# board-cooldown.sh — remembers "this board+query was already confirmed dry" so the
# loop stops re-fetching (and re-token-spending on) a search that yields nothing new.
#
# WHY THIS EXISTS: application-tracker.csv + board-native hide (LinkedIn Dismiss /
# indeed feed.py hide) dedup individual POSTINGS fine — a posting never gets
# re-screened or re-applied-to twice. But nothing remembered "this whole board+query
# combo was already confirmed exhausted a few minutes ago", so every loop firing
# re-ran the full source-and-filter pass from scratch: re-fetch the feed, re-list
# every card, re-diff against the tracker — paying the enumeration+filtering token
# cost again and again even when zero new postings were ever found. This is the
# lightweight fix: skip re-sourcing entirely when a combo is in cooldown, instead of
# re-discovering "still dry" the expensive way every time.
#
# NOTE (2026-07-13): the check+mark are now enforced automatically inside the feed.py
# scripts via board_cooldown.py (the Python twin of this script, same CSV/format), so
# the loop no longer depends on the agent remembering to call this CLI. This CLI stays
# for ad-hoc inspection and manual overrides; it and board_cooldown.py interoperate on
# the same board-cooldown.csv.
#
# Usage:
#   board-cooldown.sh check <board> <query>          -> "clear" or "cooldown active: Xh remaining"
#   board-cooldown.sh mark  <board> <query> [hours]   -> record exhaustion (default 12h —
#                                                         most boards refresh roughly daily)
#
# <board> is a short slug (linkedin, indeed, wttj), <query> is the exact search string
# used (e.g. "Product Designer", "UX Designer") — different queries on the same board
# are tracked separately since they can surface different postings.

#
# IMPLEMENTATION (2026-07-13): this CLI now DELEGATES to board_cooldown.py so the two
# share ONE CSV-correct parser. The old awk -F',' implementation mis-split queries that
# are CSV-quoted because they contain commas or embedded quotes (e.g. the bundled
# boolean LinkedIn query in board-cooldown.csv), computing a different key than the
# Python twin — so `check` could report "clear" for a combo the loop had marked cooling.
# Delegation keeps the exact same usage and output strings while killing that mismatch.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

case "${1:-}" in
  check) exec python3 "$SCRIPT_DIR/board_cooldown.py" check "${2:?board}" "${3:?query}" ;;
  mark)  exec python3 "$SCRIPT_DIR/board_cooldown.py" mark  "${2:?board}" "${3:?query}" "${4:-12}" ;;
  *) echo "Usage: board-cooldown.sh check|mark <board> <query> [hours]"; exit 1 ;;
esac
