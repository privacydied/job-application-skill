#!/bin/bash
# prerender-pdfs.sh — render MANY tailored resumes to PDF concurrently.
#
#   prerender-pdfs.sh <app-dir> [<app-dir> ...]
#
# WHY: PDF render (make-pdf.sh) is pure, deterministic wall-clock — serve HTML on the
# LAN, drive the Playwright container, verify text extracts (~several seconds each). In
# the naive loop it sits ON the critical path: tailor #1 -> render #1 -> browser-fill #1
# -> tailor #2 -> render #2 -> ...  Each render blocks the next posting's browser work.
#
# The fix (lever 3): tailor the whole work list FIRST, then batch-render every posting's
# PDF here in ONE parallel pass, so rendering overlaps itself and is OFF the per-posting
# critical path. N sequential ~6s renders (~N*6s) collapse to ~ceil(N/JOBS)*6s, and no
# render blocks a browser fill. (Browser fills still serialize — camofox is single-tab on
# the Hermes path — so this parallelizes the render step, which is the part that safely can.)
#
# Concurrency is capped (PRERENDER_JOBS, default 4) because all jobs share ONE Playwright
# container; each job gets its own local HTTP port so the servers don't collide.
#
# Exit: 0 iff every render succeeded; non-zero = at least one failed (its tail is printed).
set -uo pipefail                       # NOT -e: collect every job's result, don't abort on first fail

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ "$#" -ge 1 ] || { echo "usage: prerender-pdfs.sh <app-dir> [<app-dir> ...]" >&2; exit 2; }

JOBS="${PRERENDER_JOBS:-4}"            # max concurrent renders
BASE_PORT="${PRERENDER_BASE_PORT:-8940}"
WORK="${PW_WORK:-/tmp/pw-work}"
PW_VER="1.58.0"                        # keep in lockstep with make-pdf.sh / the PW server

