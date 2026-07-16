# LinkedIn sourcing pitfalls (added 2026-07-13)

Two LinkedIn-specific sourcing traps seen live this run. Both can let a
duplicate slip past feed.py dedup, or a real application get mis-skipped.

## 1. feed.py id-dedup misses LinkedIn→external-ATS Company+Role duplicates
`feed.py --nav` dedups results against `application-tracker.csv` **on the
LinkedIn numeric job id** (`data-job-id`). When a posting's apply flow
redirects to an external ATS (Easy Apply external, or "Apply on company
website" → Ashby / Workable / etc.), the tracker row for that SAME application
was logged with the **ATS URL**, not the `linkedin.com/jobs/view/<id>` URL. So
feed.py's id match fails and returns the posting as "fresh" — even though
`Company | Role` is already tracked (often `Applied`).

**Concrete miss (2026-07-13):** LinkedIn `4439359105` (Mistral, Product
Designer) came back in the "19 FRESH" set, but `Mistral | Product Designer` was
already `Applied` via its Ashby URL
(`jobs.ashbyhq.com/mistral.ai/f7e940ab-...`). The "6 already filtered out" count
gave a false sense of safety; the duplicate only surfaced on a manual
`grep mistral` of the tracker.

**Mitigation (already in SKILL.md's Dedup rule — enforce it):** after feed.py
returns, do a manual `Company+Role` grep of `application-tracker.csv` for any
posting whose apply redirects externally, and treat an existing non-Skipped /
non-Blocked row as a duplicate (skip, don't re-open). Do NOT trust feed.py's
filtered-out count as complete dedup for external-apply postings.

## 2. "Apply on company website" may safety-redirect through Adzuna
For some postings the "Apply on company website" link is a LinkedIn safety
redirect into **adzuna.co.uk** (e.g.
`linkedin.com/safety/go/?url=...adzuna.co.uk/jobs/details/<id>...`), which then
forwards to the REAL ATS (observed: Workable). This is NOT an aggregator
employer to skip — it's a LinkedIn redirect leg. Follow it through to the actual
ATS and apply there (same external-apply rules as always). Don't log `Skipped`
for "agency/aggregator" on the strength of the `adzuna.co.uk` URL alone.

**Note:** camofox `click-follow <ref>` handles the LinkedIn "Share your
profile?" consent dialog and the redirect hop automatically — use it for these
buttons (see `sites/linkedin/NOTES.md`).
