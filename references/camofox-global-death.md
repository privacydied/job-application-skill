# Camofox GLOBAL DEATH after long session (escalation, 2026-07-16)

Companion to `camofox-backend-recovery.md` (backend-down + DEGRADED-but-still-running)
and `camofox-open-tab-nav-pitfall.md` (the REAL root cause of the 2026-07-16
"global death" episode — read that first).

## ⚠️ CORRECTION (2026-07-16): the "global death" was a misdiagnosis
The episode diagnosed below was NOT a wedged node event loop. The blank renders
on Reed + TotalJobs were caused by **`open-tab "<url>"` auto-nav silently
failing** (see `camofox-open-tab-nav-pitfall.md`): tabs were created at
`about:blank` so every page looked empty, producing false "NO APPLY BUTTON" /
false "backend dead". The fix was `open-tab "about:blank"` + explicit `nav` — NOT
a container rebuild. ALSO: `cfx.restart_engine()`'s `sudo -n docker compose restart`
was **failing with "a password is required"** (no NOPASSWD sudoers rule), so no
real restart happened and the backend self-healed on its own. The `evaluate`
"timeouts" were the agent's own 120s wrapper on a tab whose page never loaded.
**Do NOT conclude "backend globally dead" from blank renders — verify the load
via explicit `nav` + `innerText.length` first.** Keep the timeout-hang signal
below as a LAST-RESORT genuine-death indicator, but it was NOT what happened here.

## Signal (genuine GLOBAL DEATH — distinct from the open-tab bug)
- `cfx.evaluate(...)` and `cfx.open_tab(...)` / `POST /tabs` **TIMED OUT at 120s** — no JSON envelope, `curl: (28) Operation timed out`. NOT the DEGRADED "tabs die within seconds but API answers" case, NOT a 500/empty, NOT the open-tab auto-nav blank (which returns `0|` FAST, not a hang).
- `/health` STILL returned `browserRunning:true` — so it *looks* alive.
- Even after a REAL container restart (see fix) + 30s cooldown, a known-good board (Reed) AND a curl-verified-reachable board (TotalJobs, HTTP 200) BOTH render empty DOM even via explicit `nav` (not just open-tab).

## Root cause (ONLY if the above genuine signal holds)
The node `server.js` event loop wedged on the tab route after a multi-hour session. `/health` polls but the tab endpoint is dead/hung. This is NOT fixed by in-process `restart_engine()` alone (confirm the `sudo -n` restart actually ran — if it says "a password is required", the restart did NOT happen) and NOT by opening more tabs / re-pointing `CFX_TAB` / re-`nav`.

## Fix (agent CANNOT do this alone — only if genuinely dead)
A real container rebuild from the host:
```bash
sudo -n docker compose -f compose.yaml restart camofox-browser
# if restart insufficient:
sudo -n docker compose -f compose.yaml down && up -d
```
Then the stability gate: open ONE tab → 5× `evaluate(document.title)` 2s apart; ALL must return clean before sourcing. If evaluates STILL hang/timeout after a confirmed restart, the container needs full rebuild/redeploy.

## Lesson for future sessions
1. **Blank render ≠ backend dead.** Rule out `open-tab` auto-nav failure FIRST (explicit `nav` + check `innerText.length>0`). The 2026-07-16 "death" was this bug, not a dead backend.
2. **Verify the restart actually ran.** `restart_engine()` returning "a password is required" = no restart happened. Don't assume it healed.
3. If you reach ~18+ passes and `evaluate` genuinely HANGS (real timeout, not `0|` fast-return), STOP hammering: the backend may be globally dead. State the data-scarcity ceiling + backend-death as TWO separate blockers and wait for infra recovery. Re-looping a dead backend wastes the whole session.

## NOT a "TotalJobs is blocked" false-negative
TotalJobs returned HTTP 200 + 76 listings via curl — it is reachable, NOT Cloudflare-walled. Its blank camofox render in the 2026-07-16 episode was the `open-tab` bug, NOT a site block. Verify reachability with `curl -s --max-time 25 -A "Mozilla/5.0" <url>` before concluding any board is "blocked". (TotalJobs apply itself DOES need an account — clicking Apply redirects to homepage when unauthenticated — but browsing works.)
