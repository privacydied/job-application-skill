# Apply mechanics — deep per-ATS + volume detail (read on demand)

Extracted from SKILL.md's per-turn context (2026-07-15): these are reference details you
only need when actually driving a specific ATS or chasing a big volume target. SKILL.md
keeps the one-line pointers; the depth lives here.

## LinkedIn Easy Apply — the end-to-end driver and its gotchas

Primary path is `apply_ea.py` (summarized in SKILL.md Step 5). Depth:

- **Batch volume path:** `scripts/easyapply_batch.py <queue.txt>` (line format:
  `EA|Role|Company|https://www.linkedin.com/jobs/view/<id>/`) drives N postings
  end-to-end with proof + logging; self-heals a dead tab and retries the SAME posting;
  dedups against the tracker; polls the post-submit spinner. The four gotchas that break
  a naive driver — sponsorship/authorised/relocate screeners are **RADIOS not text**; the
  submit spinner races `state()`; mid-batch tab death; resume persistence — are in
  `references/easyapply-batch-pitfalls.md`. **Source LinkedIn WITH `f_AL=true` (Easy
  Apply only) before falling back to external-ATS redirects** — the filtered pass is the
  automatable pool. Persistent high-volume runs (re-source as inventory rotates, incl. the
  self-heal-tab-reuse fix that prevents the 10-tab wedge): `references/continuous-apply-loop.md`.
- **`easyapply.py open` only clicks the in-page button — it does NOT navigate.** Always
  `nav(<job_url>)` + ~9s render sleep BEFORE `open`, or a real Easy Apply posting falsely
  reports `NO_BUTTON`.
- **Resume PERSISTS across Easy Apply sessions** — a 2nd Easy Apply shows the previous
  posting's PDF still attached. Always re-`upload` the per-posting PDF and confirm the
  Review step shows `resume = <this-posting>.pdf` before `submit`.
  `references/easyapply-resume-persistence.md`.
- **Custom radio/checkbox widgets commit unreliably via `easyapply.radio`** — substring
  matching collides (Man⊂Woman), div-wrapped groups return `NOT_FOUND`, and a JS `.click()`
  flips `checked` but not React state. Read the shadow-root DOM, click the
  `data-test-text-selectable-option` wrapper with a trusted MouseEvent sequence, match
  EXACT option text, treat ethnicity "Select all that apply" as a checkbox. Residual
  "valid answer" wall → log `Blocked`. `references/linkedin-easyapply-shadow-radio-commit.md`.
- **Auto-advance confirmation (FIXED 2026-07-15):** apply_ea.py now confirms a submit that
  LinkedIn auto-advances straight to "Your application was sent" (no Review step) — it logs
  inline via `submit`'s own SUCCESS signal. (Earlier note that it "missed" these is stale.)
- **Unanswerable required screener → bail, don't loop:** apply_ea.py returns `NEEDS_HUMAN`
  (exit 7) on a blocked required field (e.g. a react-select "Location (city)" that won't
  commit) instead of spinning to the attempt cap. Consult the screener bank first
  (`screener.py`), answer + `screener.py learn` if it's a genuinely new question, else log
  `Blocked`. `references/easyapply-batch-pitfalls.md` §10–§11.
