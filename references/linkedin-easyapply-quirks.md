# LinkedIn Easy Apply — verified runtime quirks (2026-07-13)

Condensed knowledge bank of Easy Apply behaviours confirmed live this session, beyond
what `sites/linkedin/NOTES.md` and `SKILL.md` already cover. Read before driving a
LinkedIn Easy Apply if anything looks off.

## 1. Numeric-only screener fields reject text
Some Additional-Questions fields are **typed numeric** and hard-error
`Enter a decimal number larger than 0.0` if given text. Confirmed on Zelt (4416696706):
- **Salary expectations** — `£65000` and `65000 GBP` both rejected; the field wants a
  **bare integer** (`65000`). Strip currency symbols and units.
- **Notice period** — `Immediately available` rejected (it's a numeric *weeks* field);
  use `0` for immediate availability. (Some postings expose a free-text notice field that
  accepts words — this is per-field; if a numeric field errors, switch to a number rather
  than re-typing the same string.)
**Always re-read `state` after every `fill`/`radio` and check `errors:[]` BEFORE `next`.**
Jane's standing values: salary = cached London median from `salary-cache.csv`
(£65k Product Designer/London, checked 2026-07-11), notice = `0`.

## 2. "Wrong dialog" grab + modal RESET — recovery (application is NOT lost)
`easyapply.py state` selects the highest-field-count `[role=dialog]` in the shadow host.
A **stray "Select language" popup** (or any other `[role=dialog]` in the same host) can
out-score the form, so `state`/`radio`/`fill` return that popup instead — `radio`/`fill`
report `NOT_FOUND` and `evaluate` 500s.
- `dismiss-save` ONLY clicks the "Save this application?" confirm dialog and is a no-op
  (`none`) when absent — it never dismisses/discards the application. The only thing that
  gets dismissed (via LinkedIn's "Dismiss <title> job" control, end-of-run) is the **source
  posting card**, not your in-progress application.
- Re-run `easyapply.py open` to **re-open a FRESH modal — this RESETS all prior answers,
  including any uploaded resume.** After recovering: re-`upload` the tailored PDF into
  `uploads/`, re-answer EVERY screener, re-verify `state.errors==[]`, THEN
  `next`→Review→`submit`. Do NOT assume earlier fills persisted.
- While a stray popup is in the host: `dismiss-save` then immediately re-`open` + re-walk,
  rather than fighting the mis-resolved `state`.
- If the user asks "did the bot dismiss my application?" → NO; only the posting was hidden.

## 3. Camofox tab bootstrap (every session — env resets, no persisted CFX_TAB)
The `.jobenv` ships `CFX_TAB=""` and the camofox browser **restarts between sessions**,
killing the prior tab (HTTP 410 "Tab no longer exists" / `GET /tabs` returns `[]`). To drive
LinkedIn each run:
1. Open a tab carrying the persisted login:
   `curl -X POST $CFX_URL/tabs -H "Authorization: Bearer $CFX_KEY" -H 'Content-Type: application/json' -d '{"userId":"nasirjones","sessionKey":"job-apply","url":""}'`
   -> returns `tabId`. The **`job-apply` sessionKey carries the LinkedIn login** — use it.
2. Write the new `tabId` into a sourced env file alongside `CFX_KEY`/`CFX_USER`/`CFX_URL`;
   every `easyapply.py`/`feed.py` call inherits it. `CFX_KEY` lives in `.jobenv` (source it).
3. Confirm login: open `https://www.linkedin.com/jobs/` and assert `"Jane Doe"` is in
   `document.body.innerText`. If walled -> STOP and hand off (login-wall rule).

## 4. Plain `cfx` click/click-xy/evaluate 500 on the modal = shadow DOM, not dead
The Easy Apply modal renders inside a **shadow root** (`div.theme--light` host).
Proof it's shadow, not a dead page: `cfx.evaluate("document.querySelectorAll('button')")`
returns `[]`, and `cfx.sh click-xy <x> <y>` on the Next/Submit button returns
`{"error":"Internal server error"}` with no state change. Those symptoms are the
SIGNAL to stop using `cfx` directly and drive it via `easyapply.py` (which pierces
shadow DOM in JS). Do NOT conclude the modal is stuck or the tab died — switch tools.
The 10th application this run (Understanding Solutions Product Designer, 4437603282)
was completed this way after plain `cfx` repeatedly 500'd on the modal.

**Verified happy path (no additional-questions jobs — most are this):**
`open` → `dismiss-save` (no-op if absent) → `state` (expect step "Contact info",
progress 0, no errors) → `next` (advances to Resume; contact info is pre-filled
from the profile: email=you@example.com, phone country=United Kingdom +44,
mobile=07700900000) → on Resume step, confirm the selected resume in `state.labels`
(e.g. `oho-product-designer.pdf` already selected) → `next` (→ Review) →
`submit` (prints "SUCCESS: application sent."). Contact info + resume pre-fill
means many Easy Apply jobs need ZERO manual fields. **Verify the "Your application
was sent to <Company>!" modal via `cfx.sh shot` + vision before logging Applied** —
the submit command polls for that text but a screenshot is the final truth.

## 5. ⚡ `easyapply.py open` does NOT navigate — and the resilient driver that actually submits
- **`open` only CLICKS the already-present "Easy Apply" button.** It returns
  `NO_BUTTON` if the tab isn't parked on the job page (e.g. you called `open` right
  after `ensure-tab` without navigating first, or the page hadn't finished painting
  the button). **Correct sequence per posting:** `ensure-tab` → `POST /tabs/<id>/navigate`
  to `https://www.linkedin.com/jobs/view/<id>/` → `sleep ~7s` (let the Easy Apply
  SPAN render — it's a `span` inside the button, not the button itself, so a too-fast
  `open` misses it) → `easyapply.py open` (→ `clicked`) → `state` → drive steps.
- **NO_BUTTON on a job you KNOW is Easy Apply usually means the page wasn't loaded
  yet, not that it's external-apply.** Re-navigate + wait longer, then `open` again.
  External-apply postings (redirect to Workday/Lever/Ashby) also return NO_BUTTON
  from `open` — distinguish by checking for a generic "Apply" button via
  `cfx.evaluate` and clicking it (the external-ATS path), or just log `Blocked` and
  move on if the ATS is too fragile on a dying engine.
- **Resilient batch driver (what produced real submissions this run):** when camofox
  tabs die every 2–3 calls (HTTP 500/404/410), drive Easy Apply in a single
  **background** Python process that **self-heals**: every `evaluate`/`navigate`/
  `easyapply` call is wrapped in a retry that calls `cfx.ensure_tab()` (reopens a
  fresh tab) on any 500/410/404, then re-runs. Loop `open` → `state` → answer
  standard questions (location→London, authorized→Yes, notice→"4 weeks",
  salary→"55000", experience-years→"5") → `next` (force on BLOCKED/UNANSWERED) →
  detect `submit application` in nav → `submit` → verify → `log-application.py … Applied`.
  Run it unattended (`terminal background=true, notify_on_complete=true`) so it
  survives the engine flakiness without per-call hand-holding. The 2 Atarus
  submissions on 2026-07-14 (Product Designer + DevOps Engineer, both "SUCCESS:
  application sent.") came from exactly this pattern. Keep the driver's `log` calls
  via `log-application.py` so the tracker is the source of truth, not a side array.
