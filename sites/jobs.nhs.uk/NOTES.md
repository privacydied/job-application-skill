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
- **✅ Inputs/selects/textareas ALL bind via the native value-setter + `input`/`change` events.**
  (An earlier note claimed selects/date-pickers "resist automation" — that was a RED HERRING: the
  values bound fine; the real bug was clicking the wrong save button, so the section never POSTed
  and re-showed a stale error. See the button rule below.) HTML5 constraint validation
  (`required` + Bootstrap `was-validated`) is the gate — after setting `.value`, `checkValidity()`
  returns true. The one exception where **real keystrokes** (`cfx.press`) were still needed: the
  `RegisterNoPassword` name/email step (pre-application, before the main form).
- **⛔ EACH section/modal has its OWN save button — there is NO single "Save and Continue".** You
  MUST target the right one or the section silently never submits (the trap that wasted a whole
  pass):
  - Page sections (About You, Monitoring): **`#saveReferenceFormTab`** (text "Continue") /
    `#savePersnalApplicationFormBtn`.
  - **Employment** modal: **`#btnConform`** (text "Confirm").
  - **Education** modals (Higher Ed / Secondary / Other Training): **`#saveEducation`** ("Save").
  - **References** modal: **`#saveReferenceFormTab`** ("Continue").
  - Final: **`#saveApplicationForm`** ("Submit application") — disabled until the declaration
    checkbox `Declare` is ticked.
- Sections + modal fields (all `TemplateData[N].SelectedValue`; verified):
  - **About You**: title/name/address/contact (address accepts commas). AI-use radio `69`
    (applicant decides — flag it). "Where did you hear" → **NHS Jobs**.
  - **Supporting information**: competency textareas, per-question word limit (word counter
    updates on native-set input). This role: 4×300 words.
  - **Monitoring/Equal-opportunities**: 8 native `<select>`s + DOB text (DD/MM/YYYY) + Relationships
    textarea ("N/A") + Criminal Record. Optional per its own intro, but marked required.
  - **Employment** (Add → modal per role, most-recent first): Employer, City, Job title, Duties
    (textarea, required), Start/End dates `dateFromControl.SelectedValue` / `empEndDate`
    (DD/MM/YYYY), `experience_currently_working` checkbox.
  - **Education**: three Add sub-blocks — **Higher Education** (Subject/Qual, Year, Grade
    1st/2.1/2.2/3rd, Obtained/Expected), **Secondary/Further Education** (Year/Subject/Grade free
    text), **Other Training / Qualifications \*** (required; Details textarea + a required "UK
    professional registration" select → "Not required for this post" for non-clinical roles).
  - **References** (Add → modal per referee): Name+Email+Relationship+Type+Period all required
    (email enforced — phone alone fails). One referee clears the section; add more for full
    3-year coverage. Referee contacts are **real people → user-provided, never fabricated**.
- **Final submit is the applicant's**: tick the `Declare` checkbox → `#saveApplicationForm`. The
  supporting statements are agent-drafted (truthful/grounded) so the applicant should review before
  certifying "true and complete".

## Trac (trac.jobs) hand-off
Some trusts route "Apply" to their own **Trac** instance (trac.jobs — 403 to plain curl, needs
camofox). Trac is a server-rendered multi-page eform, same CLASS as TalentLink /
applicationtrack (VacancyFiller): native-DOM fills work, a real button `.click()` advances
pages, dates are 3 selects. When a listing hands off to Trac, follow the TalentLink/
applicationtrack recipe pattern; it too needs a (separate) Trac account.

## CAPTCHA
⛔ Per `references/captcha-policy.md`: full halt for any CAPTCHA except the two sanctioned
reCAPTCHA-v2 auto-solves. Not observed on the sourcing path.