- **⚠️ NO_BUTTON fast-fail (PATCHED 2026-07-15, was the #1 time-sink).** A `linkedin-easyapply`-
  tagged queue row is frequently a **false positive** — the listing is "apply on company
  site", not a real Easy Apply modal. `easyapply.py open` returns `NO_BUTTON`, and the OLD
  code then walked the (non-)modal 12× and retried `max_attempts` (3×) = **~6 min of
  pure stall per dead posting**. PATCH: in `apply_ea.py run()`, capture `open_res = ea("open")`
  and `return 7` immediately if `"NO_BUTTON" in open_res` — a ~12s skip. Always re-verify
  after any edit to `apply_ea.py` that touches the `open` call: `python3 -m py_compile
  sites/linkedin/scripts/apply_ea.py`. If a future run stalls 3+ min on one posting with
  `attempt N: never reached Review`, this fast-fail regressed — re-add it.

## Ashby — toggle commit (the one that silently fails validation)

`sites/ashbyhq/scripts/ashby.py apply` (its own keys — `cv`/`files`/`toggles`; see docstring).
`check` reports toggles/radios "empty" even when set (it reads the hidden checkbox, not the
button state) — `references/ashby-toggle-check-gotcha.md`. **Pre-submit MUST-DO:** `set-toggle`
reads button COLOUR; `submit` validation reads the BACKING `input[type=checkbox]` inside
`[data-field-path="<uuid>"]`. For EVERY required toggle, find that checkbox (name = field
uuid, or inside the container) and `.click()` it if `!checked`; trust `submit`'s "Missing
entry" error over `set-toggle`'s OK.

## Upload gotchas — Workday & Greenhouse

- **Workday** (`*.myworkdayjobs.com`) — three failure modes: Apply click-drift
  (`sites/myworkdayjobs/NOTES.md`), resume date-revert, and a **silent "Save and
  Continue" submit wall** (`references/workday-silent-submit-wall.md`). Create-account +
  apply recipe (trusted-click submit, `noCaptchaWrapper` false-positive, hierarchical
  "How did you hear", `/upload` `path` param): `references/workday-create-account-flow.md`.
  Resume upload can be unbindable → `references/workday-resume-upload-unbindable.md` (log
  `Blocked`; don't submit corrupted dates to a regulated employer).
- **Greenhouse** — the `<input type=file>` is visually-hidden with a random
  `question_<digits>` id and no snapshot ref; `atsform.py upload` fails on it. Verify
  attach by the rendered `canonical-xxx.pdf` + "Remove file" paragraph, not
  `input.files[0]`. Full react-select / EEO / time-zone pitfalls:
  `references/greenhouse-ats-pitfalls.md`.

## Volume — reaching a big target (e.g. 100)

A big target is NOT met from one day's bundled queries: the `searches.csv` bundles
auto-cooldown the moment a pass returns 0 fresh (now ADAPTIVE — 12h escalating on repeated
dryness, 6h for high-yield rows; see board_cooldown.py) and drain fast. To reach a big target:

**⚠️ THE `APPLY_TARGET` DONE-GATE (this silently no-ops a big-target run).** `pipeline.run()`
and `scripts/apply_queue.py` default `target=10`. The DONE gate compares **`applied_today` vs
`target`**, not total-applied vs target — so with 16 applied "today" and target=10 it returns
`verdict=DONE` and `apply_queue.py` exits 12 without sourcing/applying ANYTHING. **Always
`export APPLY_TARGET=100` (or your real target) before any driver call.** `loop-preflight.py
--target 100` may say WORK while the *driver* still uses default-10 — the driver is what runs.
Full gotcha + the queue-noise reality + the `--dry-run` triage technique:
**`references/volume-driver-pitfalls.md`**.

**Queue noise:** a `linkedin-easyapply`-tagged row is a weak heuristic, not a guarantee. Expect
~5–8 real submissions per 30-row queue (most are `NO_BUTTON` "apply on company site" or
`NEEDS_HUMAN`); verified historical submit rate ~21% (48 attempts → 10 submitted). Drain the
whole queue and let the driver self-heal/bail; never pad with off-profile rows.

- **⚠️ `searches.csv` must stay UN-prefixed (gotcha 2026-07-15).** `search_plan.read_searches()`
  parses each row with `csv.reader` and takes `parts[0]` as the board. If you ever renumber
  rows with an `N|` prefix (e.g. `12|linkedin,...`), the board becomes `"12|linkedin"` and
  `bc.norm()` never matches `"linkedin"` → **`sp.plan()` returns 0 linkedin rows in `clear`**
  → pipeline sources nothing → 0 queued, with NO error. If a `--refresh` run reports
  `0 queued (0 keep, 0 review)` yet a direct `feed.py --nav` on the same URL returns cards,
  suspect this: open `searches.csv`, strip every leading `^\d+\|` prefix, re-verify with
  `python3 -c "import sys;sys.path.insert(0,'sites/_common/scripts');import search_plan as
  sp,bc;print(len([s for s in sp.read_searches() if bc.norm(s['board'])=='linkedin']))"`.
  Edit the rows' `query`/`nav` fields, not the line numbers.

- **Lean on CSJ for volume** — its London set is hundreds of postings across ~17 pages with
  little tracker overlap (`--all-pages`). Most are senior/off-discipline, but junior-mid
  EO/HEO roles are on-profile and invisible to title-only precheck — open borderline JDs
  (junior-mid salary bands) and read the "Job grade" row (SKILL.md §Boards, CSJ).
- **Break cooldown with NEW query URLs, not the bundled ones** — `python3 scripts/gen_queries.py`
  emits ready alternate OR-bundled searches (wider vocab, no seniority exclusion, `f_WT=2`
  remote, `fromage=14`) that hit DIFFERENT cooldown keys; pick a line and `feed.py --nav <url>`
  (no `--force` — the new key isn't on cooldown). Simpler still: the cooldown is enforced
  in code from `board-cooldown.csv`, not the backend — deleting a board's rows (or
  back-dating `cooldown_until`) and re-running re-crawls immediately. LinkedIn rotates
  inventory hourly, so re-clearing often yields fresh within hours. Persistent-rotation loop:
  `references/continuous-apply-loop.md`; stale-key trap: `references/feed-scripting-pitfalls.md` §6–7.
- **Expression-of-interest / dead posts slip past precheck** — glance `jd_text` for
  "register your interest" / "does not represent a live vacancy" before tailoring; log `Skipped`.
- **Never pad the count** with off-profile/senior/wrong-location roles. Pool exhausted for the
  day → report the real count + the cooldown window/new-board options.
