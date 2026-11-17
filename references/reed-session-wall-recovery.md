# Reed session-wall recovery (verified 2026-07-18)

## Symptom
`scripts/reed_apply.py <id>` returns `LOOP-END` even though the Apply button is present
and a manual `click_apply_now()` works. The apply modal shows:

    Session expired
    Your session has expired.
    Please click on the button to reload the page.
    [Refresh]

Clicking **Refresh** reloads the page but the session is STILL expired on the next
navigation — the auth cookie is dead, not just a transient modal.

## Why
Reed has no password-login form. The SignIn page (`/account/SignIn?returnUrl=%2F`)
renders only a passwordless button that emails a 4-digit code. Both `feed.py` and
`reed_apply.py` assume an already-authenticated profile and ship no re-login script, but
the code lands in the applicant mailbox and `scripts/fetch_verification_code.py` reads it
over IMAP. A dead session is therefore self-serve, not a human-only wall, provided the
`imap...` row in `ats-credentials.csv` is live and Reed uses that same mailbox. Prefer the
Gmail address whose app-password row is configured — personal Outlook IMAP no longer
accepts passwords.

## Diagnosis (one call)
```python
import sys; sys.path.insert(0,'sites/_common/scripts'); import cfx
cfx.navigate("https://www.reed.co.uk/jobs/ui-designer-design-systems/<id>"); time.sleep(9)
modal = cfx.evaluate("""(function(){var m=document.querySelector('[class*=modal],[role=dialog]');
  return m? m.innerText.replace(/\\s+/g,' ').slice(0,120):'NO MODAL';})()""")
print(modal)   # -> "Session expired ..." == session wall, NOT a flake
```

## Self-serve sign-in (verified) — run `python3 scripts/reed_login.py`
The canonical script does every step below (camofox tab by default; `--cdp <url>` drives the
local-browser fallback; `--if-needed` is a no-op when already signed in). It prints `LOGIN_OK`
or a named failure (`STUCK_NO_EMAIL_FIELD`, `NO_FRESH_CODE`, `VERIFY_DISABLED`,
`REDIRECT_TIMEOUT`, `SESSION_NOT_ESTABLISHED`). The steps are the contract it enforces:
0. Clear Reed cookies and storage FIRST (sign-out URL + cookie/storage wipe). A stuck OTP step
   from an earlier attempt otherwise hides `#signin_email`. camofox has no clear-cookies
   endpoint, and `DELETE /sessions/<uid>` would log out every other board, so the script stays
   Reed-scoped.
1. Open `https://www.reed.co.uk/account/SignIn?returnUrl=%2F`. If the page is blank on
   `/authentication/login/callback`, clear the context cookies and start at
   `https://www.reed.co.uk/` first, then reopen SignIn. If clearing cookies still leaves a
   blank callback, start a fresh persistent browser profile (new user-data-dir and debugging
   port) instead of fighting the stuck session.
   Reed also exposes `Continue with Google`. Use it only when the controlled browser profile
   already holds an authenticated Google session, or the vault has a saved login for that origin.
   Never request or accept a Google password, 2FA code or recovery answer in chat; with no
   authenticated session, use the email-code path below or ask the user to sign in once in the
   profile the agent drives.
2. Fill the email field with the mailbox backed by the configured IMAP row, then click
   the passwordless button (`#signin_button_passwordless_signin_jobseeker_web_view`).
3. Read the 4-digit code. Fetch the code from the initial passwordless request first; do NOT
   click "Send code again" before the first fetch, because that invalidates the code the
   reader is about to return. If a fresh code is genuinely needed, request it explicitly,
   record the request time, and select the Reed email whose `Date` is AFTER that time — not
   merely the newest 4-digit token in the mailbox. Unconsumed stale codes in the same inbox are
   otherwise indistinguishable from the live one and Verify will accept the digits but the
   redirect will land back on sign-in.
   Reuse the shared primitives for the mechanics (`vcode._body_text`, `vcode._extract`,
   `vcode._ledger_consume`, `email_ingest._connect`); do not fork a second code extractor.
   Do NOT clear `.vcode-consumed.json` casually: clearing it makes already-spent codes eligible
   again and reintroduces the stale-code failure. Clear it only when every entry is known to be
   consumed and no live code exists.
