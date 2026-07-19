# Reed.co.uk — board notes (apply-path quirks)

## Login check — DO NOT use the homepage "Sign out" link
Reed caches the homepage nav unreliably; a logged-in session may NOT render the
"Sign out" link on `reed.co.uk/` even when the account is live. The RELIABLE login
probe is the **account page**:

    https://www.reed.co.uk/account/jobs/applications

A live session there shows "Sign out" in the account nav AND real
"Applied DD/MM/YYYY" cards. Check THAT, not the homepage signout link.
(If a `check_login.py reed` ever ships, it must use the account page, not the shell.)

## "Session expired" on the Apply modal is NOT a dead session
The Apply-now modal validates the session via an endpoint that can return
"Session expired — click Refresh" even when the page session is valid (account
page proves login). Known causes:
  1. ONE-TAB contention: two agents (or the user + automation) driving the same
     camofox tab thrash the session → "503 Browser session expired". The ONE-TAB
     rule is mandatory: only ONE agent on the browser at a time.
  2. Automated `.click()` on Apply now may open the modal in a state the apply
     endpoint rejects (missing origin/CSRF a real user gesture carries). If the
     modal opens ALREADY expired even when SOLO and the account page is live,
     this is the camofox-fingerprint apply block — not a re-login issue. A VNC
     re-login does NOT fix it; the fix is one agent on the tab, or the user
     applies manually.

## Apply flow (reed_apply.py)
job page -> click "Apply now" (button.btn-primary, exact text) -> modal.
Modal: Yes/No screening radios + "Continue", then "About you" + "Submit application".
Answer screening "Yes" (truthful), Continue to Submit, verify on the Applications list
(badge/cards) — the post-submit redirect 404s but the app REGISTERS.

## Wall state (2026-07-18)
At depth, the apply modal returns "Session expired" under camofox automation even
solo with a valid account-page session. Treated as an automation-block wall; the
11 screened on-profile roles (57131534, 57060076, 57096312, 57067097, 57132083,
57070319, 57130034, 57076637, 57136623, 57085757, 57054606) are blocked on this
until the apply endpoint accepts the camofox session (one-agent + working token).
