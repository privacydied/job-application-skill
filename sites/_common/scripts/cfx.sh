#!/bin/bash
# cfx.sh — shared camofox REST helper used across ALL site scripts.
# Usage: cfx.sh <action> [args...]
#   snap                          -> accessibility snapshot of the tab
#   click <ref>                   -> click element by a11y ref (e.g. e8)
#   type  <ref> <text>            -> type text into element by ref
#   press <key>                   -> press a keyboard key (e.g. Escape, Enter)
#   nav   <url> [referer]         -> navigate the tab to a URL. A plausible
#                                     Referer is attached AUTOMATICALLY (see the
#                                     "Referer chains" note below) so a direct
#                                     nav to a deep job-posting URL stops looking
#                                     like an address-bar teleport. Pass an
#                                     explicit referer as the 2nd arg to override.
#   scroll [down|up] [amount]     -> scroll the page
#   shot  [outfile.png]           -> screenshot the tab
#   eval  '<js expression>'       -> evaluate JS in the tab, returns the result
#   eval-frame <frameSel> '<js>'  -> evaluate JS INSIDE an iframe's own document
#                                     (cross-origin OK, same frameSelector semantics
#                                     as click-frame) -- e.g. read a reCAPTCHA v2
#                                     anchor's REAL aria-checked state directly,
#                                     instead of inferring pass/fail from the
#                                     main-page token or a screenshot.
#   click-frame <frameSel> <sel>  -> click an element INSIDE an iframe (cross-origin
#                                     OK) -- e.g. a reCAPTCHA v2 anchor checkbox.
#   click-xy <x> <y>              -> trusted mouse click at page coordinates (no
#                                     selectable element needed) -- e.g. reCAPTCHA
#                                     image-challenge tiles located via the VL model.
#   list-tabs                     -> list ALL managed tabs for CFX_USER (see below)
#   find-popup                    -> list-tabs, but print only tabs != CFX_TAB
#                                     (i.e. candidate popups) with tabId + url
#   open-tab [key] [url]          -> open a fresh tab; prints new tabId (export CFX_TAB)
#   close-tab [tabId]             -> close CFX_TAB (or an explicit tabId) to free
#                                     RAM. Do this the moment you're DONE with a
#                                     posting -- open tabs accumulate memory and
#                                     hit a ~8-tab cap where POST /tabs starts
#                                     failing. Safe: login/cookies live in the
#                                     browser PROFILE, not the tab, so closing a
#                                     tab never logs you out. Idempotent.
#   record-captcha-fail <domain>  -> log a Turnstile/CAPTCHA failure for domain
#   check-cooldown <domain>       -> "clear" or "cooldown active: ...Nh remaining"
#                                     -- check BEFORE navigating to a domain that
#                                     failed a CAPTCHA recently. See cooldown
#                                     tracker note below.
#
# Every page-affecting action (click/type/press/nav/scroll/eval/click-selector)
# now waits on a randomized human_pause() first (~0.7-2.9s, occasionally
# longer) instead of firing immediately -- see the function definition below
# for why. `scroll` also breaks one big scroll into several smaller wheel
# ticks instead of one atomic jump, and `type` uses real per-key keyboard
# events for short text instead of an instant value-set. Same logic is
# mirrored in Hermes's tools/browser_camofox.py for when the autonomous
# agent (not Claude Code) drives Camofox -- keep both in sync. (Viewport
# diversity across tabs was ALSO attempted here at one point -- removed, see
# the note in the `open-tab` action for why, and why it turned out not to be
# needed anyway.)
#
# --- Referer chains (nav) -----------------------------------------------------
# A REAL user almost never reaches a deep job-posting URL by typing it into the
# address bar -- they click through from a listings/search page or a Google
# result, and that click carries a Referer header (and makes the browser send
# Sec-Fetch-Site: same-origin/cross-site instead of `none`). A raw automated
# navigate sends NEITHER: empty Referer + Sec-Fetch-Site: none on a deep link is
# a textbook "arrived by automation" signature (confirmed live against a header-
# echo endpoint). `nav` now closes that gap automatically, zero operator
# friction, via compute_referer() below:
#   1. explicit 2nd arg  -> used verbatim (you know the real chain).
#   2. else the tab's LIVE current URL (location.href) if it's a real http(s)
#      page and not the same URL -> mimics clicking a link on the page you are
#      actually on (the common listing -> posting hop).
#   3. else cold entry to a DEEP link (has a path/query) -> https://www.google.com/
#      (arriving at a posting with no history looks like a search-result click).
#   4. else (bare homepage, no history) -> no Referer (typing a domain IS normal).
# camofox /navigate forwards `referer` to Playwright's page.goto(url,{referer});
# Firefox then derives the correct Sec-Fetch-Site from it. Mirror of
# browser_camofox.py's camofox_navigate -- keep in sync.
# Env overrides (testing only): CFX_NO_PACING=1, CFX_NO_KEYBOARD_TYPE=1,
# CFX_NO_REFERER=1.
#
# IMPORTANT — Cloudflare Turnstile / verification widgets can open as a real
# POPUP TAB, not an iframe on the current page (confirmed on Workable's
# apply.workable.com flow: challenges.cloudflare.com/.../turnstile/... opened
# in a brand new tab). Camofox registers it as a managed tab automatically,
# but every action above only ever touches CFX_TAB -- if a CAPTCHA is expected
# but `snap`/`shot` on the current tab shows nothing unusual, run `find-popup`
# BEFORE assuming the bot can't see it or escalating to the user. If a popup
# is found, switch CFX_TAB to its tabId, solve it there, then switch CFX_TAB
# back to the original tab (popups like Turnstile typically self-close on
# success -- a subsequent action on a closed tabId will 404, which just means
# it passed; switch back to the original CFX_TAB and continue).
#
# Env overrides:
#   CFX_KEY  - camofox bearer token (CAMOFOX_ACCESS_KEY). Defaults to the value
#              wired into ~/.hermes/.env / config.yaml (see camofox-browser skill).
#   CFX_TAB  - tab ID to operate on (from POST /tabs). Required — set this after
#              opening a tab for the site you're driving.
#   CFX_USER - Hermes camofox user_id (config.yaml browser.camofox.user_id).
#
# See ../../../references/... (job-application skill root) for the camofox auth
# model and the browser-automation/camofox-browser skill for how these values
# are wired into Hermes.

