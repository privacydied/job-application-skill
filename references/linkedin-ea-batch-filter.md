# LinkedIn Easy-Apply batch driver — keeping the 100-target run HONEST

`scripts/apply_queue.py` is the headless volume driver: it (re)builds `queue.jsonl` via
`pipeline.run()` (the shipped funnel) and drives `apply_ea.py` per LinkedIn Easy-Apply
row. It replaced the old `run_pass.py`, whose bespoke sourcing/filter/dedup were a
parallel re-implementation of shipped tools (perf-roadmap F.1).

## The bug that started this (2026-07-15, live)
A shakedown pass applied the bundled `check_title.eligible` verdict as the gate. Of 4
submissions, 3 were OFF-PROFILE — `Electrical Design Engineer`, `ICT Design Engineer`,
a `Senior Product Designer`. Root cause: `check_title` did a naïve `phrase in title`
substring match, so `"design engineer"` (Tier A) matched every industrial
`<discipline> Design Engineer`, all `eligible=true, seniority_flag=false`.

## The fix now lives in `check_title.py` (single source of truth), NOT a driver
`run_pass.py` worked around it with its own `on_profile()` word lists — which quietly
held the *only correct* discipline filter while the canonical path still leaked (and
which also wrongly excluded Tier-C `field service engineer`). That divergence is exactly
what P0.2's divergence test now forbids. The screen is centralized:

1. **Discipline false-cognate guard** — `check_title._industrial_design_engineer()`:
   a `design engineer` title with an industrial modifier (`electrical/ict/mechanical/
   cad/rf/structural/hvac/…`) and no UX/creative signal → `eligible:false,
   discipline_flag:true`. Bare `Design Engineer` (Tier A), `UX Design Engineer`, and
   `field service engineer` (Tier C) stay on-profile. Widen the modifier list THERE.
2. **Seniority** — `check_title` sets `seniority_flag`; `precheck` drops
   `eligible+seniority_flag` titles (except the CSJ junior-mid grade rescue). Senior/
   Lead/Manager are off-target for a junior→mid applicant.
3. **Positive on-profile keyword** — `eligible` already requires a target-roles tier
   phrase match; `software engineer`/`data scientist`/`backend`/`full stack` never match
   a tier phrase, so they're already `eligible:false`.

`apply_queue.py` inherits ALL of this through `pipeline → precheck → check_title`. It
re-implements no screening — that is the whole point of retiring `run_pass.py`.

## Malformed-URL guard
A feed can return a card whose `url` is the search-results page itself
(`…/jobs/view/search`) rather than a job. `pipeline`/`precheck` screen those out before
they reach `queue.jsonl`, and `apply_ea.py` validates the job id/url it's handed; a bad
row is skipped, not navigated blindly.

## Running for volume
```
source .jobenv.run && source .jobenv.persist   # live 64-char CFX_KEY + CFX_TAB
python3 scripts/apply_queue.py --refresh --max 8         # shakedown: rebuild queue, apply ≤8
python3 scripts/apply_queue.py --refresh --force         # full pass; --force re-sources cooled boards
python3 scripts/apply_queue.py --boards linkedin --refresh   # LinkedIn Easy-Apply only
```
Tally lands in `/tmp/apply_queue_count.json`
(`{attempted, tally:{applied,needs_human,failed,dry_ok,other}, needs_model, already_tracked}`).
Rows on any non-Easy-Apply ATS are reported as `needs_model` (they need a tailored
resume/cover letter — a model step) and left in the queue, never applied off a generic
PDF. Dedup against `application-tracker.csv` is the canonical `precheck.load_tracker`
map, read once (Blocked stays retryable).
