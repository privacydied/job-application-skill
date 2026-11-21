# Trac (`trac.jobs` / `healthjobsuk.com`) — ACCOUNT CREATED, APPLY PATH OPEN

Trac (a **Civica** product) is where NHS trust applications actually happen — `sites/jobs.nhs.uk/`
is now a pure aggregator that hands off to the trust's own ATS, and Trac is one of the common
targets (alongside Jobtrain / Oleeo / TalentLink). It is **also** where a large share of Civil
Service Jobs adverts marked "Apply at advertiser's site" land — including UKHSA.

> Trac registration uses reCAPTCHA v2 (`recaptcha.py`); the account exists and Trac submits. HTTP/curl is Cloudflare-challenged, camofox renders the pages normally.

## Sourcing is browser-only (Cloudflare challenge over HTTP)

`https://www.trac.jobs/search/vacancies` returns 403 to plain curl. **Better headers do not fix
it** — they just reroute:

| URL | plain curl | full browser header set (UA + Accept + Sec-Fetch-* + `--compressed`) |
|---|---|---|
| `www.trac.jobs/search/vacancies` | 403 | 200 but **redirects to `apps.trac.jobs/`** (the login portal) — the search route is gone |
| `www.trac.jobs/` | 403 | **403**, 107 KB body |
| `healthjobsuk.com/` (public board) | — | **200** — landing page only |
| `healthjobsuk.com/job_list/ns?JobSearch_q=digital` (search **results**) | — | **403** |
| `healthjobsuk.com/job/UK/London/…/-v8079394` (a job **detail**) | — | **403** |

Every 403 body is the same interstitial:
> "Site unavailable — **Trac Security check**. Please complete the security check to access
> Trac: Enable JavaScript and cookies to continue. Why do I have to complete a CAPTCHA?"

with `/cdn-cgi/`, `__cf_chl` and `Cloudflare` markers. Reproduced on repeat attempts — not a
transient. So:
- **Only landing pages are HTTP-reachable.** The search results page *and* every job detail page
  are challenged. There is nothing to scrape over HTTP.
- **→ sourcing is NEEDS-BROWSER.** Solve any challenge per `references/captcha-policy.md`. Do **not** hammer it: fast retries compound the
  Cloudflare risk score, and `cfx.sh check-cooldown trac.jobs` / `record-captcha-fail` exist for
  exactly this.

The public search form is otherwise trivial (`GET /job_list/ns`, one field `JobSearch_q`, job
URLs `/job/UK/<region>/<city>/<trust>/<specialty>/<specialty>-v<ID>` where `v<ID>` is the id) —
the wall is the whole problem, not the markup.

## ⛔ Headline 2 — apply requires a Trac account

`apps.trac.jobs` is the candidate portal, and it states the gate plainly:
> "Trac powers the recruitment for a large proportion of the UK's public sector workforce.
> **Create an account to apply for jobs** and track the progress of your applications
> including employment checks, appointments and more."

- **Sign in** form `FrmCoreLogin-CandidateSignIn` → `FrmCoreLogin-CandidateSignIn_Email`,
  `FrmCoreLogin-CandidateSignIn_Password`.
- **Create account** form `StartRegistration` → `StartRegistration_emailaddress`, plus
  **"Please confirm you are not a robot (required)"**.
- Both carry hidden `_tr` / `_ts` / `_ct` / `_gt` / `_gt2` tokens (per-render; must be replayed).
- Employer side is `admin.trac.jobs` — irrelevant here.

This matches `sites/jobs.nhs.uk/NOTES.md`'s existing note ("it too needs a (separate) Trac
account"). One Trac account covers the Trac-hosted trusts; store it in the gitignored
`ats-credentials.csv` (via `httpfeed.creds_row`), never env.

## CAPTCHA summary
| where | vendor | policy |
|---|---|---|
| sourcing (`healthjobsuk.com` search + detail, `www.trac.jobs`) | **Cloudflare** managed challenge | solve per `references/captcha-policy.md` |
| account creation (`apps.trac.jobs`) | **reCAPTCHA**, `data-sitekey="6LeuMgITAAAAAHgU6j_DDWMZeN74PyUptT5jffvk"` | reCAPTCHA v2 → auto-solve via `sites/_common/scripts/recaptcha.py` |

## Trac's own public job boards
`healthjobsuk.com` ("Job Search" from the portal), `nursingnetuk.com`, `nhsjobs.com` — all Trac
front-ends, all behind the same Cloudflare posture.

