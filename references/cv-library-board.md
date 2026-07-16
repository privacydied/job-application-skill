# CVLibrary (cv-library.co.uk) — reachable agency board, account-gated

Discovered 2026-07-15 while probing Adzuna's website: Adzuna's UX/design "Apply for this
job" redirects land on **CVLibrary** (cv-library.co.uk) — a major UK agency job board.
CVLibrary is a DISTINCT board from the six canonical ones and was never in `pipeline.py`
`FEEDS`, so it is NOT covered by the standard sourcing loop. Capture it so the next
"LinkedIn off" session can try it as a fresh channel.

## What works
- CVLibrary job pages load WITHOUT a Cloudflare challenge at the job level (no Turnstile on
  `/job/<id>/<slug>`). A normal `cfx` navigate + snapshot works.
- Job pages show an **Easy Apply** tag + a green **Apply Now** button (e.g. UX Designer,
  Randstad, London — `cv-library.co.uk/job/225351767/ux-designer`).
- Search appears reachable (`/jobs/search?q=…`) — not verified for bulk harvest, but the
  single-job apply path is live.

## The blocker (same class as WTTJ)
- Applying requires a **CVLibrary account**. Clicking Apply Now while logged out does NOT
  open a usable apply modal (the click wedges / no login dialog surfaces) — Easy Apply
  implies it uses a saved CVLibrary profile + CV. There is **NO `cv-library.co.uk` row in
  `ats-credentials.csv`** (verified 2026-07-15: the csv has lbg/indeed-sso/adzuna/csj/moj/
  nationalarchives/interpublic/wttj/the-dots/reed — no cv-library).
- **This is a genuine "needs creds" unblock**, exactly like WTTJ. Provide Jane's
  CVLibrary email/password (free signup at cv-library.co.uk with you@example.com) and ensure
  his profile + CV are uploaded, then CVLibrary becomes a 4th drivable board.
- After login, drive the Easy Apply flow like Reed's: `cfx` click Apply Now → fill the
  modal (likely email/CV-confirm + screening Yes/No) → Submit. Reuse the Reed DOM-click
  pattern from `reed-apply-playbook.md` (button.btn-primary text "Apply Now", answer Yes
  radios + Continue until Submit application).

## Why it matters for the 100-target
When LinkedIn is rate-limited, the non-LinkedIn on-profile pool is near-zero (CSJ senior/
clearance-gated, Reed harvested, Indeed Cloudflare, Hackney 0-on-profile, WTTJ no-creds,
Adzuna API-key missing). CVLibrary is a NEW reachable board with real UX/Service/Product
Designer + UR + BA agency postings — once logged in, it could surface 10-30+ on-profile
junior-mid roles. It is the second-most-valuable unblock after the Adzuna API key.

## Action for the next session
1. Check `ats-credentials.csv` for a `cv-library.co.uk` row. If absent → ask the user for
   Jane's CVLibrary login (or sign him up).
2. Log in via `cfx`, then source + apply UX/Service Designer London/remote roles.
3. Add `sites/cv-library.co.uk/NOTES.md` + a `feed.py` if bulk-harvesting proves worthwhile.
