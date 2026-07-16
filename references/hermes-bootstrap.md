# Hermes bootstrap — terminal-driven cfx.py / cfx.sh (env + tab setup)

Detailed session-setup mechanics for the **Hermes** path. This is one-time
per-session setup, so it lives here rather than in `SKILL.md`'s per-turn context
(SKILL.md keeps only a short pointer). The Claude Code path gets `CFX_*` from a
PostToolUse hook and needs none of this.

The **Hermes path has no hook**, so you must bootstrap the env yourself each
session before any `cfx.sh` / `cfx.py` / `feed.py` call — and the env does NOT
persist between separate tool calls unless you re-`source` it. When driving
camofox from the Hermes terminal you use the `cfx.py`/`cfx.sh` path — **never**
the native `browser_*` tools (incomplete subset, see
`sites/_common/CAPABILITY-GAPS.md`).

1. **Source the credentials.** The skill root ships `.jobenv`
   (`export CFX_KEY=…; CFX_USER=nasirjones; CFX_URL=http://localhost:9377; CFX_TAB=""`).
   `source` it — `CFX_TAB` is empty; you create the tab next.

   ⚠️ **STALE-KEY TRAP (2026-07-14, cost a full wasted sourcing pass).** `.jobenv`'s
   `CFX_KEY` is the SHORT 36-char UUID form and is **stale/wrong**. The live
   64-char bearer token lives in **`.jobenv.run`** (same dir). A GET against
   `/health` SUCCEEDS with the short key (so a naive health-check passes and fools
   you), but every POST (`/tabs` open, `/navigate`) returns `401 Unauthorized`.
   **Always `source .jobenv.run`, not `.jobenv`.** If a POST hits `401` right after
   a clean `200` on `/health`, the key is the first suspect — overwrite `.jobenv`
   with the `.jobenv.run` contents and re-source.

2. **Open a tab against the `job-apply` session** (this profile holds the
   LinkedIn/WTTJ logged-in cookies — a fresh `sessionKey` logs you out):
   ```bash
   RESP=$(curl -s -X POST -H "Authorization: Bearer $CFX_KEY" \
     -H "Content-Type: application/json" \
     -d '{"userId":"nasirjones","sessionKey":"job-apply","url":""}' \
     http://localhost:9377/tabs)
   export CFX_TAB=$(echo "$RESP" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['tabId'])")
   ```
   Persist all four `export`s (incl. the new `CFX_TAB`) to a file you `source` before
   every terminal call this run. **The camofox browser can restart between runs** (or even
   mid-run) — the previously-persisted `CFX_TAB` then dies with HTTP 410
   `Tab no longer exists (browser was restarted)`. When that happens, list live tabs
   (`GET /tabs?userId=nasirjones` via curl, or `cfx.py list-tabs`); if none, open a fresh
   one (step 2 above) and **re-point your persisted env file's `CFX_TAB`** before
   continuing. Re-check `GET /tabs` first whenever a `cfx` call 500s/410s unexpectedly.

   ⚠️ **`.jobenv.persist` CLOBBER TRAP (cost a wasted pass 2026-07-15).** Persisting with
   `echo "CFX_TAB=..." > .jobenv.persist` (single `>`-redirect) **wipes the file and
   deletes `CFX_KEY`** — every later `cfx.sh` call then dies with `CFX_KEY: Set CFX_KEY to
   the CAMOFOX_ACCESS_KEY bearer token`. **NEVER `>`-overwrite the persist file.** Always:
   (a) re-`source .jobenv.run` FIRST (it has the live `CFX_KEY`), then write a heredoc that
   includes BOTH `export CFX_KEY=...` and `export CFX_TAB=...`; or (b) use `>>` to append just
   the `CFX_TAB` line to the existing persisted file. The persist file must always contain
   `CFX_KEY` + `CFX_TAB` together. If you see the `Set CFX_KEY` error, the fix is
   `source .jobenv.run` then re-persist both vars.

   ⚠️ **Two different 410s — diagnose before acting.** The per-tab 410 above has
   `browserRunning:true` and a single fresh `ensure-tab` works. If instead `ensure-tab`
   fails EVERY time with `open_tab: tab not created (last response {})` and `/health`
   shows `browserRunning:false`, the **browser backend itself crashed** — a one-time
   `docker compose restart camofox-browser` is the fix, NOT a retry-loop on `ensure-tab`.
   Full diagnostic + fix: **`references/camofox-backend-recovery.md`**.
3. **Verify.** `curl -fsS -H "Authorization: Bearer $CFX_KEY" http://localhost:9377/health`
   → `browserConnected:true`. `python3 sites/_common/scripts/cfx.py list-tabs` should
   show your new tab.
4. **Login-check first** — one call: `python3 sites/_common/scripts/check_login.py`
   checks **all four boards** (LinkedIn, WTTJ, Indeed, SEEK) by default; pass specific
   boards (e.g. `check_login.py linkedin wttj`) for a faster subset. It navigates each,
   classifies `logged_in` / `wall` / `guest_ok` / `unknown`, prints per-board JSON + a
   summary, and **exits 11 if a login-REQUIRED board (LinkedIn/WTTJ) is WALLED** (hard
   stop — message the user via VNC per SKILL.md → Login walls, don't scrape logged-out).
   Guest boards (Indeed/SEEK) report login status too but a logged-out state there is
   `guest_ok`, not a stop. Uses the correct WTTJ **app** domain
   (`app.welcometothejungle.com`), not the marketing `www.` domain. ⚠️ NAVIGATES the tab
   once per board, so run it before sourcing (or on a scratch step), not mid-application.
