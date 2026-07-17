# Board-wall verification — guest path is NOT proof of a wall

## The mistake this prevents
A board that redirects to an employer ATS (or shows "create an account") **as a guest**
is commonly logged `Blocked` as an "account wall". That conclusion is only half-true: many
Madgex / SuccessFactors / arbetsformedling boards offer an **in-platform "quick apply"**
(saved profile + CV) to *logged-in* candidates while bouncing *guests* out to the employer
ATS. A guest-path redirect therefore does **not** prove the logged-in path also walls.

## Rule (embed in the loop)
1. When a board's apply path looks account-gated as a guest, check `ats-credentials.csv`
   for a row for that board **before** logging `Blocked`.
2. If a credential row exists -> **test the logged-in path** (log in, re-open 2-3 sample
   job URLs, check whether "Apply" stays on the board's own domain or still bounces out).
3. If login itself is impossible from the agent (email-OTP you can't read, CAPTCHA you
   can't solve) -> log it as **`untested-untestable`**, not `Blocked`. State explicitly:
   "guest path walls; logged-in path untested because login needs <blocker>." Do NOT
   re-conclude "wall" every firing once flagged.
4. Reconcile docs: a board's `sites/<board>/NOTES.md` may describe an OLD apply flow that
   the live guest path has since superseded. Prefer `references/<board>-board-reality.md`
   when present, but treat BOTH as guest-path observations unless the logged-in path was
   actually exercised.

## Worked example — Guardian (jobs.theguardian.com / Madgex), 2026-07-17
- Guest path: "Apply on website" -> `external-redirect-registration` -> employer ATS
  (accenture.com, etc.) = account-gated. True.
- Credential row **exists** in `ats-credentials.csv` (email + password present).
- Login is **email-OTP gated**: `profile.theguardian.com/signin` -> "Continue with email"
  -> `profile.theguardian.com/passcode` -> *"We've sent a temporary verification code to
  you@example.com."* No password field -- email + one-time code.
- Agent cannot read `you@example.com` -> **cannot complete Guardian login** -> cannot test
  whether logged-in flips any role back to in-platform apply.
- Correct status: guest-path-verified wall; **logged-in path untested-untestable from
  agent**. Not a settled wall, not a realisable unblock. Human must run the logged-in test
  (real browser + inbox OTP) to settle it.
- Docs reconciled: `sites/jobs.theguardian.com/NOTES.md` Apply section marked STALE;
  `references/guardian-board-reality.md` gained the "logged-in path untestable" section.

## Why this matters for the 477 target
CSJ TAL is the only multi-page board the agent can FULLY drive to a confirmed submission.
Guardian, NHS (0 on-profile), MI5/MI6 (autofill never submits) and boards 5-8 (no account)
are the rest. The single highest-leverage unblock is **creating the account-gated board
accounts** (or running the Guardian logged-in test) -- that needs the user's email/CAPTCHA
access, not the agent's. Report it once, with the specific unblock; do not pad the count.
