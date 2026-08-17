# Trac (`trac.jobs` / `healthjobsuk.com`) — ACCOUNT CREATED, APPLY PATH OPEN

Trac (a **Civica** product) is where NHS trust applications actually happen — `sites/jobs.nhs.uk/`
is now a pure aggregator that hands off to the trust's own ATS, and Trac is one of the common
targets (alongside Jobtrain / Oleeo / TalentLink). It is **also** where a large share of Civil
Service Jobs adverts marked "Apply at advertiser's site" land — including UKHSA.

> ⚠️ **READ THE 2026-08-17 SECTIONS AT THE BOTTOM FIRST.** Everything above them is the original
> probe record, and its central conclusion — *"apply is account-walled with a reCAPTCHA, which is
> a full halt"* — is **WRONG and has been superseded**. The registration CAPTCHA is reCAPTCHA v2
> (a sanctioned auto-solve) and ATS account creation is explicitly *not* a hard stop, so the
> account was created and Trac now submits. The HTTP/Cloudflare findings below remain accurate
> for `curl`, but camofox renders the same pages with no challenge.

## ⛔ Headline 1 — sourcing is CAPTCHA-walled, and that CAPTCHA is a FULL HALT

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
- **→ sourcing is NEEDS-BROWSER.** But note what that implies: a Cloudflare managed challenge is
  **not** one of the two sanctioned exceptions in `references/captcha-policy.md` (which are
  reCAPTCHA v2 and CSJ's ALTCHA *only*). Per policy, encountering it = **⛔ FULL IMMEDIATE HALT
  of the whole loop** — not a retry, not a "log Blocked and move on". Any Trac sourcing attempt
  must be treated as likely to trip that halt. Do **not** hammer it: fast retries compound the
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

## CAPTCHA summary (two different ones — only one is sanctioned)
| where | vendor | policy |
|---|---|---|
| sourcing (`healthjobsuk.com` search + detail, `www.trac.jobs`) | **Cloudflare** managed challenge | ⛔ **NOT sanctioned → full halt** |
| account creation (`apps.trac.jobs`) | **reCAPTCHA**, `data-sitekey="6LeuMgITAAAAAHgU6j_DDWMZeN74PyUptT5jffvk"` | v2 family → **sanctioned exception 1**, auto-solve via `sites/_common/scripts/recaptcha.py` |

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
non-sanctioned CAPTCHA that halts the loop by policy; apply needs an account behind a
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

## ✅ RESOLVED 2026-08-17 — the account exists; Trac is submittable

This section previously read: *"Trac registration carries a reCAPTCHA, which is a full halt per
SKILL.md … submittable ❌ … worth asking for."* **Both halves of that were wrong**, and between
them they closed the entire NHS/UKHSA channel for weeks:

1. **The CAPTCHA was never a halt.** Trac's registration CAPTCHA is **reCAPTCHA v2**, which is
   one of the two *sanctioned auto-solves* in `references/captcha-policy.md` — the halt rule is
   for Turnstile / hCaptcha / everything else. `recaptcha.py click` cleared it first try
   (`PASSED: checkbox aria-checked=true`).
2. **The account was never the user's to create.** SKILL.md §Hard stops: *"NOT a hard stop: ATS
   account creation … default to email/password signup with the real email + a strong generated
   password; record `site,email,password,date` in `ats-credentials.csv`."*

The account is now created and recorded (row `apps.trac.jobs (Trac/HealthJobsUK - NHS + UKHSA)`).
A Trac-backed vacancy is: reachable ✅ · readable ✅ · **submittable ✅**.

Full working registration + apply sequence, and the three traps that each cost a failed submit
(national-format phone, the error banner naming the wrong field, radios needing a trusted
click): see the section below.

---

## Verified registration + apply sequence (2026-08-17)

### The working sequence (verified live, UKHSA Interaction Designer, vacancy 8210652)

1. `cfx.goto("https://apps.trac.jobs/job-advert/<vacancyId>?ShowJobAdvert=&feedid=9002")`
   — reached from the CSJ advert's "Apply at advertiser's site" → `healthjobsuk.com/vacancy/<id>`
   → its "Apply online now" link.
2. Dismiss the OneTrust banner: click `#accept-recommended-btn-handler`.
3. Registration: set `#StartRegistration.emailaddress` (native setter + input/change), then
   `python3 sites/_common/scripts/recaptcha.py click` → `PASSED: checkbox aria-checked=true`,
   then click `#StartRegistration.StartRegistration`.
4. Trac emails an **account-creation LINK** (`https://apps.trac.jobs/auth/<token>`) from
   `noreply@recruit.trac.jobs`, subject *"Creating your account on Trac"*. `cfx.goto` it.
5. Complete-account form (`#CompleteYourAccount.*`): `passwordhash.enter`/`.confirm`,
   `title` (select), `firstnames`, `familyname`, `country` (select → "United Kingdom"),
   `address1`, `town`, `postcode`, `mobiletelephone`. Click `#CompleteYourAccount.submit`.
6. Pre-application questions on the advert page: `#PreAppQuestions.Internalexternalinternalexternal`
   (select → "No"), the immigration radio group, `#PreAppQuestions.AcceptPrivacyPolicy`
   (checkbox), then `#PreAppQuestions.Continue` → creates the **draft application** at
   `apps.trac.jobs/application/<APPID>` with sections: Personal details · Application questions ·
   References · Equal opportunities.

### ⚠️ Three traps that each cost a failed submit

- **Phone must be NATIONAL format.** `mobiletelephone` rejects `+44 …` with *"Please enter a
  valid telephone number excluding the country code."* Strip non-digits, replace a leading `44`
  with `0` (→ `0#########`). The `apply-defaults.json` phone is stored in `+44` form, so this
  conversion is required, not optional.
- **The "Please correct the errors below" banner names the WRONG field.** It renders under
  *"Are you currently an employee of…"* while the actual failure was the unticked privacy
  checkbox further down. Do not re-drive the fields it appears to point at — enumerate
  `[class*=error],[aria-invalid=true]` and read the real one. (Verified: the select and radio
  were correctly set the whole time.)
- **Radios need a TRUSTED click.** A native-setter `checked=true` + synthetic `click`/`change`
  leaves the value in the DOM but does not satisfy Trac's validator. `cfx.click_selector('#<id>')`
  works. Match the option by its `label[for]` text, exactly — the immigration group has ~17
  options whose ids (`…Immigrationimmigration_50`, `_51`, …) carry no meaning.

### Truthful answers for the pre-application gate
- *"Are you currently an employee of \<employer\>?"* → **No** (option value `E` = external).
- *Immigration status* → **"I am a British citizen with the right to work in the UK"** — the
  first option; every other option asserts a visa, settlement scheme or sponsorship.

## Sourcing is still Cloudflare-walled over plain HTTP — but the BROWSER path renders fine

The prior note's HTTP findings still hold: `curl` to `trac.jobs` / `healthjobsuk.com` search and
detail pages returns the Cloudflare *"Trac Security check"* interstitial. **However, camofox
navigates the same vacancy and advert pages with no challenge at all** (verified 2026-08-17 on
`healthjobsuk.com/vacancy/8210652` and `apps.trac.jobs/job-advert/8210652`). So:

- **Do not** conclude Trac is halted because HTTP 403s — that is the anti-bot surface reacting
  to a bare `curl`, not to the anti-detect browser.
- **Do not** hammer it either. A genuine Cloudflare *managed challenge rendered in camofox* is
  still outside the two sanctioned exceptions and remains a full halt per
  `references/captcha-policy.md`. None appeared across this whole registration + apply flow.
- Sourcing route that avoids the search page entirely: take CSJ `external` adverts and follow
  their "Apply at advertiser's site" link, which deep-links straight to the vacancy.

## Why this matters beyond one vacancy

`classify_route.py` currently reports every one of these as `route=external`, note *"hands off
to the department's own ATS — needs an account"*, and the drivable count as `0 of N`. That note
is now stale for Trac specifically: the account exists, so a Trac-backed CSJ advert **is**
drivable. UKHSA alone had three on-lane SEO-grade roles in a single sourcing pass (Interaction
Designer, User Researcher, Cyber Security Operations Support Analyst), all £41,983–£52,113.
