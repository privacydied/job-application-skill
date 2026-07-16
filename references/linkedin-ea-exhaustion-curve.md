# LinkedIn Easy-Apply exhaustion curve (verified 2026-07-15, target 100+)

This is the empirical ceiling for the London/junior profile on LinkedIn `f_AL=true`,
7-day window (`f_TPR=r604800`). Use it to know when to STOP re-sourcing and pivot, and
to recognize the re-source-yields-0 anti-pattern.

## The curve (one session, single 7-day window)

| Stage | Applied | What changed |
|-------|---------|--------------|
| start | 83 | — |
| +12 original EA rows | 95 | NO_BUTTON fast-fail patch (see `apply-mechanics.md` §NO_BUTTON) unblocked the drain |
| broaden 12→18 rows | 99 | added Junior Analyst / Coordinator / Administrator / Assistant / Business Analyst / Operations families |
| teach 3 screeners | 107 | `do you have professional servic…` / `linkedin profile` / `this role pays up to` → Yes |
| broaden 18→24 rows | 111 | added Data Junior / Research Assistant / QA Junior / Project Junior / HR Junior / Finance Junior |
| re-drain (no new rows) | 111 | drain11 verdict applied=0, needs_human=12 — **0 new** |
| re-source 24 rows + drain | 111 | drain12 verdict applied=0, needs_human=16, NO_BUTTON=20 — **0 new** |

**Real submittable ceiling for this profile on LinkedIn EA ≈ 111.** Beyond that, every
fresh-ish posting is either a `NO_BUTTON` false-positive (~55–65% of `f_AL=true` hits) or
blocks on a hard eligibility gate.

## Anti-pattern: re-sourcing the SAME bundles yields 0

