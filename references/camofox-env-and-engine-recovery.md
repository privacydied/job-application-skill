# Camofox env-file & engine recovery (beyond the tab wedge)

Two failure modes the shipped wedge/recovery notes don't cover. Found live
2026-07-18 during a job-application firing. Both recur every time the env files are
regenerated or the engine crashes — capture the FIX, not a "tool is broken" claim.

## 1. The empty-CFX_URL / CFX_USER override footgun

When `.jobenv.run` / `.jobenv.persist` contain literal empty exports
(`export CFX_URL=""` and `export CFX_USER=""`), they OVERRIDE the python `cfx`
module's sane defaults (`CFX_URL` -> `http://localhost:9377`,
`CFX_USER` -> `nasirjones`). Symptoms:

- `ValueError: unknown url type: '/tabs/<id>/evaluate'`  <- CFX_URL is empty
- `HTTP 400 userId is required`                          <- CFX_USER is empty

The shell `cfx.sh` wrapper sets these itself, so it masks the bug — but ANY python
script that `import cfx` and relies on module defaults breaks (feed.py, diagnose.py,
autofill.py, precheck piped through python, etc.).

**FIX (the correct persistence recipe):**
- Write ONLY `CFX_KEY` + `CFX_TAB` to the env files. Never write `CFX_URL` or
  `CFX_USER` — let them fall through to the module defaults.
- After `source .jobenv.run`, run `unset CFX_URL CFX_USER` before any python `cfx`
  call in that same shell.
- When reopening a tab via `cfx.ensure_tab(persist=True)`, capture the id from the
  FUNCTION RETURN, not from `os.environ['CFX_TAB']` inside the already-sourced shell
  (it still holds the dead id). Persist the *returned* id explicitly, e.g.:
  ```python
  import os, sys
  sys.path.insert(0, 'sites/_common/scripts')
  import cfx
  new = cfx.ensure_tab(persist=True)   # returns the live id
  body = 'export CFX_KEY="%s"\nexport CFX_TAB="%s"\n' % (os.environ.get("CFX_KEY",""), new)
  for fn in (".jobenv.run", ".jobenv.persist"):
      p = fn; tmp = p + ".tmp"
      open(tmp, "w").write(body); os.replace(tmp, p)
  ```
  Re-source, `unset CFX_URL CFX_USER`, then verify with `cfx.evaluate('1+1') == 2`.

## 2. Engine-level death (REST server down, not just a dead tab)

- A DEAD TAB -> HTTP 404 "Tab not found". Recoverable with `ensure_tab` / `ensure-tab`.
- A DEAD ENGINE -> `curl http://localhost:9377/health` returns NOTHING
  (Connection refused / unreachable). `ensure_tab` CANNOT fix this — there is no
  server to make a tab on.

**RECOVERY (prefer this over `cfx.py restart-engine`):**
The `camofox-vnc-watchdog.sh` at `/volume1/docker/playwright/` runs
`docker compose restart camofox-browser`. Either:
- wait ~25s for the watchdog to self-heal, OR
- trigger it directly: `cd /volume1/docker/playwright && docker compose restart camofox-browser`
  (requires docker-socket access; `docker ps` may say "permission denied" for the
  unprivileged user — the watchdog runs as root and still works).

`python3 sites/_common/scripts/cfx.py restart-engine` returned
`{"restarted_and_healthy": false}` in this session even though the watchdog/compose
path brought the engine back. **Prefer the watchdog/compose path.**

**After recovery (mandatory sequence):**
1. `curl -fsS http://localhost:9377/health` shows `browserConnected:true,
   activeTabs:0`.
2. Open a FRESH tab — every old tab id is gone. `cfx.ensure_tab(persist=True)`.
3. Re-persist env (recipe above), `unset CFX_URL CFX_USER`.
4. Re-login if needed: CSJ login persists in the browser *profile*, but a brand-new
   tab may land on the public homepage — re-run `python3 scripts/csj_login.py`
   (prints `LOGIN_OK` when "Jane Doe / Sign out" appears). applicationtrack
   login also persists in the profile; just re-navigate.
