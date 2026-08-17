# Shared primitives inventory — grep HERE before you write a primitive

**Purpose.** Agents keep re-forking infra that already exists (and usually a worse copy):
a board-local combobox engine, a blanket tick-all, a bespoke tracker-dedup regex. The cause
is discovery cost — the shared function is behind a generic name in a big file, so writing a
local one *feels* cheaper. This file is the index that makes "does it already exist?" a
30-second grep instead of a 10-minute archaeology dig.

**The rule (AGENTS.md §no-divergent-duplicate):** a capability that spans boards has exactly
ONE home. If it doesn't do what you need, **extend the shared function in place** — never fork
it into a `sites/<board>/` file. Board adapters DELEGATE (see `sites/ashbyhq/scripts/ashby.py`:
`set_checkbox = atsform.set_checkbox`, `combobox_commit = …combobox_pick`). Enforced two ways:
`tests/test_core.py::TestNoDivergentFormWidgets` (red build) and
`loop-preflight._divergent_infra_guard()` (every firing, both runtimes) — both read the scan
from `sites/_common/scripts/infra_guard.py`.

> Before adding a shared function, confirm it isn't already here:
> `grep -rn "def <name>" sites/_common/scripts/` and skim this file.

---

## Browser / tab driving — `sites/_common/scripts/cfx.py`
The ONLY way to touch the camofox browser. Never post to `$CFX_URL` by hand from a board file.
- `navigate(url)`, `goto(url)`, `current_url()`, `compute_referer()` — page nav w/ anti-detect pacing.
- `evaluate(js)` / `eval_frame(...)` — run JS in the tab (returns the JSON result).
- `poll(js, predicate, timeout)` — wait for a DOM condition (use instead of blind `sleep`).
- `press(char)` — REAL per-char keystroke (react-select typeahead; synthetic events are ignored).
- `click_selector` / `click_ref` / `click_and_follow` — clicks; `click_and_follow` handles new-tab/consent handoff.
- `ensure_tab` / `set_tab` / `open_tab` / `sync_tab` / `is_tab_alive` / `prune_tabs` / `close_tab` — tab lifecycle.
- `claim_tab(tab, note)` / `active_tabs()` / `release_tab(tab)` — **the cross-process active-tab
  registry** (2026-08-17). A driver CLAIMS the tab it is using (pid + heartbeat, refreshed from
  `_tab()` on every REST call) and `prune_tabs` then SKIPS any claim whose owner is alive and
  recent. Before this, prune protected only the caller's tab and reaped everyone else's, killing
  live drives mid-application (`HTTP 404 Tab not found`). This is what makes **parallel apply
  lanes** safe — see `references/parallel-apply-lanes.md`. Claims self-clean on dead pid, stale
  heartbeat, or `close_tab`, so a crashed run cannot permanently protect a leaked tab.
- `post(path, body)` — raw REST (uploads: `POST /tabs/<tab>/upload`); `shot()` — screenshot.
- `dismiss_cookie_banner()`, `find_popup()`, `restart_engine()`, `engine_click_healthy()`.

## ATS application forms — `sites/_common/scripts/atsform.py`  ⭐ the big one
The ATS-agnostic form engine. A new board adapter is a THIN file that adds only that board's
quirks (reveal button, success signal); everything below is delegated, never re-implemented.
- `fill(label, value)` — text/textarea by visible-label substring (`@file` / `-` stdin supported).
- `combobox_pick(target, option, multi=, clear_first=)` — **THE** universal dropdown/react-select
  driver (native `<select>` + Greenhouse/Lever/Ashby/WTTJ/SmartRecruiters). `select`, `combo`,
  `pick_dropdown`, `react_select`, `answer` all route through it. **Won't bind headlessly? Extend
  the ladder here — do NOT fork a per-board combobox.**
- `select(label, option)` / `react_select(...)` / `react_select_type(...)` / `pick_dropdown(...)` — thin wrappers over combobox_pick.
- `set_radio(question, option)` / `pick_radio(...)` — radio groups.
- `set_checkbox(label, on|off)` — one checkbox by label.
- `checkboxes_from_profile()` — **truthful** auto-tick: ticks only affirmatively-true boxes,
  leaves marketing / anti-AI / unknown / false unticked and reports them. This REPLACED blanket
  tick-all — never write a `click every checkbox` loop again.
