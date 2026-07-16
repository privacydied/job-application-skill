# LinkedIn Easy-Apply drain tuning (2026-07-15)

## NO_BUTTON fast-fail patch (bucket-A code fix, verified 2026-07-15)
The `linkedin-easyapply` queue tag is often WRONG: many "Easy Apply"-tagged
postings are actually "apply on company website" (NO_BUTTON), not real EA.
`apply_ea.py` used to retry 3x internally on a NO_BUTTON (each walk = up to 12
`ea("next")` iterations with NO_NAV_BUTTON), burning ~6 min PER grinder and
stalling the whole drain (the driver re-iterates the queue from the start each
run, so it re-hit the same grinders every pass).

FIX: in `sites/linkedin/scripts/apply_ea.py`, capture the `open` result and on
`NO_BUTTON` return `rc=7` IMMEDIATELY (no retry). A NO_BUTTON posting is not a
real EA flow, so retrying is pointless. This turns a 6-min grinder into a ~12s
skip and is what unblocked the 84->112 climb. Keep this patch.

## Broadening the EA search to surface fresh inventory
The default `searches.csv` ships 12 `linkedin,...(Easy Apply)` rows. When the
7-day window (`f_TPR=r604800`) is exhausted on those, re-sourcing returns the
same postings (0 new). To get more:
- ADD new `linkedin,...(Easy Apply)` rows with distinct junior-role query groups
  (one row per `keywords=` OR-phrase cluster, all with `NOT senior NOT lead NOT
  head NOT principal NOT staff NOT director NOT manager`, `location=London`,
  `f_TPR=r604800`, `sortBy=DD`, `f_AL=true`). Verified-add clusters that yielded
  fresh cards: Junior Analyst, Coordinator, Administrator, Assistant, Business
  Analyst, Operations, Data Junior, Research Assistant, QA Junior, Project Junior,
  HR Junior, Finance Junior. (24 rows total by end of 2026-07-15 run.)
- FIX any row still carrying `f_TPR=r86400` (24h) -> `r604800` (7d) so all EA rows
  share the wider window.
- Append via Python (not hand-editing) to avoid CSV-quoting corruption; each row:
  `linkedin,"<query> (Easy Apply)",https://www.linkedin.com/jobs/search/?keywords=<urlencoded query>&location=London%2C%20England%2C%20United%20Kingdom&f_TPR=r604800&sortBy=DD&f_AL=true`

## Reading the drain verdict
`apply_queue.py` prints `{"verdict":...,"attempted":N,"tally":{"applied":A,"needs_human":H,...}}`.
- `NO_BUTTON` count in the log = false-positive EA tags (unavoidable; skip fast).
- `needs_human` that persists across runs = unanswered required SCREENERS. Teach
  them: add a substring pattern to `screener-answers.csv` (specific-before-generic).
  Verified teachable this run: "do you have professional servic"->Yes,
  "linkedin profile"->Yes, "this role pays up to"->Yes, "are you comfortable
  commuting"->Yes, "location (c"->select London. Do NOT auto-answer genuine
  eligibility gates like "Are you a 2025/2026 graduate?" (Jane is 30-34 -> truthful
  No; falsifying is out of scope).
- When a re-source returns the SAME postings and `needs_human` is all eligibility
  gates, the pool is exhausted for this rotation — stop re-sourcing (looping is the
  documented failure mode). Re-run `--refresh` later as the 7-day window rotates.
