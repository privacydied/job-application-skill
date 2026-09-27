# jobs.nhm.ac.uk (Natural History Museum, JobTrain ATS) — site notes

A conversational multi-step ATS ("JobTrain" platform, `jt-modal` CSS classes). Reached via
a LinkedIn external Apply → `jobs.nhm.ac.uk/Job/JobDetail?JobId=<n>` listing page → "Apply
for job" → "I don't work here" → a 2-step no-password registration (name → email/mobile) →
a full multi-tab application form (About You / Application questions / Equal opportunities
/ Review and submit) → a final "create a password" step AFTER "Submit application" to
actually finalize. First live submission: UX Designer, JobId 948, 2026-09-27 — took
several hours due to the bugs below. Read this BEFORE touching employment-history rows.

## ⛔ Mid-application SESSION EXPIRY dialog silently causes "phantom saves" — the root cause of hours of debugging this session
A "Session Expire" modal ("Your session will expire in another N seconds", `Keep Me Logged
In` / `Logout` buttons, real id `#btnOK` / `data-testid="btn-keep-me-logged-in"`) can appear
**stacked on top of an open Edit-employment modal** without any other visible warning. If
you don't see and dismiss it in time (or if a stale-refs `click-xy` 500 error masks it),
every field edit made in that window silently fails to persist server-side — the field
shows the correct value client-side (green border, correct text) for the rest of that
render cycle, `Continue` appears to succeed, but **the underlying record keeps its old
(often empty) value indefinitely.** This produced a maddening loop of "the field READS
BACK correctly, Continue closes the modal cleanly, yet the row still shows the red
completeness asterisk and the Main Responsibilities/Start/End Date text never appears in
the review table" — which looked like a widget bug but was actually an expired session
silently rejecting the save.
- **Prevention**: after opening ANY edit-employment/edit-education modal, immediately
  check `document.body.innerText.includes('Session Expire')` before touching fields, and
  re-check after every `Continue` click. If found, dismiss it via
  `document.elementFromPoint(x,y).click()` on the "Keep Me Logged In" button coordinates
  (NOT `cfx.sh click-xy`, see below) before doing anything else.
- **Detection after the fact**: if a field you just set (and verified via `.value` read)
  is missing from the row's display text moments after `Continue`, suspect this — re-open
  the row's edit modal and check if the value reverted to empty/stale.

## `cfx.sh click-xy` intermittently 500s with "page may have changed... stale refs" on this site — use `document.elementFromPoint(x,y).click()` instead
Verified repeatedly: the dedicated click-xy REST endpoint threw `Internal server error`
with a stale-refs hint on this ATS far more often than on other sites this session, for
reasons not fully diagnosed (possibly the app's frequent DOM re-renders on every keystroke
invalidate whatever ref cache the endpoint relies on). **Working fallback used throughout
this session**: `bash sites/_common/scripts/cfx.sh eval "document.elementFromPoint(X,Y).click()"` — a plain JS click at the same coordinates, which worked reliably every time
click-xy failed. Prefer this from the start on this site rather than retrying click-xy.

## Employment-row Main Responsibilities / Start Date / End Date: JS `.value=` setter alone often does NOT persist — real per-character keystrokes via `cfx.sh press` DO
Setting a textarea/date input's value via the standard native-setter + `dispatchEvent`
pattern (`Object.getOwnPropertyDescriptor(proto,'value').set.call(el,val)` + `input`/
`change` events) frequently reads back correctly in the SAME turn but does not survive a
`Continue` click (see session-expiry note above — this may be the same underlying cause,
not a separate bug). The reliable fix used repeatedly this session:
1. `document.elementFromPoint(x,y).focus()` on the target field — confirms real DOM focus
   (`document.activeElement === el`), which a `.focus()` call on a JS-selected element does
   register correctly here (unlike some other sites).
2. `bash sites/_common/scripts/cfx.sh press <char>` once per character (loop over a
   bash `for c in ...`) — genuine keyboard events land differently from JS synthetic ones
   and this is what actually persisted the values through to submission.
3. Re-verify the field's `.value` immediately (before doing anything else) and again right
   before clicking Continue.

## Employment-row date inputs use DD/MM/YYYY, not MM/DD/YYYY — despite the placeholder sometimes rendering ambiguously
Confirmed: typing `01032020` produces the DISPLAYED value "01/03/2020" (1 March 2020), and
the placeholder literally reads "DD/MM/YYYY" on the visible field. An earlier attempt on
this session mistakenly used MM/DD/YYYY ordering for one field before this was confirmed —
double-check the placeholder text on each fresh row (it can vary by which sub-field
re-rendered most recently).

## Multiple employment-row edit/delete buttons share the SAME re-orderable DOM index — never trust `data-testid="btn-ref-edit-N"` alone
The `[data-testid="btn-ref-edit-N"]` index does NOT reliably map to on-screen row order
after any add/delete operation on the list (observed: `edit-2` opened a completely
different row than the one visually at position 3). **Reliable pattern**: locate the
`<table>` containing known unique text (e.g. the employer name), walk up to find its
containing row `<div>`, then `.querySelector('[class*=editEmploymentBtn]')` /
`[class*=deleteEmployment]` scoped to THAT container — never index into the global button
list.

## Add-employment modal's Start/End Date fields are BELOW the fold and the modal is `position: fixed` — page `window.scrollBy` does nothing to reveal them
The `.modal.jt-modal.fade.show` element itself is independently scrollable
(`scrollHeight` ~1200-1300px vs `clientHeight` ~735px). Scroll THAT element's `scrollTop`
directly (`document.querySelector('.modal.jt-modal.fade.show').scrollTop = 900`), not the
page — page scroll leaves the fixed-position modal's on-screen position completely
unchanged, which produces confusing "the field exists in the DOM at y=980 but scrolling
doesn't move it" symptoms.

## Two open native datepicker calendars can visually block the Continue button after typing both Start and End Date
After typing into both date fields (each opens its own `.datepicker` popup on focus), both
calendars can remain open and overlap the Continue button underneath. Neither pressing
Escape nor Tab reliably dismisses them cleanly — Tab in particular can jump focus and
silently overwrite the End Date field with today's date via the picker's auto-select
behavior (verified: typed `31082022`, Tab caused it to become `27/09/2026`, i.e. today).
**Fix that worked**: `document.querySelectorAll('.datepicker-days')` → walk up to each
`.closest('.datepicker')` → `style.display = 'none'` on both. This hides the calendar
popups (which also visually hides the shared-class date INPUT elements themselves, since
they apparently share a class with the picker container — this is cosmetic only, the
underlying `<input>` value is retained) and reveals Continue underneath, clickable
immediately.

## The final "Submit application" click is NOT the end — a password-creation step follows
After the review page's "Submit application" succeeds, the site shows "Nearly done! One
last thing" and requires creating an account password before the application is actually
finalized. The true success screen ("Thank you for submitting your application. You have
successfully applied for the following position: `<role>`") only appears after this
password step. Don't log `Applied` until you see that exact text — the intermediate states
can look terminal but aren't. Save the generated password to `ats-credentials.csv` under
`jobs.nhm.ac.uk (Natural History Museum)`.

## Net time-cost note for future runs
This single application took multiple hours this session, almost entirely due to the
session-expiry-during-edit bug compounding with the value-doesn't-persist symptom it
causes. If a future run hits the same "field reads back correctly but row stays
incomplete after Continue" loop more than ~2-3 times on this site, check for the Session
Expire dialog FIRST before assuming a driver/selector problem.
