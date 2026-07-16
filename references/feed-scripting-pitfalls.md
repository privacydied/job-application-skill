# feed.py / cfx.py raw-scripting pitfalls (2026-07-14)

Lessons from batching the sourcing pipeline in Python (subprocess + urllib), not the
interactive CLI. Each bit here cost a failed parse and a wasted run.

## 1. feed.py prints a TEXT line BEFORE the JSON array
Every `feed.py` (linkedin / indeed / wttj / csj / hackney) prints a human summary
first — e.g. `21 FRESH jobs (4 already in application-tracker.csv filtered out). …`
or `EXHAUSTED: all 0 jobs … Auto-marked … on cooldown …`. Then the JSON array.
`json.loads(p.stdout)` therefore raises. **Fix:** scan stdout for the first line
starting with `[`, then bracket-match to the matching `]`:

```python
def parse_feed(p):
    if not p: return None
    text = p.stdout or ""
    try: return json.loads(text)          # whole-text sometimes works
    except Exception: pass
    start = text.find("[")
    if start >= 0:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "[": depth += 1
            elif text[i] == "]":
                depth -= 1
                if depth == 0:
                    try: return json.loads(text[start:i+1])
                    except Exception: break
    return None
```

(Indeed's variant also emits a leading `clear: no modal open.` line before the
array — same parse handles it; see `references/indeed-feed-json-prefix.md`.)

## 2. Raw `GET /tabs` returns a DICT, not a list
`cfx.py list-tabs` wraps it, but a raw `urllib` call to `GET /tabs?userId=nasirjones`
returns `{"running":true,"tabs":[…]}`. Handle both:
`d.get("tabs", []) if isinstance(d, dict) else d`. A bare `d[0]` on the dict →
`KeyError: 0`.

## 3. `--force` bypasses the cooldown gate
`feed.py --nav <url>` without `--force` returns `[]` immediately (and auto-marks
cooldown) if that board+query was already drained. When you deliberately re-source
or use a *new* query, pass `--force`. Alternate/widened queries carry different
cooldown keys, so they naturally evade the gate — that's intended for broadening
(covers the "100 more" case where the day's earlier run drained the bundled queries).

## 4. cooldown only tracks the bundled queries
`board-cooldown.csv` records only the `searches.csv` bundles, not your ad-hoc
alternate queries. So new queries (e.g. wider title vocab, remote+London filter)
are NOT blocked by the cooldown of the original bundles — use them to break a
drained board (see `references/sourcing-screening-pitfalls.md`).

## 5. Drive navigation via REST, not a missing CLI verb
There is no `cfx.py nav`. To navigate a tab from Python:
`POST /tabs/<tabId>/navigate` with `{"userId":…,"url":…}`. To evaluate JS:
`POST /tabs/<tabId>/evaluate` with `{"userId":…,"expression":…}` — returns
`{"ok":true,"result":<value>}`.

## 6. ⚡ LinkedIn/Indeed cooldown is a SOFT self-imposed limit — CLEAR IT to resurface fresh inventory
`board-cooldown.csv` / `board_cooldown.py` is enforced **in code by `feed.py`** (it
bails before navigating when a board+query row is still inside its `cooldown_until`).
It is NOT a hard backend block. When you believe a board is "exhausted" but suspect
inventory rotated, **delete that board's rows from `board-cooldown.csv`** (or set
`cooldown_until` to a past time) and re-run `feed.py --nav <url>` **without
`--force`** — it will navigate and re-crawl. **This is the single biggest fresh-pool
lever: clearing the LinkedIn cooldown on 2026-07-14 resurfaced 91 fresh candidates
that a same-day "exhausted" call had suppressed.** Caveat: actual job inventory
rotates slowly (hours/days), so re-sourcing the SAME queries repeatedly yields the
SAME postings (already in the tracker → 0 net-new). Clearing the cooldown helps when
inventory HAS rotated (next morning, or after the ~12h window), NOT when called twice
in the same hour. Combine with alternate query URLs (different cooldown keys, §4) for
maximum new-posting yield.

## 7. `.jobenv` vs `.jobenv.run` — STALE CFX_KEY trap (cost a dead session this run)
The committed `.jobenv` can hold a WRONG / truncated `CFX_KEY` (e.g. an old short
token). The **live 64-char token lives in `.jobenv.run`** in the same skill dir.
Symptom: `GET /health` works but every `POST /tabs` returns `401 Unauthorized`, or
`ensure-tab` returns a tabId-less response and navigations 500. **Fix: copy the key
from `.jobenv.run` into your live env** (`export CFX_KEY="<64-char token from
.jobenv.run>"`), or `cp .jobenv.run .jobenv` if the rest of the env matches. Always
re-source `.jobenv` (or reset `CFX_KEY`) at the start of a session — never assume the
committed key is current. The tab id changes constantly (camofox wedges/dies); only
the key is stable, so persist and re-`source` the env file each terminal call.