4. Commit each digit through React's native value setter and dispatch `input` + `change`:
   `Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(el,ch)`.
   Programmatic `fill()` alone leaves Verify disabled. Real keystrokes (`click`,
   `keyboard.type(ch)`, `Tab`) are the fallback, not the primary. Check
   `#passwordless_verify_code.is_enabled()` before clicking it, then wait for the URL to leave
   `login` before declaring success.
5. Click Verify Code, wait for the redirect, and confirm the page shows "Sign out" and
   "Jobs applied for". Re-verify with the diagnosis snippet above before resuming
   `reed_apply.py`.

## New account registration
The same code also serves signup. After verification Reed asks for a CV and a few profile
fields: upload the local CV to the file input, then fill name/phone/job title, select
right-to-work and country, postcode, desired salary and location from the applicant
profile. Leave WhatsApp alerts off. Click Create account and verify the account page
shows the applicant name and a zero applications count.

## Easy-Apply submit and proof
Click the first visible `Apply now` button on the job page after dismissing the cookie banner. A stale "Session expired" dialog often
coexists with the real one — select the dialog whose text contains `Submit application`,
not the first `[role=dialog]`. After submitting, verify on
`https://www.reed.co.uk/account/jobs/applications` that the count rose and the
company/title is listed; save that page as `confirmation.png` and pass it to
`log-application.py --proof`. A submit click without this check is not evidence. Use the
employer string from that applications page in the tracker row — Reed often shows a recruiter
brand that differs from the queue's `company` field.

A session can expire after several submissions in one run. Re-login with a fresh code
rather than treating each subsequent role as failed; re-check the applications page after
each batch so no submission is missed or double-driven. If a fresh session still returns
the "Session expired" dialog on specific postings, that is the posting's stricter apply
endpoint, not the account session: skip those postings and move on instead of re-loginning
per role.

## Local-browser driver (working fallback)
When the sanctioned browser path cannot hold the session, drive a persistent local browser:
launch Edge/Chrome with `--remote-debugging-port` and reuse the same process across short
scripts via `connect_over_cdp('http://localhost:9222')`. Stage the CV in `~/` and attach it
with CDP `DOM.setFileInputFiles` (see `references/local-apply-fallback.md`).
- For the 4-digit code, use the native React setter from the sign-in step; keyboard typing is
  the fallback. Verify the button is enabled before clicking it.
- Before clicking Apply now, dismiss the cookie banner (`Reject All` / `Accept all cookies`);
  its overlay silently eats clicks on the job-page button. Use the FIRST visible `Apply now`
  button — the last match can be a hidden stub whose click times out. When several
  `[role=dialog]` nodes exist, pick the one whose text contains `Submit application`, not the
  first dialog and not a stale session-expired one.
- Keep batches small. After each batch read `account/jobs/applications`, match the
  company/title and count, screenshot it as `applications/<company>-<role>/confirmation.png`,
  and log only then. A session gone stale is a re-login, not a failed role. Re-login with a
  fresh date-verified code between batches; do not churn browser profiles unless the auth
  callback itself is stuck.

## Standing apply preferences
- A CAPTCHA ends work on that posting; never bypass it. The user prefers SKIP-AND-CONTINUE: mark
  the posting retryable and move to the next on-profile role instead of pausing the run for a
  human solve. Use sanctioned solvers only when explicitly asked.
- Keep driving the channel that is producing verified applications. Skip postings it cannot
  serve (dead session, missing Apply button) rather than reconfiguring infrastructure mid-run;
  stop at the submission cap and report.
- A login-loop failure is an OTP/session problem, not a missing account. Do not create a second
  Reed account to work around it; if a fresh profile plus a cleared `.vcode-consumed.json` still
  cannot enable Verify Code, stop re-login attempts, report the blocker, and ask the user to sign
  in once in the driven profile.

## Do NOT
- Do NOT keep re-running `reed_apply.py` against a dead session — every role returns
  `LOOP-END`. Re-login with a fresh code, then resume.
- Do NOT hand-write a `/tmp/reed_*` re-login scraper — use `scripts/reed_login.py` and extend
  it in place.
- Do NOT drive a row whose `Apply now` button is absent; that posting is already applied
  or closed.
- Do NOT log `Applied` from a submit click alone. Confirm on the applications page that
  the count rose and the company/title is listed, then save that page as proof.

## Timing hardening (already in reed_apply.py)
Initial settle before clicking Apply now is 9s (Reed lazy-renders the button via JS; 5s
raced it → `LOOP-END`). If `LOOP-END` recurs *with a healthy session*, it's a different
role-specific wall, not this one — inspect the modal content per above.
