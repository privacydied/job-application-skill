# charityjob.co.uk — verified site notes

Biggest UK charity/third-sector board — the dedicated source for the **charity digital/web/
comms lane** (family #14; genuinely on-profile: Digital Marketing Officer, Digital Comms
Officer, Digital Inclusion Lead, etc.). Wired in `pipeline.py FEEDS` as `charityjob`.

## Sourcing (VERIFIED live 2026-07-17)
- Listing pages are **JS-rendered + bot-walled to plain curl** (0 bytes) — source via camofox.
- Free-text search: `?Keywords=` param (`/jobs/?Keywords=<terms>`); category browses like
  `/digital-jobs` also work. Cooldown key parsed from Keywords (case-insensitive) or the
  `/<cat>-jobs` path.
- Cards: `article.job-card-wrapper`; title link `/jobs/<charity>/<role>/<ID>` (ID = numeric
  tail). `.organisation` = "<Charity>, <Location> (<mode>)" — split on first comma.
- Salary usually only on the DETAIL page (not the card).

## Apply
Resolves per-listing — many charities push to their own ATS (Beapplied, Hireful, JobTrain,
etc.) or an on-site form. No CharityJob account needed to search/view.

## CAPTCHA
⛔ Per `references/captcha-policy.md`: full halt for any CAPTCHA except the two sanctioned
reCAPTCHA-v2 auto-solves. Not observed on the sourcing path.