export PATH=/usr/bin:/bin:/usr/local/bin:$PATH

# record-captcha-fail/check-cooldown are local file operations -- they don't
# touch camofox at all, so they must NOT require CFX_KEY/CFX_TAB below (a
# domain cooldown check often needs to happen BEFORE a tab even exists).
COOLDOWN_FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)/captcha-cooldown.csv"
COOLDOWN_LOCK="${COOLDOWN_FILE}.lock"
case "$1" in
  record-captcha-fail|check-cooldown)
    :  # handled in the main case statement below, after arg validation
    ;;
  open-tab|list-tabs|find-popup)
    # These actions create/enumerate tabs rather than act on an existing
    # CFX_TAB, so only CFX_KEY is required here -- CFX_TAB doesn't exist yet
    # on a fresh session. (Bug found 2026-07-12: the blanket CFX_TAB check
    # below made `open-tab` impossible to call before a tab existed at all,
    # which is exactly when you need it.)
    : "${CFX_KEY:?Set CFX_KEY to the CAMOFOX_ACCESS_KEY bearer token}"
    ;;
  close-tab)
    # Closes CFX_TAB by default, but accepts an explicit tabId ($2) so you can
    # reap a solved-Turnstile popup or any stray tab without CFX_TAB being set.
    # Require CFX_TAB only when no explicit tabId was given.
    : "${CFX_KEY:?Set CFX_KEY to the CAMOFOX_ACCESS_KEY bearer token}"
    if [ -z "${2:-}" ]; then : "${CFX_TAB:?Set CFX_TAB, or pass a tabId: cfx.sh close-tab <tabId>}"; fi
    ;;
  *)
    : "${CFX_KEY:?Set CFX_KEY to the CAMOFOX_ACCESS_KEY bearer token}"
    : "${CFX_TAB:?Set CFX_TAB to the target tab ID (from POST /tabs)}"
    ;;
