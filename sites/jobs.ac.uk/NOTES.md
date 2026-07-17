# jobs.ac.uk — UK universities & research

The academic-sector board. On-profile because every London university hires the
"one-person digital team" family (§14) — web editor, digital content officer, digital
communications — plus IT/AV support (§13): learning technologist, AV technician, service
desk. Slow-moving and under-competed next to LinkedIn/Indeed; postings sit for weeks.

## Sourcing

Plain server-rendered HTML — **no browser, no key, no login**. Built on the shared
`httpfeed` runtime; this feed is the reference implementation of a declarative `Board`.

```bash
python3 sites/jobs.ac.uk/scripts/feed.py --what "digital" --where london --pages 2
python3 sites/jobs.ac.uk/scripts/feed.py --nav "https://www.jobs.ac.uk/search/?keywords=ux&location=london"
```

- Cards: `div.j-search-result__result[data-advert-id]`.
- **The id is the `/job/<CODE>/…` code (e.g. `DSG684`), not `data-advert-id`** — the code is
  what appears in the tracker URL, so dedup keys on it.
- Pagination is `startIndex` (1-based) at `pageSize=25`, not a page number.
- `sortOrder=1` = newest first.

`--where` is a plain substring the site matches loosely: a London search returns some
non-London rows (Salford, Oxford). That's the board, not a bug — precheck screens location.

## Apply

Off-site, per employer — jobs.ac.uk is **not** the apply surface. Most London universities
run **Stonefish** (`sites/stonefish/NOTES.md`), which is **account-walled: one account per
university**, and its apply is a `__doPostBack`, so applying needs a browser. Sourcing here
stays HTTP-only. `ats_hint` is deliberately empty — it only resolves on the JD page.
