# Account-wall verification protocol (2026-07-18)

When a board is flagged "account needed" / "self-register where no CAPTCHA", don't
REPORT it as a wall on a guess. Probe it concretely — most are one of three outcomes,
and only the third is a true wall:

1. **Self-registerable (no CAPTCHA, no email-OTP).** Create the account with the real
   email + a strong generated password, store `site,email,password,date` in
   `ats-credentials.csv`, continue. (This is the skill's authorized move.)
2. **Email-OTP login (human-only).** Login sends a one-time code to the inbox the agent
   can't read → genuinely walled *for the agent*; report it ONCE as needing human login,
   don't loop on it.
3. **No self-registration path at all.** Login page exposes only "Existing user login" /
   "Forgotten password" → account is provisioned by the employer/HR, not self-serve.
   Report once as a wall.

## Concrete probes that worked

**Parliament (MHR Web Recruitment / iTrent)** — `hrhoc.parliament.uk/ce0912li_webrecruitment`.
Open the job-search board, find the `Existing User Login` link (`ETREC109DF.open?…`), open
it. If the page renders ONLY "Existing user login" + "Forgotten Password" with NO
"create account / register / new candidate" link → outcome #3. (Confirmed 2026-07-18:
Commons had 10 live roles but all off-tier / non-design; PDS on-profile stream = 0; no
self-reg path.)

**TfL / BBC (SuccessFactors RMK)** — `london-gov.jobs2web.com/tfl/` and `careers.bbc.co.uk`.
The job detail page's `Apply now` deep-link (`/talentcommunity/apply/<id>/`) often 302s back
to the RMK homepage or an error page when there's no session — that's the account gate, not
a broken URL. Look for a `Log in to Profile` / `Create Account` link on the job page. If
only `Log in` exists (no `Create Account` / `Register`) → outcome #3. (Confirmed 2026-07-18:
TfL apply redirected to homepage; BBC apply hit an exception page with only "Log in to
Profile".)

**Guardian (Madgex)** — login is `profile.theguardian.com/signin` → "Continue with email" →
`/passcode` (email-OTP). No password field. Outcome #2 (human-only). The guest apply path
redirects to the employer ATS; the logged-in "quick apply" path is UNTESTABLE by the agent
because login needs the inbox OTP. Don't re-conclude "wall" every firing, but also don't
assume a logged-in unblock exists.

## Reusable snippet — "does this board offer self-registration?"

```python
import sys; sys.path.insert(0,'sites/_common/scripts'); import cfx, time
cfx.goto(<board_login_or_apply_url>, verify=False); time.sleep(4)
links = cfx.evaluate('''JSON.stringify([...document.querySelectorAll('a,button')]
  .map(a=>({t:(a.innerText||'').trim().slice(0,45), h:(a.getAttribute('href')||'')}))
  .filter(x=>/register|create account|sign up|new (user|candidate)|no account/i
            .test(x.t+x.h)))''')
# empty list + only "Existing user login"/"Forgotten password" present  =>  outcome #3 (wall)
# "Continue with email" + passcode  => outcome #2 (email-OTP, human-only)
# "Create Account" link  => outcome #1 (probe it; if no CAPTCHA, self-register)
```

## Reporting discipline
State each walled board ONCE with its specific unblock (e.g. "Parliament: login page has no
self-register link — needs an HR-provisioned or human-created account"). Do NOT re-attempt
the same board every firing, and NEVER pad the 477-style target with senior/off-tier/easy-
apply roles to fake progress — that violates the no-fabrication rule.
