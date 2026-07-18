# Camofox env-file & tab/engine recovery (2026-07-18)

Non-obvious failure modes seen driving the camofox backend from this skill, with the
exact recovery that worked. The shell wrapper `cfx.sh` hides some of these (it sets its
own base URL), which is why `bash cfx.sh eval '1+1'` can succeed while the python
`cfx.evaluate('1+1')` fails on the SAME backend — the bug is in env config, not camofox.

## 1. The env-file footgun (most common, silent)

A hand-written `.jobenv.run` / `.jobenv.persist` that contains `export CFX_URL=""`
or `export CFX_USER=""` **overrides the python `cfx` module's built-in defaults**:
- `cfx.U` defaults to `http://localhost:9377`. An empty `CFX_URL` makes it `""`, so every
  `post()` builds a path like `/tabs/<id>/evaluate` with no base →
  `ValueError: unknown url type: '/tabs/.../evaluate'`.
- `cfx._uid()` defaults to `"nasirjones"`. An empty `CFX_USER` makes it `""`, so the server
  returns `HTTP 400 userId is required`.

**Fix:** env files must contain ONLY `export CFX_KEY=...` + `export CFX_TAB=...`. After
`source .jobenv.*`, run `unset CFX_URL CFX_USER` in the same shell so the module falls
back to its defaults. The `cfx.sh` wrapper is unaffected because it computes its own base.

## 2. Re-persisting a fresh tab the safe way

`cfx.ensure_tab(persist=True)` only writes `CFX_TAB_FILE` if that env var is set; a plain
`source` won't pick it up. To persist a recovered tab to BOTH env files WITHOUT clobbering
`CFX_KEY` (and without writing empty `CFX_URL`/`CFX_USER` lines):

```python
import os
new = os.environ["CFX_TAB"]; key = os.environ.get("CFX_KEY", "")
body = f'export CFX_KEY="{key}"\nexport CFX_TAB="{new}"\n'   # deliberately NO CFX_URL / CFX_USER
for fn in (".jobenv.run", ".jobenv.persist"):
    p = os.path.join(os.getcwd(), fn); tmp = p + ".tmp"
    open(tmp, "w").write(body); os.replace(tmp, p)
```
Then `source .jobenv.run; unset CFX_URL CFX_USER` and verify:
`python3 -c "import sys;sys.path.insert(0,'sites/_common/scripts');import cfx;print(cfx.evaluate('1+1'))"`
(must print `2`, not a connection/url error).

## 3. Dead engine (Connection refused / health unreachable)

Symptom: `curl -fsS http://localhost:9377/health` returns nothing; `cfx` calls raise
`Connection refused` / `Connection reset by peer`. The REST server (not just the browser)
has died — commonly after a long feed crawl under host memory pressure.

Recovery:
1. The `camofox-vnc-watchdog.sh` at `/volume1/docker/playwright/` runs a
   `docker compose restart camofox-browser` on a timer. **Wait ~20–30s** and re-check
   `/health` — it often self-heals.
2. If not, trigger it explicitly:
   `cd /volume1/docker/playwright && docker compose restart camofox-browser`
3. `python3 sites/_common/scripts/cfx.py restart-engine` may fail ("engine never came
   back healthy") if the NOPASSWD sudoers rule is absent — fall back to the compose
   restart above (it does not need sudo from this host path).
4. Login persists in the browser profile across the restart, so re-login is usually NOT
   needed. Only re-run `csj_login.py` if a board shows "not logged in".

## 4. Order of operations after any outage
1. `curl -fsS http://localhost:9377/health` — is the server even up?
2. If down: compose-restart camofox-browser, wait, re-check.
3. `cfx.ensure_tab(persist=True)` for a live tab; persist ONLY key+tab (§2).
4. `unset CFX_URL CFX_USER`; verify with `cfx.evaluate('1+1')` == 2.
5. Re-check board login state; re-run the board's `*_login.py` only if needed.
