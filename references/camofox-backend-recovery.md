# Camofox browser-BACKEND-down recovery (distinct from a dead tab)

Companion to `sites/_common/CAPABILITY-GAPS.md` (cross-cutting endpoint faults) and
`references/hermes-bootstrap.md` (per-tab 410 recovery). This note covers the case
where the camofox **browser process itself** has crashed — REST server still up,
browser child dead.

## Signal (verified live 2026-07-14)

- Every `ensure-tab` / tab-create fails with:
  `ERROR: open_tab: tab not created (last response {})`
- Any live `nav` returns:
  `HTTP 410 Tab no longer exists (browser was restarted). Create a new tab.`
- BUT `curl -fsS -H "Authorization: Bearer $CFX_KEY" http://localhost:9377/health`
  is still reachable and shows `"browserRunning":false,"browserConnected":false,
  "activeTabs":0`.

This is **NOT** the ordinary single-dead-tab `410` (that case has
`browserRunning:true` and a single fresh `ensure-tab` succeeds immediately). Here
the browser child died — no `ensure-tab` will work until the backend is restarted.

## Diagnostic one-liner

```bash
curl -fsS -H "Authorization: Bearer $CFX_KEY" http://localhost:9377/health
# -> if browserRunning:false  => backend is down
```

Use the REAL `CFX_KEY` from `.jobenv`. A bare literal `***` bearer returns
`401 Unauthorized`, which masks the real diagnosis and looks like a separate fault.

## Fix (one time — do NOT retry-loop `ensure-tab`)

```bash
sudo -n docker compose -f compose.yaml restart camofox-browser
```

- `/etc/sudoers.d/camofox-restart` grants `<your-user>` NOPASSWD for exactly this command
  (+ `up -d`). If `sudo -n` prompts for a password, the grant isn't active on this
  host — escalate to the user.
- After restart, poll `/health` until `browserRunning:true` (3–6s), THEN open a tab.
- **Tell the user in the same turn** — an unexplained docker restart looks like
  thrash. One line is enough: "camofox browser backend had crashed
  (`browserRunning:false`), blocking all browsing; restarted it once, now up."
- One restart is sufficient; it stays stable afterward (verified: 372 vacancies
  crawled post-restart with no further tab loss). Do NOT keep re-running it.

## How it differs from the per-tab 410

| Case | `browserRunning` | `ensure-tab` outcome | Fix |
|---|---|---|---|
| Per-tab 410 (browser alive) | `true` | succeeds on first try | re-point `.runtab` CFX_TAB, continue |
| Backend down (this note) | `false` | fails every time | `docker compose restart camofox-browser` |

## ⚠️ DEGRADED-BUT-RUNNING state (NEW, 2026-07-14 — not covered above)