## 8. ⚠️ NEVER prefix `searches.csv` rows with `N|` — silently zeroes the LinkedIn source
`read_searches()` in `search_plan.py` parses each line with `csv.reader` and takes
`parts[0]` as the board token. If you rewrite the file by re-numbering lines as
`1|board,query,nav`, `parts[0]` becomes `"1|linkedin"` → `bc.norm("1|linkedin")`
never equals `"linkedin"`, so **every LinkedIn row is dropped** (indeed/wttj too).
`loop-preflight.py` still *shows* them (different read path), so the leak is
invisible: `pipeline.run` sources 0 LinkedIn cards → `queue.jsonl` is 0 bytes →
driver drains nothing, no error. **Symptom to recognize:**
`python3 -c "import search_plan as sp,bc; print(len([s for s in sp.read_searches() if bc.norm(s['board'])=='linkedin']))"`
returns 0 even though `grep -c 'linkedin,' searches.csv` shows rows present.
**Fix:** strip the `N|` prefixes — `searches.csv` must be plain `board,query,nav`
(no line-number prefix). If you add rows (e.g. Easy-Apply-only `f_AL=true`
variants), append them as bare `board,query,nav` lines and give `query` a distinct
string (suffix ` (Easy Apply)`) so the cooldown key differs from the base query.

## 9. ⚠️ `apply_queue.py` / `pipeline.run` DONE-gate defaults to target 10, not 100
`pipeline.run(target=None)` falls back to `sp.DEFAULT_TARGET` (=10) unless
`APPLY_TARGET` env is set or `--target N` is passed. With 16 already Applied
"today", the driver returns `verdict=DONE` and refuses to source — even when the
standing goal is 100 total. **Fix:** always `export APPLY_TARGET=100` (or pass
`--target 100`) before running `apply_queue.py` for a big-target run, or it stops at
10. The gate counts `applied_today` (Date column == today), so a midnight rollover
or a backlog run can also trip it — dedup against the whole tracker, not
`date.today()` (see `rotation-recovery-2026-07-15.md` §C).

## 11. ⚠️ Reed `feed.py` defaults to `--pages 1` — PAGINATE or you silently under-harvest (cost 15 wasted "exhausted" passes, 2026-07-16)
Reed's `feed.py` takes `--pages N` (default **1**) and `--all` (bypass cooldown + include
already-tracked). A single-page harvest of one query family returns only ~25 postings,
but Reed holds **hundreds** per family. Running the LinkedIn-off "100 more" pivot with only
page-1 Reed sourcing produced a FALSE "Reed fully harvested" conclusion that held for 15
passes — until a re-source with `--pages 4 --all` across 12 families returned **588 unique /
326 on-profile / 102 precise-Jane-profile UNapplied jobs** (Reed apply clicks work reliably,
unlike CSJ/CVLibrary). **Rule:** for any volume target, source Reed with `--pages 4 --all`
(and more pages if the family is deep) across ALL Jane target-role families, dedupe, then
filter. Never declare Reed (or any board) exhausted from a page-1 pass. This is the Reed
analog of the CSJ "stops at page 1" note (§3 CSJ entry) — both require explicit pagination.
Re-apply the same lesson to `indeed`/`wttj`/`hackney` feeds: pass `--pages N` (or `--all-pages`
where supported) before crediting a zero-fresh pass as true exhaustion.

## 10. Tab wedge recovery — POST /tabs then confirm via list-tabs, not GET /tabs
When the engine wedges, a bare `GET /tabs?userId=nasirjones` (and `cfx.list-tabs()`
which calls it) can hang, while `POST /tabs` sometimes answers. But a created tab
id from POST can still 404 on verify (the wedge is deeper). Recovery that worked:
retry `cfx.py ensure-tab` a few times, then `python3 sites/_common/scripts/cfx.py
list-tabs` — a *living* tab on `https://www.linkedin.com/jobs/` eventually
surfaces there even when POST-returned ids 404. Re-point `.jobenv.run` `CFX_TAB` and
`.runtab` to that live id. If tabs stay at 0 and no tab ever persists, the real fix
is `docker compose restart camofox-browser` — but on this NAS that needs a password
(`sudo` NOPASSWD grant has lapsed; `camofox-browser.env` is permission-denied for
user `<your-user>`), so escalate to the user rather than looping on the wedge.
