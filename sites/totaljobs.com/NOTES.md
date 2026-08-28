# totaljobs.com (StepStone family) — verified site notes

Totaljobs is a large UK aggregator on **StepStone's "genesis" platform**. One adapter
(`scripts/feed.py`) also sources the siblings **CWJobs** (cwjobs.co.uk — tech/IT:
DevOps/cyber/support lanes) and **Jobsite** (jobsite.co.uk): pass `--base <site>` or set
`TJ_BASE`; via the pipeline the nav URL's host is used automatically. Wired in
`pipeline.py FEEDS` as `totaljobs` and `cwjobs` (both → `totaljobs.com` dir).

## Sourcing (VERIFIED live 2026-07-17)
- Search is **PATH-based**: `/jobs/<what>/in-<location>` (e.g. `/jobs/product-designer/in-london`)
  — NOT `?keywords=`. The cooldown key is parsed from that path (`_query_from_nav`) and matches
  the searches.csv `query` column after `board_cooldown.norm()` (hyphens↔spaces↔underscores).
- Result cards are `[data-at="job-item"]`; stable `data-at` hooks: `job-item-title` (a[href]),
  `job-item-company-name`, `job-item-salary-info`, `job-item-location`, `job-item-timeago`.
- Canonical posting URL: `/job/<slug>/<company-slug>-job<ID>` (id = the `-job<digits>` tail).
- Search pages are **NOT Cloudflare-walled to plain HTTP** (curl 200), but **listing/apply
  pages ARE** — source via camofox, don't curl a `/job/...` page.

## ⛔ Apply is StepStone-account-gated (login wall — same class as Reed/LinkedIn/WTTJ)
Every listing's "Apply" (even big employers like Revolut) routes through Totaljobs' own
`/application/authentication` flow — entering an email lands on a **password login** if an
account exists, else inline registration. The **only** external URL exposed in a listing is
StepStone's own corporate careers, never the employer's ATS — so there is **no account-free
apply path** here. Treat exactly like a login gate: **source freely; the apply step needs
the applicant's authenticated StepStone session** (their password is user-only, not stored).
If/when a Totaljobs password is available, add it to `ats-credentials.csv` (gitignored) and
the apply is: email → password → "Continue application" → on-site form + CV upload.

## CAPTCHA
⛔ Per `references/captcha-policy.md`: full halt for any CAPTCHA except the two sanctioned
reCAPTCHA-v2 auto-solves. Not observed on the search/sourcing path.

## ⛔ STALE ABOVE — Smart Apply works fine with stored creds (verified 2026-08-23/24)
The "account-gated login wall" section above is stale: with the `totaljobs.com (StepStone)`
row in `ats-credentials.csv`, clicking a listing's "Apply" button routes straight into an
already-authenticated **Smart Apply** flow (`/job/<uuid>/application/smart-apply`) —
name/email/phone/CV pre-filled from the account, occasional single-radio screener, "Send
application" → `/application/confirmation/success`. Verified working end-to-end on 6+
postings same session (Sterling Bridge x2, Robert Half, TechNest Talent, Keystream,
Interec/Antal). Treat as a normal ATS form, not a login wall, when creds are on file.

## ⚠️ Reproducible tab-kill on ONE specific posting (Interact Consulting, UX Researcher –
UK Government – Remote, job107861185) — 2026-08-24
Clicking "Apply"/"Continue application" on this exact listing killed the camofox tab
(`HTTP 404 Tab not found` on the very next call) **every time**, reproduced 3+ times with
independently fresh, verified-healthy tabs (confirmed alive via `document.title` immediately
before the click). One attempt's `click-follow` even reported `new_tab` opening a second
`about:blank` tab that ALSO died instantly alongside the original. This is narrower than the
general session-wide camofox instability seen the same run (which self-resolved) — it
reproduced only on this posting's apply click, not on the sibling Interact Consulting
"Service Designer" listing (`job107861179`) or any other totaljobs posting driven the same
session. Root cause not identified (possibly a heavy/broken embed on this specific listing's
smart-apply page). Logged `Blocked` after exceeding the 2-attempt cap; do not keep retrying
this exact posting id — if re-encountered, treat as a genuine block and move on.
