# Camofox concurrent-tab wedge & harness-script gotchas

## The wedge (headline lesson — costs the most iterations)
camofox's REST backend WEDGES under concurrent tab load. Observed 2026-07-14:
launching 5 background sourcing scripts that each opened their own tab drove the
engine to ~10 live tabs; POST /tabs then returned
{"error":"Internal server error"} / open_tab: tab not created (last response {}),
and every in-flight feed.py / evaluate started dying with HTTP 500 or
"browser was restarted (410)". Reusing ONE live tab worked fine — that is how the
432-candidate CSJ read and the 25-candidate LinkedIn alternate-query reads succeeded.

RULE: serialize ALL browser work on a single reused tab. Never run two or more
camofox-driving processes in parallel. One sourcing script at a time, one apply at
a time. If you split work across terminal calls, each call must reuse the SAME
CFX_TAB (re-navigate that one tab per board) — NOT call fresh_tab() separately.
The login session lives in the browser profile, not the tab, so reusing one tab
keeps LinkedIn / Indeed / WTTJ logged in across boards.

### Recovery when wedged
- GET /tabs to find survivors; if none, fresh_tab() once (retry loop, back off
  ~8s between tries). Do NOT pile on more POST /tabs calls — that is what wedged it.
- A single reused tab handles LinkedIn + Indeed + CSJ + Hackney + WTTJ sequentially.
- Symptoms of the wedge: new POST /tabs -> Internal server error; in-flight
  feed.py -> "ERROR nav: ... HTTP 500" or "410 Tab no longer exists (browser was
  restarted)". Stop opening tabs, reuse the one survivor, continue.
- **Self-serviceable engine restart — VERIFIED `cfx.restart_engine()` (NOPASSWD sudoers rule
  exists on this host; NO user permission needed).** When the wedge persists across a
  fresh tab + retries, call `cfx.restart_engine(health_timeout_s=90)` — it runs
  `sudo -n docker compose -f compose.yaml restart
  camofox-browser` (exact command in `cfx.py` `_RESTART_CMD`, overridable via
  `CFX_RESTART_CMD`) and polls `/health` until `browserConnected`. It drops every open
  tab (real restart) but **login persists** (cookies live in the camoufox profile, not
  the tab). VERIFIED 2026-07-15: a CSJ TAL-eform `evaluate` wedge that survived fresh-tab
  + retries cleared completely after `restart_engine()` — minimal evaluates + clicks
  worked again and drove an application to the Eligibility page. Do NOT tell the user
  "restart needs your permission" — it does not. Only fall back to asking the user if
  `restart_engine()` returns False (sudoers rule absent on this host).

## Harness-script parsing gotchas (Python that shells out to feed.py)
- feed.py prints a human line
  ("21 FRESH jobs (4 already in application-tracker.csv filtered out). Screen titles
  before opening...") BEFORE the JSON array on stdout. json.loads(p.stdout) fails.
  Parse the first [ ... matching ] block, or scan lines for the one that starts
  with [ and json.loads that line.
- Raw GET /tabs?userId=... returns {"running":true,"tabs":[...]} — NOT a bare list.
  json.load(...)[0] raises KeyError: 0. Use d.get("tabs", []) when the payload is a
  dict; the cfx.py list-tabs CLI returns a bare list, so don't mix the two.
- feed.py returns [] (with an EXHAUSTED / cooldown message) when a query is drained
  — that is a real "0 fresh", not a parse failure. Don't retry the same query; it is
  on cooldown. Break cooldown with --force only against a DIFFERENT query (wider
  title vocab), never the identical bundled one.

## Stale-key trap (bootstrap)
The committed .jobenv may carry a SHORT / WRONG CFX_KEY. Symptom: GET /health and
GET /tabs succeed (read-only) but every POST (/tabs, /navigate) returns
HTTP 401 Unauthorized. The real 64-char bearer token lives in .jobenv.run.
source .jobenv.run (or copy its CFX_KEY into .jobenv) before any cfx / feed call.
See references/hermes-bootstrap.md.