esac
KEY="${CFX_KEY:-}"
TAB="${CFX_TAB:-}"
UID_="${CFX_USER:-nasirjones}"
U="http://localhost:9377"
A="Authorization: Bearer $KEY"

# Randomized pre-action delay so page-affecting actions (click/type/press/
# scroll/nav/eval) don't land at a mechanical, evenly-spaced cadence. Root
# cause of a real Turnstile failure on Workable: 11 clicks logged ~2-3s apart
# almost to the second -- a textbook bot signature that Cloudflare's
# behavioral scoring on the *whole session* picks up on, independent of how
# clean any single click itself is. Base pause + occasional longer "reading"
# pause, mimicking a human actually looking at the page between actions.
# Set CFX_NO_PACING=1 to disable (e.g. for tight test loops against our own
# infra where there's no anti-bot scoring to worry about).
human_pause() {
  [ -n "${CFX_NO_PACING:-}" ] && return 0
  local ms=$(( (RANDOM % 2200) + 700 ))    # 0.7s - 2.9s baseline
  if (( RANDOM % 6 == 0 )); then           # ~1 in 6 actions: longer "thinking" pause
    ms=$(( ms + (RANDOM % 4000) + 2000 ))  # + 2.0s - 6.0s extra
  fi
  sleep "$(awk -v ms="$ms" 'BEGIN{printf "%.2f", ms/1000}')"
}

# Fires one real, trusted wheel-scroll of `amount` px in `dir`, broken into
# several smaller ticks -- see the `scroll` action below for why. Shared by
# `scroll` and orientation_pause's idle micro-scroll.
scroll_chunked() {
  local dir="$1" remaining="$2" last_resp=""
  while [ "$remaining" -gt 0 ]; do
    local chunk=$(( (RANDOM % 151) + 100 ))
    [ "$chunk" -gt "$remaining" ] && chunk=$remaining
    last_resp=$(curl -s -X POST -H "$A" -H "Content-Type: application/json" \
      -d "{\"userId\":\"$UID_\",\"direction\":\"$dir\",\"amount\":$chunk}" "$U/tabs/$TAB/scroll")
    remaining=$(( remaining - chunk ))
    [ "$remaining" -gt 0 ] && sleep "$(awk -v r=$RANDOM 'BEGIN{printf "%.2f", 0.04 + (r % 50) / 1000}')"
  done
  echo "$last_resp"
}

