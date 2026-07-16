# Volume driver pitfalls — running apply_queue.py for a big target (100+)

Session-verified learnings from a run that had to push an 82→100 count on
2026-07-15. The shipped `scripts/apply_queue.py` + `pipeline.run()` are correct,
but two defaults bite hard on a non-default target, and the queue is noisier
than its row count implies. Read this before a big-target drain.

## 1. THE DONE-GATE FOOTGUN (cost a wasted ~12-min sourcing pass)

`pipeline.run()` and `apply_queue.py` default `target=10` (from
`searches.py::DEFAULT_TARGET`). The preflight/pipeline DONE gate compares
**`applied_today` vs `target`**, NOT total-ever-applied vs target. With 16 rows
dated "today" and target=10, the pipeline returns `verdict=DONE` and
`apply_queue.py` prints "pipeline verdict=DONE — nothing to do" and EXITS 12
**without sourcing or applying a single thing** — even though the standing goal
(100 total) is unmet.

**Fix (mandatory for any target > 10):** export the real target before every
driver call:
```bash
export APPLY_TARGET=100          # apply_queue.py / pipeline.run read this from env
python3 scripts/apply_queue.py --refresh --force --max 8 ...
```
Never rely on the default. A `loop-preflight.py --target 100` may say WORK, but
the volume *driver* uses its own default-10 unless you set `APPLY_TARGET`. (The
shakedown early in the run silently no-op'd for exactly this reason — the tool
was fine, the target wasn't.)

## 1b. `--force` overrides cooldown but NOT the `applied_today` DONE gate

`--force` only bypasses the **board-cooldown** (re-sources even if a query's 12h cooldown
is active). It does **NOT** bypass `pipeline.run()`'s daily `applied_today >= target`
verdict. So `apply_queue.py --refresh --force --boards linkedin` still prints
`verdict=DONE — nothing to do` (exit 12) and exits WITHOUT driving if `applied_today`
already meets `target` (default 10). This session: `applied_today=49`, so even `--force`
no-op'd and the queue was never drained.

**To actually drive when the daily cap is already met:** you must raise the cap. Two ways:
- `export APPLY_TARGET=100` (or any value `> applied_today`) before the call, OR
- bypass the gate entirely by driving an existing `queue.jsonl` directly:
  `python3 scripts/apply_queue.py --boards linkedin --max N` (NO `--refresh`, so
  `pipeline.run()`'s DONE verdict is skipped and it just drains the existing queue).
Either way the driver runs; without one of these it silently does nothing.

(§1 covers the same gate from the `target=10` default angle; this is the specific
"--force-didn't-help" failure mode.)


## 2. QUEUE NOISE — "linkedin-easyapply" rows are mostly NOT submittable

`pipeline.run` tags a row `ats_hint=linkedin-easyapply` from the URL/board, but
that is a **weak heuristic**. A 30-row "easyapply" queue from a forced re-sourcews are mostly NOT submittable

`pipeline.run` tags a row `ats_hint=linkedin-easyapply` from the URL/board, but
that is a **weak heuristic**. A 30-row "easyapply" queue from a forced re-source
behaved like this under dry-run + real drain:

- **Most rows `open: NO_BUTTON`** — the listing is "Apply on company website",
  not real Easy Apply. The driver bails in ~2s (no Review reached). Cheap, but
  they don't apply.
- **Some hit `NEEDS_HUMAN`** (exit 7) on an unanswerable required screener
  (e.g. a react-select "Location (city)" the bank can't resolve). Correct
  behavior — but also 0 applications.
- **Only a handful reach Review and submit.** Verified submit rate in
  `apply-stats.csv` was `48 attempts → 10 submitted` (~21%); the *fresh*
  forced-re-source tail was worse (off-profile + senior + wrong-location).
- **The tail is off-profile by the skill's own hard screen** and MUST NOT be
  padded in: "Primary Substation Design Engineer (Energy)" (Ireland), "Hungary -
  AGV Technical Support Engineer", "Meridial Icelandic/German/Yoruba Language
  Specialist — Freelance AI Trainer", "£635 p/d Inside IR35" contractor roles.

**Implication for a volume run:** draining all 30 "easyapply" rows is correct
(the driver self-heals and bails fast on the junk), but expect **~5–8 real
submissions per 30-row queue**, not 30. Plan the source volume accordingly.
Never re-tag or hand-pick rows to inflate the count — the canonical dedup +
`check_title` screen is the only gate; respect it.

## 3. TRIAGE WITH --dry-run BEFORE SPENDING REAL ATTEMPTS

`apply_ea.py <url> <Company> <Role> --resume uploads/base-resume.pdf --dry-run`
walks the whole modal and stops at Review **without submitting**. Output tells
you the posting's fate in one pass:
- `DRY_RUN: reached Review, not submitting.` → **submittable**; re-run without
  `--dry-run` to apply. (Verified: Quanteam "Junior Application Support Analyst"
  #4438006262 reached Review, all screeners auto-answered, real submit →
  "SUCCESS: application sent" + logged `Applied` with proof.)
- `open: NO_BUTTON` → not real Easy Apply, skip.
- `NEEDS_HUMAN` → unanswerable screener, log `Blocked`/move on.

Useful when you want to *prove the path works* on one candidate before committing
the whole queue, or to pre-filter a suspect queue. Caveat: a single dry-run is
~90s of human-paced browser I/O, so don't loop-dry-run a 30-row queue serially —
just let `apply_queue.py` drain it (it bails fast on the bad ones).

## 4. DATA-SCARCITY CEILING IS REAL — DON'T PAD

After a forced re-source the on-profile fresh pool was dominated by
false-positive Easy Apply + off-profile tail. Re-clearing `board-cooldown.csv`
and re-sourcing rotated *some* new inventory (LinkedIn rotates hourly), but the
same degradation repeated. This is inventory exhaustion, **not** a wedge or dead
engine (health `browserConnected:true`, `consecutiveFailures:0`). Per SKILL.md
DATA-SCARCITY CEILING: report the real count + the unblock options; never
fabricate or pad with off-profile roles to hit a number.

## 5. ENV RE-POINT (Hermes path)

`.jobenv.run`'s `CFX_TAB` goes stale between calls (the tab dies with HTTP 410).
Re-point it to a live `job-apply` tab from `cfx.py list-tabs` before a driver run;
the `CFX_KEY` in `.jobenv.run` is the live 64-char token (NOT the short stale one
in `.jobenv`). Source `.jobenv.run` and re-export `CFX_TAB` every terminal call.

## 6. ⚠️ `searches.csv` rewrite corruption silently zeroes the LinkedIn source
When adding Easy-Apply-only queries (`f_AL=true` appended to a LinkedIn `nav`),
**append them as bare `board,query,nav` lines** — do NOT re-number the whole file
with an `N|` prefix. `read_searches()` in `search_plan.py` parses each line with
`csv.reader` and takes `parts[0]` as the board; a `1|linkedin` prefix makes
`bc.norm("1|linkedin")` never match `"linkedin"`, so **every LinkedIn row is
dropped** while `loop-preflight.py` still *shows* them (different read path). The
leak is invisible: `pipeline.run` sources 0 LinkedIn cards → `queue.jsonl` is 0
bytes → the driver drains nothing and emits no error. Confirm with:
`python3 -c "import search_plan as sp,bc; print(len([s for s in sp.read_searches() if bc.norm(s['board'])=='linkedin']))"`
— if that's 0 but `grep -c 'linkedin,' searches.csv` shows rows, you've prefixed
the file. Strip the `N|` prefixes. Give new EA `query` a distinct string (suffix
` (Easy Apply)`) so its cooldown key differs from the base query, and widen the
window to `f_TPR=r604800` (7d) when the 24h (`r86400`) set is already fully
tracked. (Same lesson also in `feed-scripting-pitfalls.md` §8.)

## 7. Tab wedge mid-source — recover via list-tabs, don't loop on POST /tabs
`activeTabs` can drop to 0 mid-run and `POST /tabs` can return ids that 404 on
verify (the wedge is deeper than a single create). Recovery that worked: retry
`cfx.py ensure-tab` a few times, then `python3 sites/_common/scripts/cfx.py
list-tabs` — a *living* tab on `https://www.linkedin.com/jobs/` eventually
surfaces there even when POST-returned ids 404. Re-point `.jobenv.run` `CFX_TAB`
and `.runtab` to that live id, then resume the source. If no tab ever persists,
the only real fix is `docker compose restart camofox-browser` — but on this NAS
that needs a password (`sudo` NOPASSWD grant has lapsed; `camofox-browser.env` is
permission-denied for user `<your-user>`), so escalate to the user rather than spinning on
the wedge. (Full symptom set in `camofox-session-stability.md` +
`camofox-backend-recovery.md`.)

