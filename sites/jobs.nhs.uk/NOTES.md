# jobs.nhs.uk (NHS Jobs) — verified site notes

The central NHS recruitment portal — biggest single source for **gov/health digital,
service/UX design, and IT-support** roles (strong fit given NHS COVID-19 App experience).
Wired in `pipeline.py FEEDS` as `nhs`. Trust-level applications sometimes hand off to
**Trac** (trac.jobs) — see the Trac note at the bottom.

## Sourcing (VERIFIED live 2026-07-17)
- **Server-rendered** with stable `data-test` hooks (curl-reachable; sourced via camofox for
  consistency). NOT Cloudflare-walled.
- Search: `/candidate/search/results?keyword=<terms>&location=<loc>&distance=<miles>`. Cooldown
  key = the `keyword` param. ⚠️ NHS keyword search is LOOSE — "digital" is the cleanest
  on-profile query; "service designer"/"user experience" pull clinical roles (service manager,
  OT) because the words match clinical contexts. Screen hard downstream.
- Cards: `[data-test="search-result-job-title"]` (a[href] `/candidate/jobadvert/<REF>` + text,
  REF e.g. `C9289-SC-388`); `[data-test="search-result-location"]` folds **employer as its
  firstElementChild** + location as the remainder (split on that); `-salary` ("Salary: £X to £Y
  a year" → strip the prefix), `-jobType`, `-closingDate`, `-workingPattern`.

## ⛔ Apply is account-gated (sourcing only here)
"Apply for this job" → `/candidate/jobadvert/<REF>/ats-direct-apply` — the **native NHS Jobs
application**, which requires an NHS Jobs **candidate account** (sign in / create account).
Treat as a login gate: source freely, apply with the user's authenticated NHS Jobs session
(store creds in the gitignored `ats-credentials.csv`). No CV re-upload if the account profile
is complete — NHS apply is a structured multi-step form (personal details, employment history,
supporting information, equality monitoring), similar in shape to the CSJ/MoJ wizards.

## Trac (trac.jobs) hand-off
Some trusts route "Apply" to their own **Trac** instance (trac.jobs — 403 to plain curl, needs
camofox). Trac is a server-rendered multi-page eform, same CLASS as TalentLink /
applicationtrack (VacancyFiller): native-DOM fills work, a real button `.click()` advances
pages, dates are 3 selects. When a listing hands off to Trac, follow the TalentLink/
applicationtrack recipe pattern; it too needs a (separate) Trac account.

## CAPTCHA
⛔ Per `references/captcha-policy.md`: full halt for any CAPTCHA except the two sanctioned
reCAPTCHA-v2 auto-solves. Not observed on the sourcing path.