# Distinct, longer dwell after a FRESH page load, before the first
# subsequent action -- orienting on a brand new page measurably takes a
# person longer than moving between two fields already on screen. This is
# layered on TOP of nav's own human_pause (that one covers "deciding to
# navigate"; this one covers "reading the page that just loaded"). Mirror in
# browser_camofox.py's camofox_navigate -- keep both in sync.
#
# Partway through the dwell, does ONE of: a small idle scroll-down-then-
# back-up (80-200px, real trusted wheel events), or an idle mouse hover to a
# rough mid-page point (real trusted page.mouse.move via the /hover
# endpoint) -- or nothing. Two independent signal channels for "a human
# actually poked at this page" between actions. The /hover call is wrapped
# to fail silently (>/dev/null 2>&1) so it can never break the pause.
# Skipped entirely if CFX_NO_IDLE_SCROLL/CFX_NO_IDLE_HOVER is set, or pacing
# is disabled.
orientation_pause() {
  [ -n "${CFX_NO_PACING:-}" ] && return 0
  local roll=$(( RANDOM % 100 ))
  if [ -z "${CFX_NO_IDLE_SCROLL:-}" ] && [ -n "${TAB:-}" ] && [ "$roll" -lt 35 ]; then
    local amt=$(( (RANDOM % 121) + 80 ))  # 80-200px
    scroll_chunked down "$amt" >/dev/null
    sleep "$(awk -v r=$RANDOM 'BEGIN{printf "%.2f", 0.3 + (r % 500) / 1000}')"
    scroll_chunked up "$amt" >/dev/null
  elif [ -z "${CFX_NO_IDLE_HOVER:-}" ] && [ -n "${TAB:-}" ] && [ "$roll" -lt 60 ]; then
    local hx=$(( (RANDOM % 500) + 400 ))   # rough mid-page point, comfortably
    local hy=$(( (RANDOM % 300) + 300 ))   # inside any plausible viewport size
    curl -s -X POST -H "$A" -H "Content-Type: application/json" \
      -d "{\"userId\":\"$UID_\",\"x\":$hx,\"y\":$hy}" "$U/tabs/$TAB/hover" >/dev/null 2>&1
  fi
  sleep "$(awk -v r=$RANDOM 'BEGIN{printf "%.2f", 2.5 + (r % 3500) / 1000}')"  # 2.5s - 6.0s
}

# JSON-encode an arbitrary string safely (URLs/referers can contain characters
# that would break naive "\"$x\"" interpolation). Prints a quoted JSON string.
jsonstr() { python3 -c "import json,sys;print(json.dumps(sys.argv[1]))" "$1"; }

# Encode a whole request body of STRING fields in ONE python3 (B.1) — collapses the
# per-string jsonstr forks (click/press/click-selector/click-frame/eval-frame each
# forked python3 2-3×; on this low-power box each cold interpreter is ~50-100ms).
# Args are "key=value" pairs; value may itself contain '=' (only the FIRST '=' splits).
# Emits a compact object (separators without spaces) — same bytes the hand-built
# "{\"k\":$(jsonstr ..)}" produced, so the wire payload is unchanged.
jsonbody() {
  python3 -c '
import json, sys
obj = {}
for a in sys.argv[1:]:
    k, _, v = a.partition("=")
    obj[k] = v
sys.stdout.write(json.dumps(obj, separators=(",", ":")))
' "$@"
}

# Read the tab's LIVE current URL (location.href) without a human_pause -- this
# is a passive read (JS in page context, no input gesture / behavioral
# telemetry), used only to source a realistic Referer for the next nav. Prints
# empty string on any failure so callers can fall back gracefully.
tab_current_url() {
  curl -s -X POST -H "$A" -H "Content-Type: application/json" \
    -d "{\"userId\":\"$UID_\",\"expression\":\"location.href\"}" "$U/tabs/$TAB/evaluate" 2>/dev/null \
    | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    r = d.get('result') if isinstance(d, dict) else None
    print(r if isinstance(r, str) and (r.startswith('http://') or r.startswith('https://')) else '')
except Exception:
    print('')
" 2>/dev/null
}

# Decide the Referer for a nav (see the "Referer chains" note in the header).
# Args: <target_url> <explicit_referer> <current_url>. Prints the referer to
# send, or empty string for "send no Referer" (a genuinely refererless nav).
compute_referer() {
  python3 -c "
import sys
from urllib.parse import urlparse
target, explicit, cur = (sys.argv[1] if len(sys.argv) > 1 else ''), (sys.argv[2] if len(sys.argv) > 2 else ''), (sys.argv[3] if len(sys.argv) > 3 else '')
def real(u): return u.startswith('http://') or u.startswith('https://')
if explicit:
    print(explicit); sys.exit()
if real(cur) and cur.rstrip('/') != target.rstrip('/'):
    print(cur); sys.exit()   # genuine 'came from the page I'm on' chain
try:
    p = urlparse(target)
    deep = (p.path not in ('', '/')) or bool(p.query)
except Exception:
    deep = False
print('https://www.google.com/' if deep else '')  # deep cold-entry looks like a search click
" "$1" "$2" "$3"
}