## Apply form shape — ⚠️ NOT verified
`build-audit.md` claims "Trac apply is a plain multi-step form — very drivable", and
`sites/jobs.nhs.uk/NOTES.md` describes it as "a server-rendered multi-page eform, same CLASS as
TalentLink / applicationtrack (VacancyFiller): native-DOM fills work, a real button `.click()`
advances pages, dates are 3 selects."

**This probe could not confirm any of that** — the account wall plus the Cloudflare challenge
mean no application form was reached over HTTP. Whether `atsform.py`'s label matching drives
Trac is **unverified**; the TalentLink-class claim is inherited, not re-tested here. Treat it
as a hypothesis until someone reaches a real Trac eform with an authenticated browser session.

## Build verdict
**Lowest priority of the three ATSes probed.** Sourcing is browser-only *and* runs into a
a Cloudflare challenge; apply needs an account behind a
reCAPTCHA. Meanwhile `sites/jobs.nhs.uk/` already sources NHS adverts freely and un-walled —
so the only thing a Trac driver buys is the *apply* leg, and only for trusts that route to Trac
rather than Jobtrain. Prefer **Oleeo** (`sites/oleeo/NOTES.md`: HTTP sourcing, anonymous apply
start) before investing here.


## ✅ REACHABLE ROUTE (2026-08-16): NHS Jobs hands off straight to the Trac advert

The Cloudflare wall above applies to Trac's OWN search and job-detail URLs. It does NOT block
the hand-off from NHS Jobs, which lands on a fully-rendered Trac advert:

    jobs.nhs.uk/candidate/jobadvert/<ref>              (log in first — see below)
      -> "Apply for this job"  -> /ats-direct-apply
      -> "Continue to third party website"             (an <input type=submit>, NOT a link:
                                                        click_selector times out, use
                                                        `el.form.submit()`)
      -> apps.trac.jobs/job-advert/<id>?FromJobsNHS=1  ← renders, shows "Vacancy status: Open"
                                                        and an "Apply" button

Verified live on UKHSA Interaction Designer (NHS ref K9919-26-0233 -> Trac vacancy 8210652).
So sourcing/reading a Trac advert IS possible today via the aggregator; the remaining wall is
narrower than "Trac is unreachable".

**NHS Jobs login** (credentials are in the gitignored ats-credentials.csv, row `jobs.nhs.uk`):
the sign-in URL is `/candidate/auth/login` — NOT `/candidate/login`, which now returns
"The page you're looking for is no longer active". Fill `[name=username]` / `[name=password]`
and submit the FORM (`form.submit()`); the trusted click on `[name=submit-button]` times out.
On success it bounces back to the advert with the account menu in the header.

## Status: account exists, Trac is submittable

- **Do not** conclude Trac is halted because HTTP 403s — that is the anti-bot surface reacting
  to a bare `curl`, not to the anti-detect browser.
- **Do not** hammer it either. A Cloudflare managed challenge rendered in camofox: handle per `references/captcha-policy.md`.
- Sourcing route that avoids the search page entirely: take CSJ `external` adverts and follow
  their "Apply at advertiser's site" link, which deep-links straight to the vacancy.

## Why this matters beyond one vacancy

`classify_route.py` currently reports every one of these as `route=external`, note *"hands off
to the department's own ATS — needs an account"*, and the drivable count as `0 of N`. That note
is now stale for Trac specifically: the account exists, so a Trac-backed CSJ advert **is**
drivable. UKHSA alone had three on-lane SEO-grade roles in a single sourcing pass (Interaction
Designer, User Researcher, Cyber Security Operations Support Analyst), all £41,983–£52,113.

## ✅ RESOLVED 2026-09-02 — the login OTP is self-serve, no user relay needed

Trac's sign-in step (after email+password) sends a 6-digit one-time passcode by email
(`FrmOTP.otp` input, `id=FrmOTP.otp` / `FrmOTP.submit`) — **not** an authenticator-app TOTP, so
it does NOT need the user live in noVNC. It is genuinely single-attempt/short-lived regardless
of the "15 minutes" the email states — a prior session lost one to a delay while switching
tabs. The fix is to not switch away: trigger the code, poll IMAP from the SAME shell call, and
type it in the instant it returns.