- `upload(label|#id, file)` / `upload_chooser(...)` — file inputs (verifies by basename).
- `rclick(text)` / `click_button(text)` — click by visible text, self-verifying.
- `answer(question, value)` — dispatch a Q to the right widget (text/select/radio) by shape.
- `active_step()` / `advance()` — multi-step wizard navigation.
- `review(company, must_haves)` — pre-submit CONTENT audit (placeholders, wrong-company, missing keywords).
- `submit(button, success_regex)` — click submit + verify success / report alerts.
- `apply(config)` / `checkboxes_from_profile` / CLI `python3 atsform.py <cmd>`.

## Tracker dedup + apply-time guard — `sites/_common/scripts/precheck.py`
- `canon_ids(url)` — board-agnostic stable posting id(s). **The dedup key.** New board? Add its
  native-id pattern to `_CANON_PATTERNS` here (mirror the board's `feed.py` `seen_pattern`).
- `canonical_url(url)` — normalized, storable URL (strips tracking params; `''` = reject malformed).
- `already_applied(url, company, role)` / `is_applied(status)` — tracker lookup.
- `guard(url, company, role, label)` — **mandatory pre-submit dedup gate every driver calls.**
- `load_tracker()` / `load_seen(pattern)` — read the tracker for dedup.
- `precheck(candidates)` — the whole cheap pre-filter (title + location + dedup + salary) in one call.
- `screen_location(loc)`, `salary_for(...)`, `salary_band_top(...)`.

## Writing tracker rows — `sites/_common/scripts/log-application.py`
- **THE only writer of `application-tracker.csv`.** Never `echo >>` or hand-append. Handles
  match-in-place, the downgrade guard, URL canonicalization, the `Applied` proof rule, and locking.

## Title eligibility — `sites/_common/scripts/check_title.py`
- `check_title(title)` — the ONE on/off-profile + seniority screen. Never re-list seniority/role
  words elsewhere (`tests/test_core.py::TestNoDivergentTitleScreen` fails the build if you do).

## Board cooldown / yield — `sites/_common/scripts/board_cooldown.py`
- `mark`, `is_active`, `remaining_hours`, `mark_daily_limit`, `record_yield`, `expected_yield`,
  `consecutive_dry`, `query_from_url`, `adaptive_hours` — the cooldown + expected-yield ledger.

## Screener answer bank — `sites/_common/scripts/screener.py`
- `lookup(question)` / `record(q, a, kind)` / `classify_question(q)` / `triage(...)` — the persistent
  answer bank (`screener-answers.csv`). Don't hardcode Q→A maps in a driver.

## JD fetch + screen — `sites/_common/scripts/jd.py`
- `extract(url)` / `compact(...)` / `screen_one(...)` — pull + screen one JD.

## Sourcing / feeds — `sites/_common/scripts/`
- `httpfeed.py` (the `BOARD(...)` harness every HTTP feed shares — pass a `seen_pattern`),
  `merge_sources.py` (`--drop-tracked` dedup + merge), `pipeline.py`, `search_plan.py`.

## Files / locking — `sites/_common/scripts/fsutil.py`
- `file_lock(path)` (RMW advisory lock), `atomic_write(...)`, `locked_append(...)`. Use these for
  any shared-state CSV/JSONL write — never a bare open-write on a file another process touches.

## Misc shared engines (grep before re-rolling)
`recaptcha.py`, `accounts.py`, `company_cache.py`, `statedb.py` / `state_view.py`, `journal.py`,
`warm.py`, `ats_router.py`, `quirks.py`, `blockers.py`, `verdicts.py`, `outcomes.py`,
`fit_score.py`, `tailor.py`, `tracker_stats.py`, `apply_stats.py`, `stagetimer.py`,
`company_cache.py`, and `infra_guard.py` (the duplicate-infra scan itself).

---

### When the shared one genuinely lacks a capability
1. Add/extend the function in its `sites/_common/scripts/` home (thin, general).
2. Delegate from the board file (`x = atsform.x`, or a 1-line wrapper).
3. If a board truly needs different *timing* (e.g. Ashby's post-autofill re-render), keep only
   the timing/poll in the board file and hand the *mechanics* to the shared engine.
4. Never copy the shared function into a board file to tweak it — that's the exact drift the two
   guards above exist to catch.