# --- CAPTCHA-failure cooldown tracker ---------------------------------------
# Turns the "don't immediately retry a Turnstile-failed posting" rule (see
# SKILL.md) into something enforced, not just remembered. Shared plain-CSV
# file (no header row; domain,last_failure_iso,failure_count) so it works
# from both this script (Claude Code path) and browser_camofox.py's
# record_captcha_failure/captcha_cooldown_status (Hermes path) -- flock is a
# kernel-level advisory lock, interoperable across bash and Python on the
# same file regardless of which side wrote it. Backoff is exponential and
# capped: 1st failure -> 1h, 2nd -> 2h, 3rd -> 4h ... capped at 24h.
# (COOLDOWN_FILE/COOLDOWN_LOCK are set near the top of the file, before the
# CFX_KEY/CFX_TAB requirement, since these two actions need neither.)

case "$1" in
  snap)
    curl -s -H "$A" "$U/tabs/$TAB/snapshot?userId=$UID_" \
      | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('snapshot') or json.dumps(d))"
    ;;
  click)
    human_pause
    curl -s -X POST -H "$A" -H "Content-Type: application/json" \
      -d "$(jsonbody "userId=$UID_" "ref=$2")" "$U/tabs/$TAB/click"
    ;;
  type)
    human_pause
    # Short fields (logins, names, single-line answers) get real
    # character-by-character keyboard events with human-ish per-key jitter
    # instead of an instant value-set -- camofox's /type supports this via
    # mode=keyboard. Long free text (cover letters etc.) stays as the
    # instant mode=fill default: it mirrors a human pasting in prepared
    # content -- common and unremarkable -- rather than spending minutes
    # typing an essay one character at a time. Mirror of the same logic in
    # browser_camofox.py's camofox_type -- keep both in sync.
    # B.1: build the whole body (incl. the optional keyboard mode/delay) in ONE python3
    # instead of three jsonstr forks. Byte-compatible with the old hand-built body.
    kbmode=0; delay_ms=0
    if [ -z "${CFX_NO_KEYBOARD_TYPE:-}" ] && [ "${#3}" -le 70 ]; then
      kbmode=1; delay_ms=$(( (RANDOM % 71) + 45 ))
    fi
    body="$(python3 -c '
import json, sys
uid, ref, text, kb, delay = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4] == "1", int(sys.argv[5])
o = {"userId": uid, "ref": ref, "text": text}
if kb:
    o["mode"] = "keyboard"; o["delay"] = delay
sys.stdout.write(json.dumps(o, separators=(",", ":")))
' "$UID_" "$2" "$3" "$kbmode" "$delay_ms")"
    curl -s -X POST -H "$A" -H "Content-Type: application/json" \
      -d "$body" "$U/tabs/$TAB/type"
    ;;
  press)
    human_pause
    curl -s -X POST -H "$A" -H "Content-Type: application/json" \
      -d "$(jsonbody "userId=$UID_" "key=$2")" "$U/tabs/$TAB/press"
    ;;
    # Derive a realistic Referer BEFORE navigating (see the "Referer chains" note in
    # the header). The current-URL read happens before human_pause so the pacing delay
    # still lands right before the actual navigate. B.1: collapse the ~5 python3 forks
    # (tab_current_url parse + compute_referer + 3× jsonstr) into ONE — the current-URL
    # read is piped straight into a single python3 that parses location.href, computes
    # the referer (logic identical to compute_referer), and emits the final body.
  nav)
    if [ -n "${CFX_NO_REFERER:-}" ]; then
      human_pause
      body="$(jsonbody "userId=$UID_" "url=$2")"
    else
      curraw="$(curl -s -X POST -H "$A" -H "Content-Type: application/json" \
        -d "{\"userId\":\"$UID_\",\"expression\":\"location.href\"}" "$U/tabs/$TAB/evaluate" 2>/dev/null)"
      human_pause
      body="$(printf '%s' "$curraw" | python3 -c '
