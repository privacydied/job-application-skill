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

## ✅ VERIFIED full apply flow (2026-07-17, NHSBT Digital Delivery Executive)

**⚠️ jobs.nhs.uk is now a pure AGGREGATOR** — the "new" NHS Jobs no longer hosts a native
application. EVERY trust routes "Apply" to its own downstream ATS (verified: 6/6 sampled
digital roles were external hand-offs). So an NHS application = an application on the trust's
ATS, each with its own account:

1. **Sign in to jobs.nhs.uk** (`/candidate/auth/login`): fields `input[name=user]` +
   `input[name=password]`, then **press Enter in the password field** (the Sign In button is an
   `<a>` that doesn't submit headlessly). Accept the cookie interstitial first
   (`/candidate/save-seen-cookie` blocks the login form until you do).
2. **Apply** → `/candidate/jobadvert/<REF>/ats-direct-apply` → an **interstitial** "You are
   leaving NHS Jobs" whose form `<input type=submit>` (no text) redirects to the trust's ATS.
   Common targets: **Jobtrain** (`jobs.<trust>.nhs.uk`, `source=JobtrainNHSJobs`), **Trac**
   (`trac.jobs`), **Oleeo**, **TalentLink**. The only external URL shown pre-submit is the
   trust's careers host.

### Jobtrain (jobs.<trust>.nhs.uk) — verified recipe
- Job detail → "Apply for job" (`/DecideInternalExternal/...`) → **"I don't work here"**
  (external path) → **RegisterNoPassword** (register-as-you-apply, passwordless): First/Last
  name → email + mobile + terms checkbox → drops you into the application.
- **⛔ Jobtrain inputs are JS-model-bound — programmatic `.value` does NOT bind.** Text inputs
  (`RegisterNoPassword` name/email, About-You address, DOB) need **real keystrokes**
  (`cfx.press` char-by-char); native value-setter is silently ignored by its custom model.
- **Textareas DO bind via native value-setter** (supporting-statement answers + the word
  counter update correctly). This is the split: textarea=native OK, input/select=real keys.
- Sections: **About You** (title/name/address/contact — address accepts commas here;
  `TemplateData[N].SelectedValue` named fields) → **References** (skippable — Continue with none)
  → **Supporting information** (competency questions, per-question word limits — for this role
  4×300 words on interest, coordinating workstreams, delivering in a complex org w/ WCAG+GDPR,
  and an accessibility/inclusion example) → **Monitoring/Equal-opportunities** → **Criminal
  Record Declaration** → **Review and submit**.
- **⚠️ CAPABILITY GAP — the Monitoring section's custom select + date-picker widgets resist
  automation.** DOM `.value`/`selectedIndex` set correctly (native-set AND keyboard type-ahead),
  but "Save and Continue" still returns a generic "Please complete all mandatory questions" with
  no per-field marker — the widget validates an internal state that neither native-set nor
  synthetic/real keyboard `change` events reliably update. **Hand this section to the user in
  noVNC** (native dropdown clicks bind instantly); it's OPTIONAL demographic data anyway. Pre-fill
  the `.value`s so the user only has to re-confirm.
- **Final submit is the applicant's** (review + submit their own application).
- "Where did you hear": pick **NHS Jobs**. AI-use question ("Do you intend to use AI tools?"):
  the applicant decides — flag it, don't answer silently.

## Trac (trac.jobs) hand-off
Some trusts route "Apply" to their own **Trac** instance (trac.jobs — 403 to plain curl, needs
camofox). Trac is a server-rendered multi-page eform, same CLASS as TalentLink /
applicationtrack (VacancyFiller): native-DOM fills work, a real button `.click()` advances
pages, dates are 3 selects. When a listing hands off to Trac, follow the TalentLink/
applicationtrack recipe pattern; it too needs a (separate) Trac account.

## CAPTCHA
⛔ Per `references/captcha-policy.md`: full halt for any CAPTCHA except the two sanctioned
reCAPTCHA-v2 auto-solves. Not observed on the sourcing path.
