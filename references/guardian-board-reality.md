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

BUT the login itself is **email-OTP gated**: `profile.theguardian.com/signin` →
"Continue with email" → `profile.theguardian.com/passcode` → *"We've sent a temporary
verification code to you@example.com"*. There is NO password field — it's email + one-time
code. The agent cannot read that inbox, so it **cannot complete Guardian login** and
therefore **cannot test whether logged-in flips any role back to an in-platform apply**.

Consequences for the loop:
- The "Guardian = account wall" conclusion is **guest-path-verified only**. Do NOT treat it
  as a settled wall for logged-in candidates — it is *untested*, not *proven*.
- It is also **not** an unblock the agent can realise: login needs the OTP from
  `you@example.com`, which the agent cannot read.
- To actually test the logged-in hypothesis, a human must log in (via noVNC / real browser
  using the inbox OTP) and then re-open 2–3 sample job URLs to check whether "Apply" stays on
  `jobs.theguardian.com` (in-platform) or still bounces to a non-guardian.com domain.
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