import json, sys
from urllib.parse import urlparse
uid, target, explicit = sys.argv[1], sys.argv[2], (sys.argv[3] if len(sys.argv) > 3 else "")
def real(u): return u.startswith("http://") or u.startswith("https://")
cur = ""
try:
    d = json.load(sys.stdin)
    r = d.get("result") if isinstance(d, dict) else None
    if isinstance(r, str) and real(r):
        cur = r
except Exception:
    cur = ""
if explicit:
    ref = explicit
elif real(cur) and cur.rstrip("/") != target.rstrip("/"):
    ref = cur
else:
    try:
        p = urlparse(target); deep = (p.path not in ("", "/")) or bool(p.query)
    except Exception:
        deep = False
    ref = "https://www.google.com/" if deep else ""
o = {"userId": uid, "url": target}
if ref:
    o["referer"] = ref
sys.stdout.write(json.dumps(o, separators=(",", ":")))
' "$UID_" "$2" "${3:-}")"
    fi
    curl -s -X POST -H "$A" -H "Content-Type: application/json" -d "$body" "$U/tabs/$TAB/navigate"
    orientation_pause
    ;;
  scroll)
    human_pause
    # Break one big scroll into several smaller wheel ticks with tiny gaps --
    # a real mouse wheel/trackpad never delivers one atomic 800px delta, it's
    # several ~100-250px ticks over a few hundred ms. camofox's /scroll does
    # exactly one wheel event per request, so the chunking happens in
    # scroll_chunked() (defined above, also used by orientation_pause's idle
    # scroll). Mirror of browser_camofox.py's camofox_scroll -- keep in sync.
    dir="${2:-down}"
    amount="${3:-800}"
    if [ -n "${CFX_NO_PACING:-}" ]; then
      curl -s -X POST -H "$A" -H "Content-Type: application/json" \
        -d "{\"userId\":\"$UID_\",\"direction\":\"$dir\",\"amount\":$amount}" "$U/tabs/$TAB/scroll"
    else
      scroll_chunked "$dir" "$amount"
    fi
    ;;
  shot)
    curl -s -H "$A" "$U/tabs/$TAB/screenshot?userId=$UID_" -o "${2:-/tmp/cfx-shot.png}"
    echo "saved: ${2:-/tmp/cfx-shot.png}"
    ;;
  eval)
    human_pause
    curl -s -X POST -H "$A" -H "Content-Type: application/json" \
      -d "{\"userId\":\"$UID_\",\"expression\":$(python3 -c "import json,sys;print(json.dumps(sys.argv[1]))" "$2")}" \
      "$U/tabs/$TAB/evaluate"
    ;;
  eval-frame)
    # Evaluate JS inside a cross-origin iframe's OWN document -- ground truth
    # instead of inference. Built for reCAPTCHA v2: read #recaptcha-anchor's
    # real aria-checked state directly, e.g.
    #   cfx.sh eval-frame 'iframe[src*="recaptcha/api2/anchor"]' \
    #     "document.querySelector('#recaptcha-anchor').getAttribute('aria-checked')"
    # Passive read, no human_pause (generates no input telemetry).
    curl -s -X POST -H "$A" -H "Content-Type: application/json" \
      -d "$(jsonbody "userId=$UID_" "frameSelector=$2" "expression=$3")" \
      "$U/tabs/$TAB/eval-frame"
    ;;
  click-selector)
    # CSS-selector fallback click — needed for components (react-select etc.)
    # that don't expose an a11y-tree ref for their option list. Selectors very
    # commonly contain double quotes (attribute selectors like
    # input[name="foo"], iframe[src*="bar"]) so the body MUST be built with
    # jsonstr, not raw "\"$2\"" interpolation which produces invalid JSON and a
    # silent 400 for exactly those selectors (matches click-frame's handling).
    human_pause
    curl -s -X POST -H "$A" -H "Content-Type: application/json" \
      -d "$(jsonbody "userId=$UID_" "selector=$2")" "$U/tabs/$TAB/click"
    ;;
  click-frame)
    # Click an element INSIDE an iframe (cross-origin OK): <frameSelector> <selector>.
    # This is how you click a reCAPTCHA v2 anchor checkbox:
    #   cfx.sh click-frame 'iframe[src*="recaptcha/api2/anchor"]' '#recaptcha-anchor'
    # Uses server.js's frameLocator support (Playwright pierces cross-origin
    # frames natively).
    human_pause
    curl -s -X POST -H "$A" -H "Content-Type: application/json" \
      -d "$(jsonbody "userId=$UID_" "frameSelector=$2" "selector=$3")" \
      "$U/tabs/$TAB/click"
    ;;
  click-xy)
    # Trusted mouse click at page coordinates <x> <y> (no selectable element
    # needed) -- for reCAPTCHA image-challenge tiles or canvas widgets: get each
    # tile's box from a screenshot + the VL model, then click its centre here.
    # Real interpolated movement + held press (server.js).
    human_pause
    curl -s -X POST -H "$A" -H "Content-Type: application/json" \
      -d "{\"userId\":$(jsonstr "$UID_"),\"x\":$2,\"y\":$3}" "$U/tabs/$TAB/click"
    ;;
  open-tab)
    # Open a fresh tab. Prints the new tabId — export it as CFX_TAB.
    #
    # NOTE on viewport diversity: this used to also rotate the new tab's
    # viewport across a list of real-world resolutions via /viewport. REMOVED
    # after live-testing proved it silently never worked: Playwright's
    # page.setViewportSize() on an already-open page is a known-unreliable
    # operation for headed Firefox (confirmed live 2026-07-12 -- the call
    # returned {"ok":true} and window.innerWidth/innerHeight never actually
    # changed). This deployment always runs headed (VNC/virtual_display is
    # part of the whole point of this project), so that call would NEVER
    # have worked here, ever -- keeping it around would just be dead code
    # that always silently fails (see SKILL.md's "dead scripts are worse
    # than no scripts" rule). /tabs/:tabId/viewport in server.js now reports
    # an honest `verified` field for any other caller relying on it.
    #
    # The actual good news: viewport diversity across tabs doesn't need a
    # fix at all. Camoufox generates a random (but internally consistent)
    # window+screen fingerprint automatically at every browser launch unless
    # you explicitly pass a fixed `window: [w,h]` to launchOptions (confirmed
    # by reading camoufox-js's own source/types inside the container,
    # node_modules/camoufox-js/dist/utils.d.ts) -- we never do, so this
    # already happens for free, at the browser-launch granularity (every
    # restart gets a fresh size), not per-tab. Per-tab-within-one-launch
    # diversity was the part that was actually broken and unfixable at this
    # layer; per-launch diversity was never broken in the first place.
    curl -s -X POST -H "$A" -H "Content-Type: application/json" \
      -d "{\"userId\":\"$UID_\",\"sessionKey\":\"${2:-job-apply}\",\"url\":\"$3\"}" "$U/tabs"
    ;;
  list-tabs)
    curl -s -H "$A" "$U/tabs?userId=$UID_"
    ;;
  find-popup)
    # Surface any tab besides CFX_TAB -- e.g. a Cloudflare Turnstile /
    # reCAPTCHA / hCaptcha challenge that opened as its own popup window
    # instead of an iframe on the current page. See note at top of file.
    curl -s -H "$A" "$U/tabs?userId=$UID_" \
      | python3 -c "
