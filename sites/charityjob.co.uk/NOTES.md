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

## In-platform apply + off-site ATS recipes (verified 2026-10-05)
- `a.btn-apply` ("Redirect to recruiter" even for in-platform jobs) -> `cfx.py click-follow --selector 'a.btn-apply'`.
  Two outcomes: a NEW TAB on the employer ATS, or a same-tab hop to `identity.charityjob.co.uk/login` (in-platform).
- In-platform: enter email -> `sign-up/direct` (first name, surname, password, T&C; untick newsletter) -> 6-digit code
  emailed by `donotreply@charityjob.co.uk` (arrives up to ~1 min late; `fetch_verification_code.py --sender charityjob`
  returned NO_CODE once - read the mailbox directly) -> `/apply` page: CV upload (`#cv-file-upload-input`, REST
  `/upload` with `selector`) + rich-text cover letter (execCommand/paste do NOT bind; real `cfx.press` per char works,
  ~0.1 s/char) -> `#btn-review-continue` -> `#btn-submit` -> "Your application has been submitted successfully".
  Account row: `identity.charityjob.co.uk (CharityJob)` in ats-credentials.csv.
- Off-site targets seen: Scope -> MHR iTrent (`ce0258li.webitrent.com`, screening asks the barred-list declaration, so a user
  question); BookTrust -> Ciphr iRecruit (registration forces 2FA Authenticator/SMS = hard stop); British Heart Foundation ->
  `jobs.bhf.org.uk/registration.aspx` (same single-iframe ASP.NET portal as Hippo Digital, CV upload gap).

## BookTrust (Ciphr iRecruit) - 2FA authenticator is SOLVABLE; apply form gotchas (2026-10-05)
- "Authenticator" 2FA setup shows a "Manual Entry Key" (base32). `python3 scripts/totp.py <secret>` gives the 6-digit
  code (stdlib RFC 6238). Enter it on the setup page, confirm the backup code page, and store the secret in the
  ats-credentials.csv row. Later logins: Username/Password, then `/Account/VerifyTwoFactor` `TFACode`.
- The first "Next" buttons call a native `confirm()`; the headless click does not advance. Workaround that created the
  application: POST the form with `fetch` (`new URLSearchParams(new FormData(form))`) and open the returned
  `/Applicants/application/<id>` URL; then fill the pages `/1` personal, `/31` job questions, `/33` gaps, `/17`
  equalities, `/14` declaration.
- Use the shell `cfx.sh click <ref>` for the form "Save and continue" button.
- Equalities page has mandatory socio-economic selects; each has "Prefer not to say".
- Declaration page asks criminal-convictions and accuracy declarations: the user's own, so the run stops there.

## Off-site ATS recipes added 2026-10-09 (lane7)
- **CharityJob apply click:** `document.getElementById('ApplyButton').click()` (JS) opens the employer ATS in a NEW tab
  (find it with `cfx.list_tabs()`); `cfx.py click-follow --selector a.btn-apply` hits the "Report an issue" dialog instead.
- **Talos (`<org>.talosats-careers.com`, Breast Cancer Now):** job page -> "Quick Apply" link -> `/Forms/Application?...`.
  The Angular form renders EMPTY on first load; **reload once** and it appears. One page: personal, address, CV upload
  (`input[type=file]`, give it an id then `atsform.py upload "#id" <anon.pdf>` - it prints NONE but the file attaches),
  supporting statement textarea (5,500 chars), EEO selects, accuracy tick, **Submit Application**. Success URL
  `/application/complete/<id>` "Thanks for applying!". Needs the name-blind CV `uploads/base-resume-anon.pdf`.
  Native value-setter works on every field. Applied: BCN User Researcher 2026-10-09.
- **Ciphr iRecruit (`<org>.ciphr-irecruit.com`, Prostate Cancer UK):** registration button does NOT fire on a native click;
  POST the form with `fetch()` (see postform pattern: `new URLSearchParams(new FormData(form))`), then a forced 2FA
  Authenticator setup (`scripts/totp.py <Manual Entry Key>`). Application wizard: set `window.confirm=()=>true` before
  clicking the first Next/Confirm. Pages: Personal -> Job Questions -> Supporting Information -> Equal opps -> **Declaration
  asks the unspent-convictions question = the applicant's own -> Blocked**.
- **TribePad (`mycareeratdiabetes.org.uk`, Diabetes UK):** returning-user email -> password login; step 2 questionnaire has
  a safeguarding/criminal-record disclosure question (Q7) = the applicant's own -> Blocked.
- **Networx (`<org>.current-vacancies.com`, RCR):** email box needs a REAL typed value (`cfx.sh click` + `type`, then clear
  doubles); account modal -> verification link from IMAP (From jobs@<org>) opened in a second tab -> "Check Verification" ->
  quick-apply dialog; jQuery validator needs `keydown/keyup` events on the statement textarea; "Don't Notify Me" on the
  job-alert modal. Applied: RCR Digital Content Officer 2026-10-09.
