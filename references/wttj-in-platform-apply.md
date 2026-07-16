# WTTJ in-platform apply (Apply with your profile)

Driver: `sites/welcometothejungle/scripts/apply.py` (commands: `start`, `answer`,
`status`, `send`). Built on `cfx.py`. Use it — do NOT hand-drive the modal.

## Classify first: IN-PLATFORM vs EXTERNAL-ONLY
`python3 apply.py start "<wttj job url>"` navigates, clicks Apply, and detects the
modal type:
- **IN-PLATFORM** → "Apply with your profile" auto-fills from Jane's WTTJ profile;
  only an Application Question may remain. `status` shows `N section(s) left` / `All done`.
- **EXTERNAL-ONLY** → prints `EXTERNAL:<company>` (e.g. `EXTERNAL:Amazon`). The role
  routes to the employer ATS (amazon.jobs etc.) — drive THAT ATS, not WTTJ.
  (Verified 2026-07-16: of 10 fresh WTTJ on-profile roles, 4 were IN-PLATFORM —
  Maze `TPrEb8cb`, loveholidays `ny6pnAU3`, Octopus `_EDvbHix`, AIOS `Q0mJCW3d` — and
  6 EXTERNAL. The Amazon one `tVXhl91U` = amazon.jobs 3155480, already applied.)

## The silent Send bug is FIXED (commit 1d8cb1a)
WTTJ's app is a React SPA. The old `_click_text` did a raw DOM `.click()`, which
React's synthetic-event system does NOT honor → the Send/Apply handler never fired →
"Send lands, no confirmation". Fixed: `_click_text` now marks the matched button
(`data-cfx-hit`) and clicks via `cfx.click_selector` (real server-side Playwright
click). So **Send genuinely fires now**. If you ever see "Send lands, no confirmation"
again, suspect the VERIFICATION METHOD below, NOT the Send click.

## VERIFY via the dashboard, NOT the job page (critical)
After `send`, the job page resets to a **"Did you apply? Yes/No"** prompt and shows NO
"Applied" marker — this is NOT proof of failure. Verify at
**`https://app.welcometothejungle.com/account/applications`**: the role appears in the
list (e.g. "loveholidays — Product Designer - 12-Month FTC") with View/Apply/Move
actions. That list is the source of truth. Screenshot it as `--proof`.
(2026-07-16: loveholidays reported "UNCLEAR / no confirmation" from the job page but WAS
confirmed in the dashboard — a real submission that the wrong check nearly discarded.
Never log `Applied?`/`Unverified` when the dashboard shows the role.)

## Modal fragility (lazy-rendered Application Question)
IN-PLATFORM roles with "1 section left" have an Application Question whose textarea is
**lazy-rendered** — it is not in the DOM until you click into it.
- **Direct-activation recipe (works for pre-answered or answered-in-session roles):**
  click the "Type your answer here" placeholder
  (`[...document.querySelectorAll('*')].find(e=>e.children.length===0 && /type your answer/i.test(e.textContent))`,
  then `.click()`), then React-set the textarea value via the prototype setter +
  input/change dispatch, then click the **Save** button, then `apply.py send`.
- **Fresh (never-answered) roles may not reveal the textarea headlessly** — `start` can
  return "UNKNOWN modal state" (Apply CTA clicks but no in-platform modal opens) even
  though WTTJ is logged in. This is environmental (see contamination below), not the Send
  bug. On "UNKNOWN", retry `start` on a FRESH tab once; if it persists, the role is
  currently unopenable headlessly — log `Blocked` with "WTTJ in-platform modal won't open
  (UNKNOWN state)" and move on (don't re-loop).
- **`apply.py answer` needs a question-substring** present in the DOM; if the question
  text isn't introspectable (lazy), `answer` returns `Q_NOT_FOUND`. Prefer the
  direct-activation recipe above when the substring is unknown.

## SESSION-EXPIRY BLOCKER (new 2026-07-16 — distinct from UNKNOWN modal state)
If `start` reports "IN-PLATFORM apply open" but the tab URL is `uk.welcometothejungle.com/`
(homepage) and `evaluate` shows `loggedIn:false` with NO sign-in form, the **WTTJ session
cookie has expired** — the SPA won't serve the login UI (`/login` 302-redirects back to the
job page; the homepage renders logged-out marketing with no form). This is a HARD unblock,
separate from the logged-in "UNKNOWN modal state" case:
- **Symptom:** `apply.py start` prints "open" but `location.href` == homepage; body has no
  "Welcome back, Jane" / "My applications" / "Sign out" menu and no login control.
- **Verify** with a one-liner: `cfx.sh eval "JSON.stringify({url:location.href, loggedIn:/Welcome back|Sign out|My applications/i.test(document.body.innerText)})"`.
- **Re-auth is a NON-CODE human action:** creds are in `ats-credentials.csv` (row
  `welcometothejungle.com`), but the SPA login flow isn't reachable from this camofox state
  (redirect loop, no form). A human must re-log-in (email+password; possibly 2FA). **Do NOT
  loop re-`start` on stale tabs — it won't recover.** Log the affected on-profile WTTJ roles
  as `Blocked` ("WTTJ session expired — needs human re-login") and move on. ALL in-platform
  AND external-ONLY WTTJ roles are blocked until the session is restored (the external ATS opens
  from a logged-in WTTJ click).
- **Recovery signal:** once a human confirms re-login, re-run `start` on a FRESH
  `open-tab about:blank` + explicit `nav` per role (cross-tab contamination still applies).

## Use a FRESH tab per role + watch cross-tab contamination
- WTTJ modal state LEAKS across camofox tabs: a stale modal can show another role's
  content (e.g. "Amazon UX Designer" appearing on a Maze apply). **Open a fresh
  `open-tab "about:blank"` + explicit `nav` for EACH WTTJ role** to avoid carrying stale
  modal/DOM state. (Same `open-tab` auto-nav pitfall as
  `camofox-open-tab-nav-pitfall.md` — explicit nav, never rely on open-tab's
  auto-navigate.)
- Keep total open tabs low; 9+ active tabs correlates with modal-open failures.

## Auth-state check (don't misread "signin")
WTTJ shows **"Welcome back, Jane"** when authenticated. A "sign in" / "log in"
**footer link present does NOT mean logged out** — it's always in the footer. True
SIGNED_OUT = no "my applications" / "sign out" menu. Check for those, not the absence of
"signin". If genuinely signed out, the `welcometothejungle.com` row in
`ats-credentials.csv` has you@example.com + password; the login page may render
"Welcome back, Jane" directly (already authed).