import sys, json
d = json.load(sys.stdin)
tabs = d.get('tabs') if isinstance(d, dict) else d
cur = '$TAB'
others = [t for t in (tabs or []) if isinstance(t, dict) and t.get('tabId') != cur]
if not others:
    print('no popup tabs found')
else:
    for t in others:
        print(f\"{t.get('tabId')}\t{t.get('url')}\")
"
    ;;
  close-tab)
    # Free the tab's memory once you're finished with a posting. Teardown, not
    # a user gesture, so NO human_pause (it generates no behavioral telemetry).
    # DELETE is idempotent server-side (ok:true even if the tab is already
    # gone), so double-closing or reaping a self-closed Turnstile popup is safe.
    target="${2:-$TAB}"
    curl -s -X DELETE -H "$A" "$U/tabs/$target?userId=$UID_"
    ;;
  record-captcha-fail)
    domain="$2"
    if [ -z "$domain" ]; then echo "Usage: cfx.sh record-captcha-fail <domain>" >&2; exit 1; fi
    mkdir -p "$(dirname "$COOLDOWN_FILE")" 2>/dev/null
    touch "$COOLDOWN_FILE"
    (
      flock -w 5 200 || { echo "lock timeout" >&2; exit 1; }
      # Match the domain on an EXACT first-field basis (awk $1==d), NOT
      # grep "^$domain," -- a domain is full of '.' which grep treats as
      # "any char", so grep would match/rewrite the wrong row (and a domain
      # with other regex metacharacters would misbehave outright). awk with a
      # -v string variable does a literal compare and needs no escaping.
      prev_count=$(awk -F',' -v d="$domain" '$1==d{c=$3} END{print c+0}' "$COOLDOWN_FILE" 2>/dev/null)
      prev_count=${prev_count:-0}
      new_count=$((prev_count + 1))
      now=$(date -Iseconds)
      awk -F',' -v d="$domain" '$1!=d' "$COOLDOWN_FILE" > "${COOLDOWN_FILE}.tmp" 2>/dev/null || true
      mv "${COOLDOWN_FILE}.tmp" "$COOLDOWN_FILE"
      echo "$domain,$now,$new_count" >> "$COOLDOWN_FILE"
      echo "recorded: $domain (failure #$new_count)"
    ) 200>"$COOLDOWN_LOCK"
    ;;
  check-cooldown)
    domain="$2"
    if [ -z "$domain" ]; then echo "Usage: cfx.sh check-cooldown <domain>" >&2; exit 1; fi
    if [ ! -f "$COOLDOWN_FILE" ]; then echo "clear"; exit 0; fi
    # Exact first-field match (see record-captcha-fail for why grep "^$domain,"
    # is wrong for dotted domains). Take the LAST matching row.
    row=$(awk -F',' -v d="$domain" '$1==d{r=$0} END{print r}' "$COOLDOWN_FILE" 2>/dev/null)
    if [ -z "$row" ]; then echo "clear"; exit 0; fi
    # Pass the row as argv (NOT interpolated into the source) so a stray quote
    # or other shell/python metacharacter in the file can't break or inject
    # into the script. Also guard a malformed row instead of tracebacking.
    python3 -c '
import datetime, sys
parts = sys.argv[1].split(",")
if len(parts) < 3:
    print("clear"); sys.exit()
try:
    last = datetime.datetime.fromisoformat(parts[1])
    count = int(parts[2])
except (ValueError, IndexError):
    print("clear"); sys.exit()
cooldown_hours = min(24, 2 ** (count - 1))
now = datetime.datetime.now(last.tzinfo) if last.tzinfo else datetime.datetime.now()
elapsed_hours = (now - last).total_seconds() / 3600
if elapsed_hours >= cooldown_hours:
    print("clear")
else:
    remaining = cooldown_hours - elapsed_hours
    print(f"cooldown active: {remaining:.1f}h remaining (failure #{count}, {cooldown_hours}h backoff)")
' "$row"
    ;;
  *)
    echo "Usage: cfx.sh <snap|click|type|press|nav|scroll|shot|eval|eval-frame|click-selector|click-frame|click-xy|open-tab|close-tab|list-tabs|find-popup|record-captcha-fail|check-cooldown> [args...]" >&2
    exit 1
    ;;
esac
