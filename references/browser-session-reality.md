# Browser session reality — camofox ONE-TAB + login verification

## The user is a SECOND concurrent driver of the same browser
The applicant's operator (the user) runs their OWN agent on the same camofox
browser and the same live CFX_TAB that the apply automation uses. So "one tab"
is shared by TWO agents. This is the single most common cause of
"Session expired" / "503 Browser session expired" on apply modals — NOT a dead
session and NOT a re-login issue.

Rule: only ONE agent on the browser at a time. If you hit session-expired while
driving, FIRST check whether the user is still on the tab. Step them off, then
retry. Do NOT re-request a VNC re-login — it will not fix contention (the user
confirmed this explicitly).

## Verify login via the ACCOUNT page, never the homepage signout link
Reed (and similar) caches the homepage nav unreliably: a live session may NOT
render "Sign out" on `reed.co.uk/`, so a missing signout link is a FALSE
"not logged in". The reliable probe is the account page:
  reed:  https://www.reed.co.uk/account/jobs/applications
        live session => "Sign out" in nav + real "Applied DD/MM/YYYY" cards.
Check THAT. If the account page shows a live session but the apply modal says
"Session expired", it is contention/automation-block, not a login problem.

## "Session expired" on an apply modal — interpretation
Observed causes, in order:
  1. ONE-TAB contention (user + automation both on the tab) -> 503 thrash.
  2. Automated `.click()` opens the modal in a state the apply endpoint rejects
     (missing origin/CSRF a real user gesture carries) -> modal opens ALREADY
     expired even when SOLO and the account page is live. This is the camofox
     apply-endpoint block; a VNC re-login does NOT fix it.
If solo + account page live + modal still expired => automation-block wall;
log Blocked, do not pad, do not re-litigate with the user.

## Trust the user's stated state
When the user says "i logged into reed" (or any state fact), verify with the
CORRECT probe (account page) and TRUST it. Do not re-ask, do not repeatedly
request VNC re-login, do not re-litigate. Misreading login via the wrong probe
and re-requesting re-login repeatedly is a real frustration trigger — avoid it.

## Related tool hardening applied this session (reusable patterns)
- check_title.py: industrial-design-engineer guard used substring `in` (let "ui"
  match inside "building") and let "frontend" rescue "Frontend ASIC…". Hardened
  to word-boundary UX match + unambiguous-UX-only rescue + expanded industrial
  denylist. Lesson: verify borderline titles through check_title after any guard
  change; industrial "Design Engineer" modifiers (asic/mechanical/electrical/
  building services/renewable) are OFF-profile.
- reed_apply.py `ev()`: camofox python `cfx.evaluate` 500s intermittently on
  Reed's SPA. Hardened to fall back to the `cfx.sh eval` shell wrapper (SKILL.md
  mandated route). Lesson: when `cfx.evaluate` flakes on a heavy ATS page, route
  through `bash cfx.sh eval`.
