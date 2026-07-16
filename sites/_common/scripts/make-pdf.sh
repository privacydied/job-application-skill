#!/bin/bash
# make-pdf.sh — render a tailored resume HTML to an ATS-safe PDF via the Playwright
# browser container, then verify the text extracts. One call replaces the whole
# serve-on-LAN-IP → connect → print → verify recipe done per application.
#
#   make-pdf.sh <app-dir> [out.pdf] [html-filename]
#
#   <app-dir>       directory holding the tailored HTML (e.g. applications/acme-pd)
#   out.pdf         output path (default: <app-dir>/resume.pdf)
#   html-filename   HTML to render inside <app-dir> (default: resume.html)
#
# WHY A SCRIPT: the browser runs in a separate container and CANNOT read host files —
# file:// and localhost both fail — so the HTML must be served over the host's LAN IP
# and the Playwright client version must match the server (1.58.0) or the WS handshake
# 428s. That ceremony is identical every time, so it lives here, not in the operator's
# head. weasyprint/wkhtmltopdf are NOT installed on this host — this is the only path.
set -euo pipefail
SECONDS=0                              # bash builtin: seconds since script start (pdf-stage timer)
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

APP_DIR="${1:?usage: make-pdf.sh <app-dir> [out.pdf] [html-file]}"
OUT="${2:-$APP_DIR/resume.pdf}"
HTML="${3:-resume.html}"
PORT="${MAKE_PDF_PORT:-8931}"
PW_WS="${PW_WS:-ws://localhost:3006/}"
PW_VER="1.58.0"                       # MUST match the Playwright server or connect 428s
WORK="${PW_WORK:-/tmp/pw-work}"

[ -f "$APP_DIR/$HTML" ] || { echo "ERROR: $APP_DIR/$HTML not found" >&2; exit 2; }

# LAN IP the browser container can actually reach (host localhost is invisible to it).
# Use the source IP of the default route — robust against the many docker-bridge IPs.
LAN_IP="$(ip route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src"){print $(i+1); exit}}')"
[ -n "$LAN_IP" ] || { echo "ERROR: could not determine LAN IP (ip route get failed)" >&2; exit 2; }

# Pinned playwright-core, reinstalled only if missing or the wrong version.
# D.3: prerender-pdfs.sh already pre-warms the install once, so it exports
# PW_SKIP_VER_CHECK=1 to skip this per-child cat|sed|head subprocess trio (×N children).
if [ -z "${PW_SKIP_VER_CHECK:-}" ]; then
  HAVE_VER="$(cat "$WORK/node_modules/playwright-core/package.json" 2>/dev/null \
              | sed -n 's/.*"version": *"\([^"]*\)".*/\1/p' | head -1)"
  if [ "$HAVE_VER" != "$PW_VER" ]; then
    echo "[make-pdf] installing playwright-core@$PW_VER into $WORK" >&2
    mkdir -p "$WORK"
    ( cd "$WORK" && npm init -y >/dev/null 2>&1 && npm install "playwright-core@$PW_VER" --no-save >/dev/null 2>&1 )
  fi
fi

# Serve the app dir over the LAN, kill the server no matter how we exit.
python3 -m http.server "$PORT" --directory "$APP_DIR" >/dev/null 2>&1 &
SRV=$!
trap 'kill "$SRV" 2>/dev/null || true' EXIT
# Wait until the server actually accepts a request (fail loudly if it never does —
# e.g. the port is already in use), instead of a blind `sleep 1` that can race the
# render and produce a blank/failed PDF.
ready=""
for _ in $(seq 1 20); do
  if ! kill -0 "$SRV" 2>/dev/null; then
    echo "ERROR: local server exited immediately (port $PORT already in use?)" >&2; exit 2
  fi
  if curl -fsS -o /dev/null "http://127.0.0.1:$PORT/$HTML" 2>/dev/null; then ready=1; break; fi
  sleep 0.25
done
[ -n "$ready" ] || { echo "ERROR: local server on port $PORT did not become ready" >&2; exit 2; }

NODE_PATH="$WORK/node_modules" node -e '
const { chromium } = require("playwright-core");
(async () => {
  const [url, out, ws] = process.argv.slice(1);
  const b = await chromium.connect(ws, { timeout: 15000 });
  const p = await b.newPage();
  // D.2: the tailored resume is self-contained (inline CSS, no external fetches), so
  // "networkidle" just burns its 500ms network-silence debounce on every render. Wait
  // for "load" + fonts instead — exactly what affects layout — and skip the debounce.
  await p.goto(url, { waitUntil: "load", timeout: 30000 });
  await p.evaluate(() => (document.fonts && document.fonts.ready)
    ? document.fonts.ready.then(() => true) : true).catch(() => {});
  await p.pdf({ path: out, format: "A4", printBackground: true });
  await b.close();
})().catch(e => { console.error("PDF render failed: " + String(e)); process.exit(1); });
' "http://$LAN_IP:$PORT/$HTML" "$OUT" "$PW_WS"

[ -s "$OUT" ] || { echo "ERROR: no PDF produced at $OUT" >&2; exit 3; }

# ATS-safety gate: the PDF's text must extract cleanly (a table layout is fine as long
# as pdftotext yields readable text). Fail loudly if it comes back empty.
if command -v pdftotext >/dev/null 2>&1; then
  CHARS="$(pdftotext "$OUT" - 2>/dev/null | tr -d '[:space:]' | wc -c)"
  [ "$CHARS" -gt 0 ] || { echo "ERROR: $OUT has NO extractable text — not ATS-safe" >&2; exit 3; }
  echo "PDF: $OUT ($(wc -c < "$OUT") bytes, $CHARS extractable chars via pdftotext)"
else
  echo "PDF: $OUT ($(wc -c < "$OUT") bytes; pdftotext unavailable — text not verified)"
fi

# Record the pdf-stage wall-clock (no-op unless STAGETIMER is set; never fails the render).
python3 "$SELF_DIR/stagetimer.py" record pdf "$SECONDS" "$APP_DIR" 2>/dev/null || true
