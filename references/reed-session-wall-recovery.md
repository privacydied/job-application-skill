# Reed session recovery

## Symptom
`scripts/reed_apply.py <id>` returns `LOOP-END`, and the apply modal shows "Session expired"
again after Refresh. Confirm the session is dead on the account page, not the homepage:
`https://www.reed.co.uk/account/jobs/applications` must show "Sign out" and applied cards.
A "Session expired" modal on a valid account page is a posting or tab problem, not a dead session.
See `sites/reed.co.uk/NOTES.md`.

## Re-login: `python3 scripts/reed_login.py`
| Flag | Effect |
|---|---|
| (none) | camofox tab (source `.jobenv.run` first) |
| `--if-needed` | exit 0 if already signed in |
| `--cdp http://localhost:9222` | local Edge/Chrome over CDP |
| `--email ADDR` | override address (default: `reed...` row, else the IMAP row address) |
| `--wait 90` `--resends 1` `--skew-s 60` | code wait, explicit resends, Date skew |

Needs: a live `imap...` row in `ats-credentials.csv` for the mailbox Reed sends to.
If the account has a password and `#signin_password` renders, the password form in
`sites/reed.co.uk/NOTES.md` also works.

### What it does (the contract — keep these when editing)
1. **Clear cookies first.** Sign-out URL, then expire Reed cookies and clear storage.
   Only Reed: `DELETE /sessions/<uid>` would log out every board.
   If `#signin_email` is still hidden, click "Back to email".
2. **One explicit request.** Note the mailbox max IMAP UID and the time, then click
   `#signin_button_passwordless_signin_jobseeker_web_view`. Never click "Send code again" before
   the first fetch: it invalidates the code.
3. **Pick the code by request time.** Accept only a Reed email with UID > the noted UID and
   `Date` >= request time − `--skew-s`. An email with no Date is rejected. Resend only after
   `--wait` with no code, with a new UID/time baseline.
4. **Commit digits** (`#first-otp-digit` … `#fourth-otp-digit`) with React's native value
   setter + `input`/`change` events. Use keystrokes (click, type, Tab) only if
   `#passwordless_verify_code` is still disabled.
5. **Wait for the redirect.** After Verify, wait up to 30 s for the URL to leave `login`/`signin`.
   Then check the account page for "Sign out".

### Output
| Print | Exit | Next step |
|---|---|---|
| `LOGIN_OK` | 0 | resume `reed_apply.py` |
| `NO_ADDRESS` / `NO_IMAP` | 1 | fix the `ats-credentials.csv` rows |
| `STUCK_NO_EMAIL_FIELD` | 2 | fresh browser profile, or user signs in once |
| `NO_FRESH_CODE` | 3 | check the mailbox address / forwarding |
| `VERIFY_DISABLED` | 4 | inspect the digit inputs; extend `commit_code` |
| `REDIRECT_TIMEOUT` / `SESSION_NOT_ESTABLISHED` | 5 / 6 | rerun once; then report |

Tests: `tests/test_core.py::TestReedLoginFreshCode`.

## Rules
- Run it at most twice per dead session, then report and move to another board.
  Do not create a second Reed account.
- Do not clear `.vcode-consumed.json`.
- Extend `scripts/reed_login.py` in place. Do not write `/tmp/reed_*` login scripts.
- Re-check `account/jobs/applications` after each small batch. A session can expire mid-run.

## Easy-Apply submit and proof
- Dismiss the cookie banner first; it blocks the Apply button.
- Click the first visible `Apply now`. In the modal, use the `[role=dialog]` that contains
  `Submit application`.
- Skip a row with no `Apply now`: it is closed or already applied.
- Proof: the applications count rose and the company/title is listed. Save it as
  `applications/<company>-<role>/confirmation.png`, then `log-application.py --proof`. Use the
  employer name from that page.
- If one posting still shows "Session expired" on a fresh session, skip that posting.
- CAPTCHA: skip the posting and continue. Never bypass it.
- `reed_apply.py` waits 9 s before Apply now. `LOOP-END` on a healthy session = a
  posting-specific wall; inspect the modal.
- Local-browser file attach: `references/local-apply-fallback.md`.

### Local-browser apply lane (validated fallback)
When the camofox Reed path is unavailable, drive Easy Apply in a local Edge/Chrome with a
persistent profile and remote debugging: launch once with `--remote-debugging-port=<port>` and
a stable user-data dir, connect with Playwright `connect_over_cdp`, and sign in with
`scripts/reed_login.py --cdp http://localhost:<port>`. For each queued Reed URL: dismiss the
cookie banner, click the first visible `Apply now`, click `Submit application` in the
`[role=dialog]` that contains that button, then verify on `account/jobs/applications` that the
application count rose and the employer is listed before logging with `--proof`. Recheck the
account page after every small batch; a fresh sign-in is required when a modal reports
"Session expired". Do not create a second Reed account to work around session expiry.
