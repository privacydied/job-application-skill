# Continuous Apply Loop — accumulating toward a large target (100+)

The bundled `searches.csv` queries + `board-cooldown.csv` are built for a ~10-app run.
A 100-application target cannot come from one day's bundled queries (they auto-cooldown
to 12h the moment a pass yields 0 fresh, and a single day's niche inventory is finite).
To reach a big number you need a **persistent loop that re-sources as inventory rotates
and applies each new on-profile posting** — running unattended, self-healing the tab.

## Why a plain re-source isn't enough
LinkedIn/Indeed rotate postings hour by hour. Clearing the soft cooldown (delete the
board's rows in `board-cooldown.csv`, or set `cooldown_until` to a past time) and
re-running `feed.py --nav <url>` WITHOUT `--force` re-crawls immediately. This resurfaced
**91 fresh candidates** from a LinkedIn pass that a same-day "exhausted" call had
suppressed — because new postings had rotated in. The "only helps after ~12h" caveat in
SKILL.md Volume-reality is too conservative: **it works whenever inventory has rotated,
often within hours, not only next morning.** Re-clear + re-source on a timer.

## The loop shape (proven 2026-07-14)
```
for cycle in range(N):
    cands = source_li()                 # feed.py --nav on each linkedin bundle
    q = screen(cands)                   # tier A/B, non-senior, non-agency, not tracked, not attempted
    for j in q:
        apply_one(j)                    # nav -> easyapply open -> drive steps -> submit -> log
    sleep(60)
```
- `screen()` must exclude already-`attempted` ids (persist a `/tmp/feed/attempted_ids.json`
  set so a restart doesn't re-hit them) AND already-tracked ids (tracker dedup).
- Prefer `Easy Apply` postings: login-free, uses Jane's profile, driven via
  `sites/linkedin/scripts/easyapply.py`. External-apply ("Apply" -> company ATS) postings
  are logged `Blocked` (manual/ATS-driver needed) — they are NOT Easy Apply and the
  Workday/Greenhouse SPAs blank the camofox tab on this engine.

## TWO bug-fixes that make the loop actually survive (2026-07-14 hard lessons)
1. **Self-heal MUST reuse ONE tab — never open a new one on 500/410.** A naive
   `ensure_tab()` that calls `cfx.ensure_tab()` (which opens a fresh tab) on every
   failure piles up tabs and re-creates the ~10-tab wedge (`POST /tabs` -> `Internal server
   error`, every in-flight call dies with 500). Fix: `ensure()` should REUSE the surviving
   tab — `cfx.list_tabs()[0]["tabId"]` — and only `cfx.ensure_tab()` (open new) when the
   list is truly empty. One tab, reused across all cycles.
2. **`easyapply.py open` returns `NO_BUTTON` unless the tab is ALREADY on the job page.**
   `open` only clicks the in-page "Easy Apply" button; it does NOT navigate. Sequence:
   `nav(job_url)` -> `sleep ~9s` (let the card + apply button render) -> `easyapply.py open`.
   Calling `open` on a tab sitting on a search/feed page (or a page that hasn't rendered
   the button yet) returns NO_BUTTON even for a real Easy Apply posting. The easyapply
   `state`/`fill`/`next`/`submit` primitives then read the shadow-DOM modal correctly.

## Drive steps (per posting)
- `easyapply.py state` -> read `labels` + `nav`. Fill obvious screener fields by label:
  location->"London", authorized-to-work->"Yes" (radio), notice->"4 weeks",
  current-salary->"55000", years-experience->"5". If a step mentions resume/cv/upload,
  `easyapply.py upload uploads/resume.pdf` (re-upload per posting — the PDF PERSISTS across
  Easy Apply sessions; see `references/easyapply-resume-persistence.md`).
- When `nav` shows "Submit application" -> `easyapply.py submit` (look for "SUCCESS"/"sent").
- `BLOCKED_UNANSWERED_REQUIRED` on `next` -> try `next --force` once; if still stuck, log
  `Blocked` and move on (hard attempt cap = 2).
- Log EVERY outcome via `log-application.py` (Applied / Blocked) so the tracker reflects
  reality and dedup holds.

## When to stop
The loop is for VOLUME via rotation, not for forcing a number. Stop the loop and report
the real count when: (a) the engine is wedged and won't recover after a restart, or
(b) re-sourcing yields 0 fresh for several consecutive cycles with inventory not rotating
(data-scarcity ceiling — see SKILL.md DATA-SCARCITY CEILING). Never pad the count with
off-profile/senior/location-fail roles. The loop catches postings the first pass missed
because it re-screens as inventory rotates.