**Working sequence (verified live 2026-09-02, UKHSA User Researcher, vacancy 8210381):**
1. Fill `#FrmCoreLogin-CandidateSignIn\.Email` / `\.Password` (native-setter + input/change),
   click `#FrmCoreLogin-CandidateSignIn\.Login`. Page re-renders in place with
   "We have sent a one time passcode to you..." and a `FrmOTP.otp` text input.
2. **Immediately**, in the same terminal session (do not navigate the tab away):
   ```python
   import sys; sys.path.insert(0,'scripts'); sys.path.insert(0,'sites/_common/scripts')
   import fetch_verification_code as vcode
   code = vcode.get_code(sender='trac', minutes=5, digits=6, wait_s=90, poll_s=4)
   ```
   `--sender trac` matches Trac's OTP mail (`noreply@recruit.trac.jobs`). Returned in well under
   90s in the live test.
3. Fill `#FrmOTP\.otp` with the code (native-setter + input/change), click `#FrmOTP\.submit`.
   Page re-renders logged in ("Dashboard / Applications / Find a job" nav + the account name).

Use `scripts/fetch_verification_code.py`'s shared `get_code()` for this — do NOT write a
Trac-specific IMAP poller; it is already generic over `sender`/`company`/`digits`/`want`. See
`references/shared-primitives.md`.

## Application form structure (verified live 2026-09-02, User Researcher 8210381)

The post-login apply flow is: pre-application questions (internal/external employee select,
immigration-status radio, privacy-policy checkbox, `#PreAppQuestions.Continue`) → a draft
application (`apps.trac.jobs/application/<APPID>`) with an option to **clone a previous Trac
application** (`#SelectStartingSource.SelectSource_AppForm`, auto-populates
`#SelectStartingSource.PreviousAppID` when there's exactly one prior app) or start blank.

**⚠️ Cloning a prior application does NOT actually copy field values into several sections —
it only marks them "Filled from past application" in the UI, which is misleading.** Opening
one of these sections (`#blk_<id>_ApplicationForm.Edit_Fieldset_<key>`) and clicking its
`#EditAppFieldset.Submit` with the form actually empty surfaces the REAL state: several
sections silently reverted to blank and have required fields. Verified empty despite the
"Filled from past application" label:
- **Personal details** — `Preferred employment type` (a required checkbox group,
  `#EditAppFieldset.personal-preferredemployment_Fulltime` etc.) was unchecked; mobile phone
  also blank.
- **Education & professional qualifications** — the whole row-based table
  (`#EditAppFieldset.education.gmrow_0.*`) was empty, not carried over.
- **Employer/activity history** — REQUIRED (`Other employers *`), and the row-based table
  (`#EditAppFieldset.otheremp.grrow_N.employment-*`, N=0..5, most-recent-first) was completely
  empty. This is the one that would silently block submit if you trusted the "Filled from past
  application" label and never opened it.
- **Equality and Diversity Monitoring** — DOB + gender/marital/ethnicity/sexual-orientation/
  religion selects (`#EditAppFieldset.equalops-*`, `#EditAppFieldset.personal-dob.*`) all blank
  and all required.
- **Disability**, **Care Leavers** — required selects, blank.

**Rule: open and resubmit EVERY "Filled from past application" section before trusting the
form is complete — don't just check for the "Not started" label.** The row status only flips
from `assignment_returned Filled from past application` to `assignment_turned_in OK` once you
open it, fill any genuinely-empty required fields, and click that section's own
`#EditAppFieldset.Submit`. All selects/checkboxes here are ordinary native form widgets — a
native-setter `.value`/`.checked` + `input`/`change` dispatch commits cleanly (this is a
server-rendered Trac form, not React — no desync issue seen).

## ⛔ Genuine hard stop found this session: References section needs real referee identity

The **References** fieldset requires `Referee's first name / surname / how do they know you /
period covered (from-to) / can they be approached before interview` for **all activity over the
past 3 years** — this is real third-party personal data (a specific person's name and contact
details who has agreed to vouch for the applicant) that does not exist in
`applicant-profile.md` or `ats-credentials.csv`, and fabricating a referee's identity would be
a straightforward integrity violation, not a gap to paper over. **Correctly a hard stop** — left
the section open/incomplete, application stays in Draft, logged `Blocked` with the concrete
missing-data reason rather than inventing a referee or leaving the row silently un-submitted
with no explanation. The unblock is the user supplying real referee details (name, relationship,
org, contact, and the period each referee covers, with no gaps across the last 3 years).
