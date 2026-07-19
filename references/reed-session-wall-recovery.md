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
Reed has **no password-login form**. The SignIn page (`/account/SignIn?returnUrl=%2F`)
renders only a **"Sign in without a password"** button that emails a magic link. Both
`feed.py` and `reed_apply.py` assume an already-authenticated browser-profile session and
ship **no re-login script**. When that profile session dies, there is no headless path to
restore it (magic-link needs the inbox; Gmail MCP may be absent).

## Diagnosis (one call)
```python
import sys; sys.path.insert(0,'sites/_common/scripts'); import cfx
cfx.navigate("https://www.reed.co.uk/jobs/ui-designer-design-systems/<id>"); time.sleep(9)
modal = cfx.evaluate("""(function(){var m=document.querySelector('[class*=modal],[role=dialog]');
  return m? m.innerText.replace(/\\s+/g,' ').slice(0,120):'NO MODAL';})()""")
print(modal)   # -> "Session expired ..." == session wall, NOT a flake
```

## Recovery (requires human / Gmail MCP)
1. Sign out to surface the real SignIn URL:
   `cfx.navigate("https://www.reed.co.uk/account/signout?returnUrl=%2F")` → wait →
   the page now exposes `/account/SignIn?returnUrl=%2F` (and `candidate.reed.co.uk/candlogin.asp`).
2. Reed still offers only the magic-link button — headless completion is impossible
   without the emailed link. Two options:
   - **User logs in on the camofox profile** (VNC), OR
   - **Gmail MCP** is present in the run → read the magic-link email and complete auth.
3. After auth restored, re-verify with the diagnosis snippet above (expect `NO MODAL` /
   a real screening step). Only then resume `reed_apply.py`.

## Do NOT
- Do NOT burn the whole Reed queue re-running `reed_apply.py` against a dead session —
  every role returns `LOOP-END`. Stop Reed, report the session wall ONCE, pivot to
  LinkedIn-external / Indeed-external / Parliament / TfL / BBC.
- Do NOT hand-write a `/tmp/reed_*` re-login scraper — there is no password endpoint.

## Timing hardening (already in reed_apply.py)
Initial settle before clicking Apply now is 9s (Reed lazy-renders the button via JS; 5s
raced it → `LOOP-END`). If `LOOP-END` recurs *with a healthy session*, it's a different
role-specific wall, not this one — inspect the modal content per above.
