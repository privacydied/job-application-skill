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

## ✅ LOGGED-IN MADGEX PATH — NOW TESTED END-TO-END (2026-07-18): IN-PLATFORM APPLY IS REAL, BUT THE SEND reCAPTCHA IS A HUMAN GATE
**SETTLED.** The logged-in in-platform apply path EXISTS and is **fully drivable headlessly UP TO
the Send** — but the Send fires a reCAPTCHA v2 that this camofox fingerprint cannot pass. Measured
on **REVIVA SOFTWORKS — Product Designer (10126456)**, a genuine on-profile London role, logged in:
- `apply.py --classify` → `in-platform` (on-page `#application-form`, `input[name=cv]`). NOT the
  guest external-redirect wall — the logged-in path really does keep you on `jobs.theguardian.com`.
- `apply.py` filled firstName/lastName/email from config, **uploaded the tailored CV** (bound to
  `input[name=cv]` — the `uploads/<file>.pdf` basename resolves against the shared upload dir),
  added the 171-word tailored cover, and unchecked all three marketing opt-ins. **All autonomous.**
- Clicking **"Send application"** fires an **INVISIBLE reCAPTCHA v2** which, for this fingerprint,
  escalated to an **image-grid challenge ("Select all images with crosswalks")**. The sanctioned
  two-phase `recaptcha.py solve-grid` ran (capture → VL tile read → click → verify) across **3
  verify rounds** — and reCAPTCHA **recycled the pixel-identical 9-tile set every round and never
  accepted, regardless of correct answers**. That is the classic **low-trust-fingerprint loop**:
  it is not testing the answer, it is refusing the client. Per CAPTCHA policy we do NOT grind it.

**CONSEQUENCE (this is the operational rule now):** in-platform Guardian = **STAGE-AND-HALT**. The
loop can fill+upload+cover+opt-out a Guardian in-platform job fully autonomously, then it MUST hand
the final **Send + reCAPTCHA to a one-time human noVNC pass** (`http://nasirjones:6080/vnc.html` —
a real pointer/trusted fingerprint clears the grid). Never log `Applied` off an un-confirmed Send;
`apply.py` returns exit 3 and records a resumable `blockers.py` entry + a `verdicts.py` terminal
negative so a degraded-window false "submitted" can't sneak in. `recaptcha.py check-type
jobs.theguardian.com` → `grid` (so future runs expect the challenge, not a silent pass).

Old note (pre-2026-07-18, kept for context): *Madgex boards commonly offer an in-platform "quick
apply" to logged-in candidates while sending guests to the employer ATS — so the guest-path
redirect does NOT prove the logged-in path also redirects.* ✅ Confirmed true: logged-in IS
in-platform. The only surprise was the Send reCAPTCHA being an unpassable loop for this fingerprint.

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

✅ PASSWORD LOGIN WORKS PROGRAMMATICALLY (verified end-to-end 2026-07-18, logged in). The page
carries a `[data-sitekey]` reCAPTCHA, but it PASSED for the camofox fingerprint (login
succeeded, no noVNC needed). It MAY intermittently present a challenge; if it ever silently
blocks (stays on `/signin/password`, no error), one noVNC pass clears it — but that was NOT
required here.

THE REAL GOTCHA (why an earlier attempt "looked blocked"): after the credential auth, Guardian
shows a **"You are signed in with <email>" + Continue** confirmation page. The **Continue is an
`<a>` whose React handler does NOT fire on a synthetic DOM `.click()`** (same class as the
apply-Send silent-click bug) — so a `.click()` no-ops and it looks stuck. `login.py` handles
it by reading the Continue `<a>`'s href and NAVIGATING to it directly (→ `/signin/refresh` →
`www.theguardian.com`, session established). `login.py --check` then reports `logged_in`.

Consequence for the loop: **Guardian is LOGGED IN.** Run `login.py` (idempotent — it detects an
active session and no-ops), then test the logged-in in-platform apply: re-open 2–3 sample job
URLs and check whether "Apply" stays on `jobs.theguardian.com` or still bounces to an employer ATS.
- Until that human test is done, Guardian yields ~0 confirmable submissions through the agent.
  Do not re-conclude "wall" every firing, and do not assume a logged-in unblock exists.

## Sourcing still works
The Guardian **feed** (`sites/jobs.theguardian.com/scripts/feed.py`) still sources
candidates fine; only the *submit* path is walled. So Guardian contributes to the
candidate pool but yields ~0 confirmable submissions without employer-account creds.

## Honest ceiling (strategic, confirmed 2026-07-17)
Across the four reachable hard boards (CSJ / Guardian / NHS / MI5-MI6), the only multi-page
board the agent can FULLY drive to a *confirmed* submission is **CSJ TAL** (S1+S2). Guardian
(logged-in) is drivable to a *staged* in-platform application but **not to a confirmed Send** — the
Send reCAPTCHA v2 loops for this fingerprint (see the tested finding above), so its final step is a
human noVNC gate, same halt class as CSJ's occasional challenge; NHS feed returns only clinical
roles (0 on-profile for a design/research CV);
MI5/MI6 applicationtrack autofill never submits (human-only final vetting page). Realistic
confirmed submissions from in-scope boards ≈ **4** (all CSJ). Reaching a 477 target needs accounts
for the 4 account-gated boards (GCHQ / Parliament / TfL / BBC) — that unblock is the user's to
provide (email/CAPTCHA), not the agent's.