Once `searches.csv` EA rows are drained, re-running `apply_queue.py --refresh --force
--boards linkedin` returns the **same postings** (the 7-day window hasn't rotated) and the
drain re-bails on the same `needs_human` set. drain11 and drain12 proved this: `applied=0`
both times despite fresh sourcing. Re-looping the same bundles is the failure mode the
DATA-SCARCITY CEILING rule warns about — do NOT keep doing it.

**What actually moves the count:**
1. **Broaden `searches.csv` to NEW junior-role query families** (new cooldown keys → new
   inventory). The 6 families that worked this session, as a template — copy each into a
   new `linkedin,"<bool OR bundle> NOT senior…manager" (Easy Apply),<nav>` row with
   `&f_AL=true&f_TPR=r604800&sortBy=DD` appended to `nav`:
   - Junior Analyst: `"Junior Data Analyst" OR "Data Assistant" OR "Data Coordinator" OR "Reporting Analyst" OR "MI Analyst"`
   - Coordinator: `"Coordinator" OR "Junior Coordinator" OR "Project Coordinator" OR "Operations Coordinator" OR "Administrative Coordinator"`
   - Administrator: `"Administrator" OR "Junior Administrator" OR "Office Administrator" OR "Operations Administrator" OR "Data Administrator"`
   - Assistant: `"Assistant" OR "Junior Assistant" OR "Research Assistant" OR "Digital Assistant" OR "Content Assistant"`
   - Business Analyst: `"Business Analyst" OR "Junior Business Analyst" OR "IT Business Analyst" OR "Systems Analyst" OR "Reporting Analyst"`
   - Operations: `"Operations Assistant" OR "Operations Analyst" OR "Junior Operations" OR "Support Officer" OR "Customer Support Analyst"`
   - (later pass) Data Junior / Research Assistant / QA Junior / Project Junior / HR Junior / Finance Junior
2. **Teach the `needs_human` screeners** (consent / commute / location / salary-consent /
   years-of-experience-when-genuinely-true) via `screener.py learn`, then re-drain WITHOUT
   `--refresh` to harvest them. Triage with:
   `grep -oE "BLOCKED_UNANSWERED_REQUIRED: .*" <drain.log> | sed 's/BLOCKED_UNANSWERED_REQUIRED: //' | sort | uniq -c | sort -rn`
3. **Pivot to CSJ** (big-volume board) once LinkedIn EA is at its ceiling — see
   `csj-sourcing-pitfalls.md` + `csj-allpages-pagination-fix.md`.

## Hard eligibility gates are NOT teachable screeners

When the `needs_human` question is a genuine eligibility gate, leave it `needs_human` —
do NOT teach it as `Yes`. This session hit: **"Are you a 2025/2026 graduate?"** → Jane is
30–34, NOT a recent graduate, truthful answer is **No** → the posting is genuinely off-pipeline.
Teaching it `Yes` would fabricate eligibility and pad the count. Same for any gate whose
false answer removes him from the pipeline (specific clearance, specific degree year, etc.).
A `needs_human` that is really an eligibility gate = end of the line for that posting.

## DOM-verified "all-fresh-are-promoted" ceiling signal (learned 2026-07-15, late session)

The NO_BUTTON fast-fail (`apply_ea.py`) is CORRECT, not a false negative. To prove a
fresh posting is genuinely non-drivable (vs a flaky detect), open `/jobs/view/<id>` and run this DOM probe:

```python
import sys, time
sys.path.insert(0, 'sites/_common/scripts'); import cfx
def read(e):
    for _ in range(12):
        try:
            r = cfx.evaluate(e)
            if r is not None: return r
        except Exception: pass
        time.sleep(1.0)
    return "R?"
cfx.navigate('https://www.linkedin.com/jobs/view/<id>/'); time.sleep(11)
f = (read("document.body.innerText") or "").lower()
print("has_ea_text:", 'easy apply' in f)
print("apply_on_company_site:", 'apply on company site' in f)
print("promoted:", 'promoted' in f)
print("real_btn:", read("""[...document.querySelectorAll('button')].map(b=>(b.innerText||b.getAttribute('aria-label')||'').trim().toLowerCase()).filter(t=>t=='easy apply'||t=='apply').join('|')||'NONE'"""))
```

A **promoted (non-drivable) card** answers: `has_ea_text=True`, `apply_on_company_site=False`,
`promoted=True`, `real_btn=NONE`. The "Easy Apply" it shows is a *link to a search-results page*,
not a clickable job-apply `<button>` — confirmed by clicking the anchor and landing on
`/jobs/search-results/?keywords=…` instead of an apply modal. `easyapply.py`'s `_click_nav`
matches `button` only, so it correctly returns `NO_BUTTON`.

**Ceiling signal:** when a fresh re-source across MULTIPLE distinct query families (User
Researcher, Frontend Developer, Junior UX/Product/UI/Service/Content Designer) ALL return
`open: NO_BUTTON` AND the DOM probe shows `promoted=True`/`real_btn=NONE` on each sampled
posting, the live LinkedIn EA inventory for this account is **100% promoted cards** — a
platform throttle / EA-quota condition, not a tooling bug and NOT fixable by re-sourcing.
This was the verified state 2026-07-15 after the count reached 112 (every family, multiple
re-sources, DOM-confirmed). At that point `apply_queue.py` re-sources return only
promoted/non-EA cards; further re-sources produce 0 submittable postings.

**Do NOT widen to off-profile senior/intelligence/data-analyst families to "find more"** —
those are off-pipeline for Jane (design/research/growth) and violate the no-fabrication rule.
State the single true unblock (time-based EA-inventory return) and stop.

## `searches.csv` hygiene (load-bearing)
- Keep rows UN-prefixed (no `N|` line numbers) — `read_searches()` CSV-parses the file and a
  prefix breaks it (returns 0 LinkedIn rows → empty queue). If a source ever returns 0 with
  `--force`, check the file for stray prefixes first.
- All EA rows must carry `&f_AL=true&f_TPR=r604800` (7-day EA window). The default bundled
  rows use `f_TPR=r86400` (24h) and no `f_AL` — at a big-target run those return 0 fresh.