# Pre-warm the shared playwright-core install ONCE. Without this, parallel jobs would all
# find node_modules missing at the same instant and race `npm install` into the same dir.
HAVE_VER="$(sed -n 's/.*"version": *"\([^"]*\)".*/\1/p' \
            "$WORK/node_modules/playwright-core/package.json" 2>/dev/null | head -1)"
if [ "$HAVE_VER" != "$PW_VER" ]; then
  echo "[prerender] warming playwright-core@$PW_VER in $WORK" >&2
  mkdir -p "$WORK"
  ( cd "$WORK" && npm init -y >/dev/null 2>&1 && npm install "playwright-core@$PW_VER" --no-save >/dev/null 2>&1 )
fi

DIRS=("$@")
N="${#DIRS[@]}"
LOGDIR="$(mktemp -d)"
trap 'rm -rf "$LOGDIR"' EXIT

run_one() {  # index, app-dir — distinct port per job so the http.server instances don't collide
  local i="$1" dir="$2"
  # D.3: the install is pre-warmed above, so each child skips its own version check.
  PW_SKIP_VER_CHECK=1 MAKE_PDF_PORT=$((BASE_PORT + i)) "$SELF_DIR/make-pdf.sh" "$dir" \
    >"$LOGDIR/$i.log" 2>&1
  echo "$?" >"$LOGDIR/$i.rc"
}

# D.4 (opt-in via PRERENDER_SINGLE_CONN=1): render ALL dirs over ONE Playwright
# connection + ONE http.server (rooted at CWD), a page per dir — removes N-1 node
# startups + connects + servers. Writes each index's .rc/.log so the shared collector
# below is unchanged. Returns 0 if it handled the batch, 1 to fall back to per-dir
# (LAN IP undiscoverable, server didn't come up, a dir outside CWD, or node produced
# no output). Per-page isolation lives in multi-render.js.
render_single_conn() {
  local pw_ws lan_ip root_port srv ready rel out chars idx rc rest
  pw_ws="${PW_WS:-ws://localhost:3006/}"
  lan_ip="$(ip route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src"){print $(i+1); exit}}')"
  [ -n "$lan_ip" ] || return 1
  root_port="$BASE_PORT"
  python3 -m http.server "$root_port" --directory "$PWD" >/dev/null 2>&1 &
  srv=$!
  ready=""
  for _ in $(seq 1 20); do
    kill -0 "$srv" 2>/dev/null || break
    curl -fsS -o /dev/null "http://127.0.0.1:$root_port/" 2>/dev/null && { ready=1; break; }
    sleep 0.25
  done
  if [ -z "$ready" ]; then kill "$srv" 2>/dev/null || true; return 1; fi
  local args=() node_to_dir=()
  local jj nidx
  for ((jj=0; jj<N; jj++)); do
    # Guard like make-pdf.sh: a missing resume.html must FAIL, not render the server's
    # 404 page as a bogus PDF. Mark it directly and keep it OUT of the node batch.
    if [ ! -f "${DIRS[$jj]}/resume.html" ]; then
      echo 2 >"$LOGDIR/$jj.rc"; echo "resume.html not found" >"$LOGDIR/$jj.log"
      continue
    fi
    case "${DIRS[$jj]}" in
      /*) rel="$(python3 -c 'import os,sys;print(os.path.relpath(sys.argv[1], os.getcwd()))' "${DIRS[$jj]}")" ;;
      *)  rel="${DIRS[$jj]#./}" ;;
    esac
    case "$rel" in ../*) kill "$srv" 2>/dev/null || true; return 1 ;; esac   # outside CWD → fall back
    args+=("http://$lan_ip:$root_port/$rel/resume.html" "${DIRS[$jj]}/resume.pdf")
    node_to_dir+=("$jj")                         # node job index -> DIRS index
  done
  if [ "${#node_to_dir[@]}" -eq 0 ]; then kill "$srv" 2>/dev/null || true; return 0; fi
  NODE_PATH="$WORK/node_modules" node "$SELF_DIR/multi-render.js" "$pw_ws" "${args[@]}" \
    >"$LOGDIR/multi.out" 2>&1
  kill "$srv" 2>/dev/null || true
  [ -s "$LOGDIR/multi.out" ] || return 1        # no output → fall back
  while read -r nidx rc rest; do
    case "$nidx" in ''|*[!0-9]*) continue ;; esac
    idx="${node_to_dir[$nidx]}"                   # translate to the real DIRS index
    [ -n "$idx" ] || continue
    out="${DIRS[$idx]}/resume.pdf"
    if [ "$rc" = "0" ] && [ -s "$out" ]; then
      if command -v pdftotext >/dev/null 2>&1; then
        chars="$(pdftotext "$out" - 2>/dev/null | tr -d '[:space:]' | wc -c)"
        if [ "$chars" -gt 0 ]; then
          echo 0 >"$LOGDIR/$idx.rc"; echo "PDF ok ($chars extractable chars)" >"$LOGDIR/$idx.log"
        else
          echo 3 >"$LOGDIR/$idx.rc"; echo "no extractable text — not ATS-safe" >"$LOGDIR/$idx.log"
        fi
      else
        echo 0 >"$LOGDIR/$idx.rc"; echo "PDF ok (pdftotext unavailable)" >"$LOGDIR/$idx.log"
      fi
    else
      echo 1 >"$LOGDIR/$idx.rc"; echo "render failed: $rest" >"$LOGDIR/$idx.log"
    fi
  done < "$LOGDIR/multi.out"
  return 0
}

echo "[prerender] $N posting(s), up to $JOBS at a time" >&2
handled=0
if [ -n "${PRERENDER_SINGLE_CONN:-}" ]; then
  echo "[prerender] D.4 single-connection path (PRERENDER_SINGLE_CONN set)" >&2
  if render_single_conn; then handled=1
  else echo "[prerender] single-connection path fell back to per-dir" >&2; fi
fi
# D.1: fill-as-you-drain instead of a batch barrier. The old loop launched $JOBS jobs
# then WAITED for the whole batch before starting the next — so one slow render left the
# other slots idle. `wait -n` (bash 4.3+) returns as soon as ANY one finishes, and we
# immediately launch the next, keeping all $JOBS slots saturated: wall-clock ≈ total/JOBS
# instead of ceil(N/JOBS)×max. (Falls back to a batch barrier if wait -n is unsupported.)
i=0
running=0
if [ "$handled" = 1 ]; then
  :                                     # D.4 already rendered everything + wrote .rc files
elif [ "${BASH_VERSINFO[0]:-0}" -gt 4 ] || \
     { [ "${BASH_VERSINFO[0]:-0}" -eq 4 ] && [ "${BASH_VERSINFO[1]:-0}" -ge 3 ]; }; then
  while [ "$i" -lt "$N" ] || [ "$running" -gt 0 ]; do
    while [ "$running" -lt "$JOBS" ] && [ "$i" -lt "$N" ]; do
      run_one "$i" "${DIRS[$i]}" &
      i=$((i + 1)); running=$((running + 1))
    done
    if [ "$running" -gt 0 ]; then
      wait -n 2>/dev/null || true       # reap ONE finished job; rc is captured in its .rc file
      running=$((running - 1))
    fi
  done
else
  while [ "$i" -lt "$N" ]; do           # fallback: batch barrier (older bash)
    pids=()
    for ((k=0; k<JOBS && i<N; k++, i++)); do
      run_one "$i" "${DIRS[$i]}" &
      pids+=("$!")
    done
    wait "${pids[@]}"
  done
fi

fail=0
for ((j=0; j<N; j++)); do
  rc="$(cat "$LOGDIR/$j.rc" 2>/dev/null || echo 99)"
  if [ "$rc" = "0" ]; then
    echo "OK   ${DIRS[$j]}"
  else
    echo "FAIL ${DIRS[$j]} (rc=$rc)"
    sed 's/^/       | /' "$LOGDIR/$j.log" 2>/dev/null | tail -6
    fail=$((fail + 1))
  fi
done
echo "prerender: $((N - fail))/$N succeeded"
[ "$fail" -eq 0 ]
