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

**Fix:** never write EMPTY `CFX_URL`/`CFX_USER` values. When the backend is local, omit them
(or `unset CFX_URL CFX_USER` after sourcing) so module defaults apply; when it is remote,
set `CFX_URL` to the LIVE host explicitly. The `cfx.sh` wrapper computes its own base and is
unaffected.

**Remote deployments: source before init.** `cfx.py init` syncs values from the environment it
can see; running it with no env loaded rewrites `CFX_URL` to `http://localhost:9377` and
`CFX_USER` to the built-in default, silently breaking every later call against a remote
backend. Always `source .jobenv.run` first, then `init`, then re-check the URL line in the
file before driving.

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
1. Resolve the configured host (`nslookup`, `ping -4`) and test BOTH `http://<host>:6080/vnc.html`
   and `http://<host>:9377/health`. An HTTP 401 on :9377 is normal (auth required); HTTP 000 /
   timeout means the ADDRESS is stale, not that camofox is down.
2. If the configured IP is dead but a hostname answers, set `CFX_URL` to that hostname in
   `.jobenv.run`, run `python3 sites/_common/scripts/cfx.py init`, and require
   `eval_ok: true, degraded: false` before driving anything.
3. If neither answers: compose-restart camofox-browser, wait, re-check.
4. `cfx.ensure_tab(persist=True)` for a live tab; persist ONLY key+tab (§2).
5. Verify with `cfx.evaluate('1+1')` == 2.
6. Re-check board login state; re-run the board's `*_login.py` only if needed.

## 5. Remote-backend address drift
A remote browser host can be reachable through a Tailscale hostname while its old LAN IP no longer
answers; DNS may resolve that hostname to a `100.64.0.0/10` address. Never declare the backend
down from one failed IP probe — test the hostname and VNC endpoint first, then repair `CFX_URL`
in place.

## 6. CFX_UPLOAD_DIR is client-side only
`CFX_UPLOAD_DIR` changes the path string the CLIENT sends to `POST /tabs/<tab>/upload`; the server
still resolves that path under its own `/uploads`. Setting or changing it cannot repair a missing
or unwritable container bind mount — the compose mount must change and the container must restart.
On a server carrying the upstream inline-upload patch, set `CFX_UPLOAD_MODE=inline` (or leave it
`auto` with a remote `CFX_URL`) so the client sends `filename` + `content_base64` and no shared
mount is needed; verify with a real `atsform.py upload <field> <file>` before a drive. Only when
inline is unavailable, use the local-browser CDP attach recipe in
`references/local-apply-fallback.md` as the fallback.

## 7. A single /evaluate HTTP 500 is transient
One `cfx.evaluate` (or `/navigate`) returning `HTTP 500 Internal server error` during a drive
does not prove the engine or container is dead. Re-run `cfx.py init` (source the env first),
`cfx.py check-engine`, and read `/health`; if `eval_ok: true` and `degraded: false`, resume on the
live tab. Report a container restart only after those checks fail. Treating one 500 as an outage
costs a needless NAS restart and a wrong handoff.
