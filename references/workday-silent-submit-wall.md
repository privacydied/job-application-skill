# Workday — silent "Save and Continue" submit wall (2026-07-14)

A THIRD Workday failure mode, distinct from the already-documented Apply-click-drift
(`sites/myworkdayjobs/NOTES.md`) and the resume date-revert trap.

## Symptom
Account created + every required field filled correctly (verify committed values via
`getElementById().value` — NOT just the setter return), but the "Save and Continue" /
"Next" submit advances nowhere:
- `cfx.click_and_follow(selector="button[type=submit]")` → `no_change`
- raw REST `POST /tabs/<id>/click` `{"selector":"...","trusted":true}` → `ok` but no nav
- `form.requestSubmit()` in-page → also no-op
No validation error, no `[role=alert]`/`.wd-errorinput`/`aria-invalid=true`, button enabled.
This hit The National Archives Sustainability Data Analyst
(`nationalarchives.wd3.myworkdayjobs.com`, `JR200863`) — every field committed, submit
no-oped.

## Isolation check (so you don't misdiagnose)
Dump all field values + scan for error nodes. If every required field shows a committed
value AND there is no error node AND the button is enabled, yet submit doesn't navigate —
it's this wall, not a missing-field validation.

## Action (NOT a hard stop, NOT a scope blocker)
Per the per-posting ~10-min cap + 2-attempt rule: after trying the
trusted-click + raw-`/click` + `reqSubmit` trio once, **log it `Blocked` (not `Skipped` —
the match is good) with the direct job URL in Notes** and move on. A human finishes it
via VNC (`http://nasirjones:6080/vnc.html`, `you@example.com`). Record the Workday creds
(`you@example.com` + generated pw) to `ats-credentials.csv` so the human / a later run can
resume the in-progress application.

## Create-account DOM (stable ids — The National Archives instance)
- `input-4` = Email
- `input-5` + `input-6` = Password + Verify (same value both)
- `input[name=website]` = honeypot ("Enter website. This input is for robots only") — leave empty
- Password rule: 8+ chars, upper+lower+number+special.
- Set via React prototype `value` setter + `input`/`change`/`blur` dispatch. The Create
  Account submit THEN works via a trusted `button[type=submit]` click — i.e. the click
  endpoint is fine; the wall is step-specific (My Info -> Save and Continue).
