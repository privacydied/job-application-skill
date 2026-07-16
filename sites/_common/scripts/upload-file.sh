#!/bin/bash
# upload-file.sh — attach a local file to a file-input on the current camofox tab.
# Stages the file into uploads/ (bind-mounted into the container at /uploads), then
# POSTs /tabs/{tab}/upload; removes the staged copy afterward unless --keep.
#
#   upload-file.sh <file-input-ref> <path-to-file> [--keep]
#
# Env (same as cfx.sh): CFX_KEY (bearer), CFX_TAB (target tab), CFX_USER (default nasirjones).
# The <file-input-ref> is the snapshot ref of the <input type=file> to fill.
set -euo pipefail

REF="${1:?usage: upload-file.sh <file-input-ref> <file> [--keep]}"
SRC="${2:?usage: upload-file.sh <file-input-ref> <file> [--keep]}"
KEEP=""; [ "${3:-}" = "--keep" ] && KEEP=1

: "${CFX_KEY:?Set CFX_KEY to the CAMOFOX_ACCESS_KEY bearer token}"
: "${CFX_TAB:?Set CFX_TAB to the target tab id}"
UID_="${CFX_USER:-nasirjones}"
U="${CFX_URL:-http://localhost:9377}"
A="Authorization: Bearer $CFX_KEY"

[ -f "$SRC" ] || { echo "ERROR: file not found: $SRC" >&2; exit 2; }

# uploads/ lives at the skill root (…/_common/scripts -> _common -> sites -> root).
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
UPLOADS="$HERE/uploads"
mkdir -p "$UPLOADS"
BASE="$(basename "$SRC")"
STAGED="$UPLOADS/$BASE"
cp -f "$SRC" "$STAGED"
# The container sees uploads/ as /uploads; the API's `path` is just the filename.
cleanup() { [ -z "$KEEP" ] && rm -f "$STAGED" 2>/dev/null || true; }
trap cleanup EXIT

# JSON-encode every field: a staged filename ($BASE) can legitimately contain
# spaces or (rarely) quotes/backslashes that would break naive "\"$BASE\""
# interpolation and produce an invalid body + silent 400 (same fix as cfx.sh).
BODY="$(python3 -c 'import json,sys;print(json.dumps({"userId":sys.argv[1],"ref":sys.argv[2],"path":sys.argv[3]}))' "$UID_" "$REF" "$BASE")"
RESP="$(curl -s -X POST -H "$A" -H "Content-Type: application/json" \
  -d "$BODY" "$U/tabs/$CFX_TAB/upload")"
echo "$RESP"
# Surface an obvious API error as a nonzero exit so callers don't assume success.
# Match the JSON error KEY (`"error":`) specifically — a bare `"error"` substring
# would false-positive on innocuous fields like `"errorCount":0`.
case "$RESP" in
  *'"error":'*|*'"error" :'*) echo "ERROR: upload rejected — see response above" >&2; exit 1 ;;
esac
# Empty response = curl couldn't reach the API (bad CFX_URL/tab); not a success either.
[ -n "$RESP" ] || { echo "ERROR: empty response from $U/tabs/$CFX_TAB/upload" >&2; exit 1; }
