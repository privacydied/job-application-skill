# Greenhouse submission gate: emailed verification code

## The finding (verified live, 2026-07-20)

Greenhouse job-boards (`job-boards.greenhouse.io/<company>/jobs/<id>`) now **gate
submission behind an 8-character verification code emailed to the applicant**. After the
form is 100% filled and the Submit button is clicked, the page shows:

> "A verification code was sent to <applicant-email>. To submit your application,
>  enter the 8-character code to confirm you're a human."

until the code is entered, **the application is NOT submitted** and no confirmation
appears. `atsform.submit` then reports `UNCLEAR: no success text and no errors` and the
driver logs `Blocked` — NOT `Applied`.

This is the real blocker for the whole account-less Greenhouse channel. It is NOT a
form-fill bug: every text field, CV chip, and react-select combobox binds correctly;
only the code stands between a filled form and a truthful `Applied` row.

`applicationtrack.com` (MI5) and other Greenhouse-backed flows show the same pattern.

## Why this was misdiagnosed for 30 turns

The skill's `references/greenhouse-ats-quirks.md` (§4/§5) documents the Remix-EEO
combobox gap as THE Greenhouse blocker. That gap is real but **secondary** — once the
combobox engine handles EEO/required screeners (see `atsform.combobox_pick`, word-boundary
match + `.select__menu-list` scoping that excludes `UL.iti__country-list`), the form fills
cleanly and you hit the verification wall instead. Do not stop debugging at "EEO fields
didn't bind" — verify the submit actually produced a confirmation, and if it didn't,
look for the verification-code prompt in the page text.

## The unblock (one credential row)

The mailbox that receives the code is the applicant's own address (e.g. `you@example.com`).
To read the code programmatically you need an **IMAP credential row** in
`ats-credentials.csv`:

```
imap.<host>,<applicant-email>,<app-password>
```

`scripts/email_ingest.py` already consumes this exact row (`httpfeed.creds_row("imap")`)
for alerts/responses. There was NO such row this session, so the code could not be read
and 0 applications submitted. Add the row, then:

1. Fill + submit the Greenhouse form (driver logs `Blocked` / shows the code prompt).
2. Fetch the code: `python3 scripts/fetch_verification_code.py --sender greenhouse`
   (reuses `email_ingest._connect`; searches INBOX for an 8-char code from the sender).
3. Type the code into the `#...` security-code field and re-click Submit.
4. On confirmation text, the driver logs `Applied` with `--proof`.

> NOTE: if the mailbox is on the same host as the automation (e.g. a Synology Dovecot
> serving the applicant domain), IMAP is local — but you still need the app-password row.
> Do NOT guess/brute-force the mailbox password; that is out of bounds.

## Honest convertible-inventory discipline

Before promising any count ("+100", "reach 456"), compute the REAL on-profile inventory:
Greenhouse precheck on 635 London+remote roles → ~5 keepers (350 dropped for seniority,
255 off-tier), and even those are gated by this code. CSJ 161 design roles → 2 keepers
(both MI5, same code wall). Reed session dies mid-run; its 13 Easy-Apply rows are
FORBIDDEN and must never count. Ashby/Lever/Workable are spam/hCaptcha/Turnstile walls;
anti-AI-attestation boards (Canonical etc.) are a hard stop.

So the truthful convertible ceiling on proven channels is **single digits**, not 100.
State the honest ceiling ONCE after genuine multi-channel attempts, then stop — never
fabricate `Applied` rows or pad with off-profile/senior roles to hit a number.

## Reusable technique notes (engine already has these — do not re-implement)

- react-select menus open on `mousedown` (synthetic `.click()` does NOT open them).
- Read options from `div[class*="select__menu-list"]`, EXCLUDING `UL.iti__country-list`
  (the phone-country listbox otherwise masks the real options).
- Match exact → word-boundary (reversed scan) so `No`≠`Monaco`, `Man`≠`Isle of Man`.
- All of the above lives in `atsform.combobox_pick`; Greenhouse's `gh_apply.py` routes
  every dropdown through it. A fix there fixes every ATS at once.
