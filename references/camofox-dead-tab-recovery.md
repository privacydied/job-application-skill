# Camofox dead-tab recovery — when ensure_tab / sync-tab re-persist a STALE dead tab (2026-07-19)

## Symptom
`/health` returns `ok:true` but every `evaluate` against the tab 500s; `health_fingerprint()`
shows `degraded:true`, `eval_ok:false`, and all listed tabs have `title:''` / `innerText_len:0`.
Yet `cfx.list_tabs()` STILL lists those tabs, so `cfx.ensure_tab()` and `cfx.sync_tab()` return
the SAME dead tab id and re-persist it to `.jobenv.*` — the engine is wedged/degraded but the
tab is "alive" by membership. `cfx.goto()` returns a dict and does NOT raise, so the dead tab
only surfaces later as an `evaluate` 500 (or a blank-render `ok:False`).

## Why the usual fix fails
The FRESH-TAB footgun note says "get the new tab id from `ensure_tab(persist=True)`'s RETURN,
not os.environ". But when the engine is degraded, `list_tabs()` still contains the dead tabs, so
`ensure_tab()`'s `if cur and cur in list_tabs(): return cur` short-circuits and hands back the
dead id. `sync-tab` calls `ensure_tab(persist=False)` → same dead id → writes it everywhere. The
result: a fresh `cfx.goto` still 500s and `health_fingerprint().degraded` stays `True`.

## Fix (close-all → mint-fresh → write env from the RETURN value)
```python
import sys; sys.path.insert(0, 'sites/_common/scripts'); import cfx, os
for t in cfx.list_tabs():
    try: cfx.close_tab(t['tabId'])
    except Exception: pass
new = cfx.ensure_tab(persist=False)          # now mints a genuinely fresh tab
for fn in ['.jobenv.run', '.jobenv.persist']: # write BOTH from the RETURN value
    with open(fn, 'w') as f:
        if fn == '.jobenv.persist':
            f.write(f'export CFX_KEY="{os.environ.get("CFX_KEY", "")}"\n')
        f.write(f'export CFX_TAB="{new}"\n')
import time; time.sleep(1)
r = cfx.goto("https://www.reed.co.uk/jobs/ux-writer-jobs-in-london?pageno=4")
fp = cfx.health_fingerprint()
assert fp['degraded'] is False and r['ok'], fp   # verify before continuing
```
Then `source .jobenv.run` and resume. `prune-tabs` is NOT enough here — it leaves the live (=degraded)
tab and only reaps *older* ones; when the active tab itself is dead you must close it explicitly.

## Rule of thumb
If `health_fingerprint().degraded` is True, trust it over `list_tabs()` membership. Close every
tab and mint fresh; never trust `sync-tab` / `ensure_tab(persist=True)` to self-heal a degraded
engine. After recovery, re-login to boards whose session lived in the (now-closed) tabs.
