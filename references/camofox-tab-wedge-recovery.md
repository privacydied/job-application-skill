# camofox tab-wedge recovery

## Symptom
After a long autonomous run the engine silently strands tabs. `curl -fsS
http://localhost:9377/health` still reports `browserConnected:true`, but the
browser holds ~10 open tabs and sourcing starts returning **0 / 3 cards on
boards you KNOW have fresh postings** (e.g. CSJ "service designer" collapsing
from 208 live cards to 3). This is the classic wedge, NOT exhaustion — every
terminal-negative from that window is suspect (matches SKILL.md's Contamination
Rule).

Root signal: a sourcing pass reports near-zero on a board that returned hundreds
minutes earlier. Check `activeTabs` in `/health` — >=8 is the danger zone
(SKILL.md: the engine strands past ~8 open tabs).

## Recovery (verified 2026-07-17)
Run from a terminal with `CFX_KEY`/`CFX_TAB` in env:

```python
import sys, time, os
sys.path.insert(0, 'sites/_common/scripts')
import cfx

tabs = cfx.list_tabs()
for t in tabs:
    tid = t.get('tabId')
    if tid:
        try: cfx.close_tab(tid)
        except Exception: pass
time.sleep(2)

new = cfx.ensure_tab(persist=True)   # opens ONE fresh tab, returns its id
os.environ['CFX_TAB'] = new
print('fresh tab:', new)
```

Then **persist the new tab id to BOTH env files** so child processes (feed.py,
jd.py, apply drivers) and the next firing inherit it:

```python
for fn in ('.jobenv.run', '.jobenv.persist'):
    lines = open(fn).read().splitlines()
    out = [ln if not ln.startswith('export CFX_TAB=')
           else f'export CFX_TAB="{new}"' for ln in lines]
    open(fn, 'w').write('\n'.join(out) + '\n')
```

`cfx.restart_engine()` alone does NOT drop the stranded tabs (logins survive in
the profile, so that's expected) — you must explicitly `close_tab` them first.

## GOTCHA — `cfx.persist_env` is a CLI, not a Python function
`cfx.persist_env(new)` does **not** exist in `cfx.py`. `ensure_tab(persist=True)`
writes the tab to the `CFX_TAB_FILE` default (often NOT your `.jobenv.run`), so
the env file the loop actually sources keeps the dead tab id. Always overwrite
`.jobenv.run` / `.jobenv.persist` by hand after `ensure_tab`, as above.

## Verify
```bash
source .jobenv.run
python3 -c "import sys;sys.path.insert(0,'sites/_common/scripts');import cfx;
cfx.goto('https://www.civilservicejobs.service.gov.uk/csr/index.cgi');
import time;time.sleep(2);print(cfx.health_fingerprint())"
# degraded:False + innerText_len in the thousands => wedge cleared
```
Then re-run the suspicious feed — the real card count returns.