A distinct intermediate failure the backend-down note does NOT cover: `/health`
reports `browserRunning:true` (engine thinks it's fine), but **every tab created
dies within seconds**. Symptom signature observed live:

- `ensure_tab()` returns a tabId; `cfx.navigate(url)` even prints `nav ok`.
- The very next `cfx.evaluate(...)` (same call, ~1-3s later) returns
  `HTTP 404 Tab not found` for that same tabId → the whole `feed.py`/`jd.py` run
  dies with `EXIT=2`.
- Repeat across every tab you open; you never get a stable one. Health still says
  `browserRunning:true`, `consecutiveFailures:0`, low memory — so it does NOT look
  like the backend-down case above, and re-pointing `CFX_TAB` does nothing (the tab
  genuinely evaporates).

Root cause: browser child is in a wedged/leaking state that still answers `/health`
but cannot keep a tab alive. **It is NOT fixed by opening more tabs, waiting, or
re-pointing `CFX_TAB`** — those just burn sourcing passes (this session lost ~6
LinkedIn/Indeed feed attempts to it before diagnosing).

**Fix = the same restart as backend-down**, even though `browserRunning` is `true`:

```bash
sudo -n docker compose -f compose.yaml restart camofox-browser
```

**Mandatory stability gate AFTER restart (do not skip — this is what confirms the
fix and prevents re-wasting a pass):** open ONE tab, navigate to LinkedIn, then run
≥5 `cfx.evaluate("document.title")` calls with a 2s gap between each. Only trust the
tab — and only then start `feed.py` — if ALL evaluates return cleanly. Verified live:
post-restart the tab survived 6 consecutive evaluates and then crawled all 6 LinkedIn
bundles (78 candidates) + 6 Indeed bundles with zero tab loss. If evaluates still 404,
the backend restart did not take (poll `/health` until `browserRunning:true`, then
retry the stability gate).

One restart is sufficient; it stays stable afterward. Do NOT loop the restart.

## ⚠️ TAB-API WEDGE (NEW, 2026-07-14 — distinct from both above)

A third failure state seen live this session, **not** covered by backend-down or
DEGRADED: `/health` returns valid JSON (`browserRunning:true`, `activeTabs` ≤2,
`consecutiveFailures:0`), but the **tab-management API itself is hung**:

- `POST /tabs` (create) **hangs with no response** — `curl` times out at 15–20s
  (`curl: (28) Operation timed out … 0 bytes received`), no JSON envelope.
- `GET /tabs?userId=nasirjones` **hangs / returns empty** (the `list_tabs()` call
  `cfx.ensure_tab`/`open_tab` depend on — so they hang too, even though the engine
  is *technically* recoverable).
- `cfx.navigate` on an existing tab returns `HTTP 410 Tab no longer exists`.
- Occasionally a `POST /tabs` returns `400` (empty/about:blank URL rejected) or a
  successful `tabId` — i.e. it's **intermittent**, not permanently dead.

This is a deeper hang than DEGRADED (there, tabs die within seconds but the API
answers; here the API endpoint itself stops responding). It looks like the node
`server.js` event loop is wedged on the tab route while `/health` still polls.

**Fix = the same restart** (`docker compose restart camofox-browser`). But two
hard-won gotchas this session:

1. **The NOPASSWD sudoers grant is INTERMITTENT.** `/etc/sudoers.d/camofox-restart`
   grants `<your-user>` passwordless `docker compose restart camofox-browser` (per the
   backend-down note) — but live behavior was: it worked in some turns, then
   `sudo -n` started prompting `a password is required` in later turns (the grant
   had de-activated / reverted). When it prompts, you **cannot** restart, cannot
   kill the root-owned `server.js` without sudo, and cannot create tabs → the run
   is truly blocked. **Treat a `sudo -n` password prompt as a HARD STOP**: tell the
   user to either (a) run the restart themselves, (b) restore the NOPASSWD grant, or
   (c) grant sudo for the session. Do NOT loop on the wedge hoping it self-heals.

2. **Post-restart warmup exceeds the foreground cap.** After `restart`, the container
   reports "Started" but the tab API can need **60s+** before `POST /tabs` answers
   (observed: a `sleep 60` + health check blew the 60s tool timeout, and the first
   few `ensure_tab`/POST attempts still hung for ~30–60s before succeeding). Wait
   generously; don't conclude "restart failed" at 20s.

**Create-via-raw-POST workaround** (when `cfx.ensure_tab`/`open_tab` hang on the
`list_tabs()` GET but the create endpoint might still answer): call the POST
directly and parse the response, bypassing `list_tabs()`:

```bash
KEY=$(grep CFX_KEY .jobenv.run | cut -d"'" -f2)
RESP=$(timeout 20 curl -fsS -X POST -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d '{"userId":"nasirjones","listItemId":"job-apply","url":"https://www.linkedin.com/jobs/"}' \
  http://localhost:9377/tabs)
TAB=$(echo "$RESP" | python3 -c "import sys,json;print(json.load(sys.stdin).get('tabId',''))" 2>/dev/null)
# no blank/about:blank URL — it 400s; use a real https URL
# retry a few times; a 400 then a success is normal
```

Then patch `CFX_TAB` in `.jobenv.run` (see below) and verify with `cfx.current_url()`
before driving.

## Diagnostic decision tree (all three states)

```text
GET /health -> browserRunning:false ............ backend down     -> docker restart
GET /health -> true, but tabs 404 within secs .. DEGRADED (above) -> docker restart + stability gate
GET /health -> true, tab 404 once, reuse works . ordinary per-tab 410 -> re-point CFX_TAB, continue
```

## ⚠️ SELF-KILL TRAP when killing the pipeline (2026-07-15)
`pkill -f pipeline.py` / `pgrep -f <name>` match the **agent's own shell** (its
command line contains the string), so the kill signal lands on the shell itself →
the next tool call returns `exit_code: -15` (SIGTERM) with no output. Symptom:
unexplained `-15` right after a `pkill`/`pgrep -f`. **Fix:** kill by PID only
(`ps -eo pid,args | grep <name> | grep -v grep` → `kill <pid>`), or use the
proper `process(action='kill')` tool for background processes. Never `pkill -f`
a string that also appears in your own command line. (Same class: launching a
long job with `nohup … &` inside a Hermes `terminal` is rejected — use
`terminal(background=true)` instead, which tracks the PID and won't self-match.)

## ⚠️ `cfx.restart_engine()` (in-process self-restart) — post-restart DEAD-TAB dance (2026-07-15)

`cfx.restart_engine()` is the agent-self-service wrapper (NOPASSWD sudoers
`docker compose restart camofox-browser`, same effect as the backend-down note
above, but callable from a Python `cfx` import — no shell `sudo`). Use it when the
tab API wedges (HTTP 500 on `evaluate`/`type` on a heavy SPA like the MoJ wizard).

**The trap:** `restart_engine()` succeeds (`True`) but **invalidates the CURRENT
tab** — the next `nav`/`evaluate` on the old `CFX_TAB` returns
`HTTP 410 Tab no longer exists (browser was restarted). Create a new tab.` The
session/login also resets (MoJ/CSJ log you out — re-login). So after a restart you
MUST:

1. Create a fresh tab and capture its id — `cfx` has **no** `new_tab` attribute;
   use `cfx.open_tab(url)` (returns the new tabId):
   ```python
   import sys; sys.path.insert(0,'sites/_common/scripts'); import cfx
   TAB = cfx.open_tab('https://…')   # e.g. the MoJ/CSJ URL you need
   ```
2. Re-point the env: write `export CFX_TAB='<new id>'` into `.jobenv.run` and
   `source` it on the next terminal call (Hermes does not persist env between
   calls). `cfx._tab()` reads `CFX_TAB` from the env, so leaving the dead id in
   `.jobenv.run` makes every subsequent `cfx.evaluate`/`cfx.post` hit the 410 tab.
   ```bash
   echo "export CFX_TAB='$TAB'" > .jobenv.run
   ```
3. Re-login if the target session dropped (MoJ `username`/`password` from
   `ats-credentials.csv`; CSJ re-auth). Then resume.

**Do NOT** try to "reuse" the old tab id after a restart — it is gone (410).
Opening a fresh `open_tab` + rewriting `.jobenv.run` is the only recovery; the
restart-does-not-drop-tab assumption is false for `restart_engine()`.
Verified live 2026-07-15: after `restart_engine()` the prior tab 078b5fb9…
returned 410; `cfx.open_tab(...)` + `.jobenv.run` rewrite restored driving on
tab 7f608739… / 49605633….
