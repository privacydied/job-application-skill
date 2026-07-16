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
