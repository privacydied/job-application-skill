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

## ⚠️ Apply button click 500s with a Playwright strict-mode violation — use `>> nth=0` (verified 2026-09-04, CMC Markets Business Analyst)
`cfx.click_selector('[data-testid="harmonised-apply-button"]')` reliably 500s on the current
totaljobs template — camofox-browser's own log shows the real cause is NOT a backend/tab
problem but a Playwright **strict-mode violation**: the selector resolves to **3 elements**
on the page (duplicated apply buttons — likely one visible + hidden/sticky variants sharing
the same `data-testid`). Fix: append `>> nth=0` to the selector —
`cfx.click_selector('[data-testid="harmonised-apply-button"] >> nth=0')` — which clicked
through straight to `/application/confirmation/success` on the first try. This is the same
"duplicate id/testid → pick nth=0" pattern already documented for SmartRecruiters file
inputs; apply it here too instead of retrying the bare selector or assuming a wedge.

## New driver shipped 2026-09-25: `sites/totaljobs.com/scripts/tj_apply.py`
Promotes the manual cfx-driven flow documented above into a real batch driver (mirrors
`reed_apply.py`'s shape). `python3 tj_apply.py <job_url> [<job_url> ...] [--dry]`.

**TWO apply-flow shapes** exist and the driver handles both:
1. **Smart Apply review form** (most common): "Apply" click lands on a pre-filled
   Contact/CV review page needing a second "Send application" click -> confirmation page
   showing "Application sent!".
2. **One-click variant**: a single "Apply" click goes straight through to a
   confirmation-style "Application summary" / "Did all go well with your application?"
   page — no second click exists or is needed. Treating the absent "Send application"
   button as a failure here was a real bug (5 genuine submissions misreported STUCK/
   NO-SEND-BUTTON live 2026-09-25) — fixed by checking for either terminal state before
   assuming a second click is required.

**Confirmation interstitial**: after "Send application", a "Sending your application...
this should only take a few seconds" interstitial renders BEFORE "Application sent!" — a
single short sleep can read the interstitial and misreport STUCK on a genuine submission.
Poll up to ~15s.

## ⛔ COURSE-SIGNUP TRAP (same class as Reed, 2026-09-25) — different signal shape
TotalJobs doesn't carry Reed's literal "Training Course" job-type badge, so
`tj_apply.py`'s `_COURSE_SIGNUP_RE` scans the JD body for course-pitch language
("fully-funded course", "government-funded programme", "traineeship", "job guarantee",
"become job-ready", "gain a ... certification", …) before ever clicking Apply. **Extend
that regex in tj_apply.py** for a new disguise phrasing found on THIS board — Reed's badge
detector lives in reed_apply.py and is a different signal shape, so don't try to share one
regex across both drivers.

## ⛔ ROLE-SPECIFIC SCREENING QUESTIONS ON THE REVIEW FORM — never blind-answered
Some Smart Apply review pages show an "Additional questions" / "Action required" block
with role-specific Yes/No screeners naming SPECIFIC tech stacks/tools ("strong commercial
experience with Angular and TypeScript?", "hands-on experience using NgRx?"). Unlike
Reed's more generic "X years experience?" screeners, TotalJobs' questions can name a
tech stack the applicant provably doesn't have (live: Gazelle Global Consulting "Frontend
Developer" asked about Angular/NgRx/RxJS — applicant-profile.md's real stack is
React/TypeScript). `tj_apply.py` has no code that can verify an arbitrary tech-stack claim
against the applicant's truthful skills, so `_screening_questions_text()` detects the
"Additional questions" block and `apply()` refuses — returns `BLOCKED — role-specific
screening question(s)` — instead of guessing. This is a STOP-and-flag, not an auto-No; a
human or a future skills-aware check should read the actual question text before deciding.

## ⛔ UPDATE 2026-09-25 (same session, later): "one-click variant" confirmation is UNRELIABLE
The "one-click variant" described above was initially trusted as a real submit signal
(`Application summary` / `Did all go well with your application?` / bare
`confirmation/success` URL). Live cross-checking against the account's own "N
applications" -> "Applied Today" list (https://www.totaljobs.com/ homepage) found this is
WRONG for several postings: Hackajob Ltd "Technical Business Analyst" and "Technical
Support Specialist I", Arup CWS "Technical Business Analyst", Southern Housing
"Transformation Service Designer", and Rocket "Kitchen Systems Administrator" ALL showed
one of these confirmation-shaped pages, yet the job listing still read plain "Apply" (never
flipped to "Already applied") and NONE of them appeared in the account's Applied history.

**Root cause (working theory):** these are external-ATS-redirect postings where TotalJobs
shows its own "we sent your info along" confirmation UI regardless of whether the
downstream employer/agency ATS actually received the application — the same class of
unreliable signal as an external redirect on other boards.

**Fix:** `tj_apply.py`'s final verdict now trusts ONLY the literal "Application sent!"
banner (the Smart Apply review-form flow's real terminal state) as SUBMITTED. Everything
else — bare `confirmation/success`, "Application summary", "Did all go well" — returns
`UNVERIFIED`, never auto-logs `Applied?`, and the caller must cross-check the account's
Applications list before counting it. **When re-driving a one-click-flow posting, ALWAYS
verify against the account's own "N applications" list (or check the job listing itself
for "Already applied" vs plain "Apply") before trusting a confirmation page — this applies
whether the driver or a human eyeballed it.**
