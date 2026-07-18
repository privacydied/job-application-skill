# Guardian (jobs.theguardian.com) — apply-path reality, 2026-07-17

## What changed
The SKILL.md board-reality table historically described Guardian as *"on-page form
(name/email/CV) + reCAPTCHA v2 — fastest of the hard boards."* As of 2026-07-17 that is
**no longer the flow**. Clicking **"Apply on website"** on a Guardian job now lands on
`jobs.theguardian.com/external-redirect-registration?JobId=…` and then **redirects to the
employer's own ATS** — e.g. Accenture → `accenture.com/gb-en/careers/jobdetails?id=…`,
Deloitte, Electronic Arts, etc. The employer ATS is a full **account-gated** application
(many fields, checkboxes, often its own CAPTCHA/account creation).

There is also a "No thanks, continue to apply" link → `jobs.theguardian.com/apply/<id>/…`
which simply forwards to the same employer ATS. No guest on-page CV+reCAPTCHA form remains.

## Consequence for the autonomous loop
Guardian roles are now effectively **account-gated per role** — the same wall class as
GCHQ / Parliament / TfL / BBC. The agent cannot self-create those employer accounts
(CAPTCHA / email verification it can't read). Treat a Guardian "Apply on website" redirect
to a third-party domain as an **account wall**: log `Blocked` with the redirect target,
do NOT attempt to drive the employer ATS.

## Verification recipe (so you don't waste a pass)
1. Open the Guardian job URL `https://jobs.theguardian.com/job/<id>/<slug>/`.
2. Find the apply link; if its `href` contains `external-redirect-registration` or
   `apply/<id>` that resolves to a non-guardian.com domain → account wall (guest path).
3. Only if the form renders ON `jobs.theguardian.com` as a guest (name/email/CV +
   reCAPTCHA) is it drivable. As of 2026-07-17 no such guest form was observed.

## ⚠️ LOGGED-IN MADGEX PATH — UNTESTED AND UNTESTABLE FROM THE AGENT (2026-07-17)
A `jobs.theguardian.com` (Madgex) credential row **exists** in `ats-credentials.csv`
(email + password present). Madgex boards commonly offer an in-platform "quick apply"
(saved profile + CV) to *logged-in* candidates while sending *guests* out to the employer
ATS. So the guest-path redirect does NOT prove the logged-in path also redirects.

LOGIN — ✅ PASSWORD LOGIN WORKS (CORRECTED 2026-07-18; the OLD "OTP-only, agent can't log in"
claim was WRONG). `profile.theguardian.com/signin` DEFAULTS to email-OTP ("Continue with
email" → `/passcode` → a one-time code the agent can't read), **but a "Sign in with a password
instead" link on the signin page goes to `profile.theguardian.com/signin/password` (email +
PASSWORD fields — verified present).** The reason the agent kept "defaulting to OTP" is that
the link is a plain `<a>` that camofox's **a11y SNAPSHOT does not surface** — a DOM query
finds it instantly. So:
- **Log in with the SHIPPED driver — `python3 sites/jobs.theguardian.com/scripts/login.py`.**
  It goes DIRECT to `/signin/password` (bypassing OTP + the snapshot-invisible link), fills the
  `jobs.theguardian.com (Madgex)` creds, submits, and hands the reCAPTCHA to noVNC (exit 3).
  Manual equivalent if you must: navigate to
  `https://profile.theguardian.com/signin/password?signInEmail=<email>`, or native-click the
  link via DOM (NOT the snapshot):
  `[...document.querySelectorAll('a')].find(e=>/password instead/i.test(e.innerText)).click()`.
- Once logged in, THE in-platform-apply hypothesis is finally testable by the agent: re-open
  2–3 sample job URLs and check whether "Apply" stays on `jobs.theguardian.com` (in-platform)
  or still bounces to a non-guardian.com employer ATS.

⛔ BUT the password-login SUBMIT is gated by a **reCAPTCHA** (`[data-sitekey]` on
`/signin/password`). Verified 2026-07-18: with valid Madgex creds filled and "Sign in"
clicked, the page stayed on `/signin/password` with NO error message and NO visible challenge
— the reCAPTCHA **silently blocked** the submit (the same camofox-fingerprint-distrust wall
documented for Guardian's apply-submit reCAPTCHA — the widget won't issue a token for this
client). So the LINK problem is solved (reach the password page via the direct URL / DOM
click) and the creds are accepted, but programmatic sign-in still can't clear the reCAPTCHA.

Real unblock (single, human): **log in ONCE via noVNC** (`http://nasirjones:6080/vnc.html`)
on the `/signin/password` page — a real pointer passes the reCAPTCHA behavioural score — then
the session persists in the camofox PROFILE, and the agent can finally test/drive the
logged-in in-platform apply. (The sanctioned `recaptcha.py` v2 solve is worth ONE attempt, but
this widget has historically distrusted the fingerprint and looped without a token, so don't
grind it — hand to noVNC.)

Consequence for the loop: Guardian login is reachable (password page, not OTP), but the final
reCAPTCHA needs a human noVNC pass once; after that the logged-in apply path is testable.
- Until that human test is done, Guardian yields ~0 confirmable submissions through the agent.
  Do not re-conclude "wall" every firing, and do not assume a logged-in unblock exists.

## Sourcing still works
The Guardian **feed** (`sites/jobs.theguardian.com/scripts/feed.py`) still sources
candidates fine; only the *submit* path is walled. So Guardian contributes to the
candidate pool but yields ~0 confirmable submissions without employer-account creds.

## Honest ceiling (strategic, confirmed 2026-07-17)
Across the four reachable hard boards (CSJ / Guardian / NHS / MI5-MI6), the only multi-page
board the agent can FULLY drive to a confirmed submission is **CSJ TAL** (S1+S2). Guardian →
employer-ATS wall; NHS feed returns only clinical roles (0 on-profile for a design/research CV);
MI5/MI6 applicationtrack autofill never submits (human-only final vetting page). Realistic
confirmed submissions from in-scope boards ≈ **4** (all CSJ). Reaching a 477 target needs accounts
for the 4 account-gated boards (GCHQ / Parliament / TfL / BBC) — that unblock is the user's to
provide (email/CAPTCHA), not the agent's.
