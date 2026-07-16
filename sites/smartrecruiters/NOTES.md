# jobs.smartrecruiters.com ("oneclick-ui" apply flow) — site notes

## Shadow DOM: `evaluate`/`querySelectorAll` are blind here — use Playwright `role=` selectors instead

SmartRecruiters' "oneclick-ui" apply form is built from ~68 shadow-DOM
web-component hosts. Plain `document.querySelectorAll('input')` (or anything
run through the REST API's `evaluate` endpoint) returns **empty**, even
though the fields are real, interactive, and rendered on screen. Recursive
shadow-root traversal (`el.shadowRoot` walking) *can* read state back out
(e.g. checking `input.checked` — see the checkbox-verification section below)
but is too slow/fragile to use for blind click/select.

**Fix: use the REST API's `selector` param (on `/click` and `/type`), not
`ref` and not `evaluate`.** It runs through Playwright's own selector engine,
which pierces shadow DOM (and same-origin iframes) natively. The
`role=<role>[name="<accessible name>"]` syntax works reliably for comboboxes,
options, and buttons on this page:

```
POST /tabs/{tabId}/click
{"userId": "...", "selector": "role=combobox[name=\"Title\"]"}
...
{"userId": "...", "selector": "role=option[name=\"Frontend Developer & DevOps\"]"}
```

`ref`-based clicks (from the a11y snapshot) still work fine for plain
buttons/checkboxes/textboxes — the shadow-DOM problem is specifically an
`evaluate`/raw-DOM-query problem, not a Playwright-selector-engine problem.

**Watch out for shell quoting.** The `role=combobox[name="..."]` selector
contains double quotes, which breaks naive `-d "{...\"selector\":\"$2\"}"`
bash interpolation (caused `cfx.sh click-selector` to fail with `400 Bad
Request` on this site) — build the JSON via
`python3 -c "import json; print(json.dumps({...}))"` or equivalent instead of
hand-splicing a quoted selector into a bash JSON literal.

## Combobox/autocomplete fields (Title, Company, City) — type-to-match pattern

Several fields (Title, Company on each Experience entry; City in Personal
Information) are free-text-with-suggestions comboboxes, not plain selects.
Reliable fill pattern:
1. `click` on `role=combobox[name="<Field>"]` to focus/open it.
2. Type the value one keypress at a time via `/press` (`key` = each
   character) — the component only expands its own current-input-as-an-
   option (or real geo suggestions for City) once it sees real keystrokes;
   an instant `type`/value-set does not reliably trigger the listbox.
3. Re-snapshot and confirm the option text appears in the `listbox`, then
   `click` on `role=option[name="<exact text>"]` to confirm the selection.
   For City, real suggestions appear (e.g. "London, England, United
   Kingdom" vs "London, Ontario, Canada" — pick the right country).
   For Title/Company after resume-autofill leaves them blank, the box may
   only ever show your own typed text back as the sole option — select it
   anyway, this is what "confirms" the field internally (leaving it as a
   focused-but-unselected raw string fails validation).

## Resume upload triggers autofill, but inconsistently

Uploading a PDF via the `/upload` endpoint (see
`sites/_common/CAPABILITY-GAPS.md` for the endpoint itself) parses the resume
and auto-fills Personal Information + all Experience/Education entries. This
is NOT reliable field-by-field — on one attempt Last Name/Confirm Email/City
came through blank and needed manual fill; on the very next attempt (fresh
tab, same PDF) they were all pre-filled fine. Always re-snapshot after
upload + a few seconds' wait and check every field individually rather than
assuming parse success; don't rely on the same fields being blank/filled
across repeat runs.

## Experience-entry date fields: raw text alone leaves stale validation state

Typing a value directly into the "From"/"To" date textboxes (even via a
proper native-setter + `input`/`change` event dispatch) can leave the page
showing the correct string ("2025-07-01") while an internal validation error
("Please provide end date") persists indefinitely — Save does nothing,
looping silently. The shadow-DOM-recursive checkbox read (below) confirmed
the underlying `<input type=checkbox>` (e.g. "I currently work here") really
was unchecked and the date input really held the right string — the
validator's internal state was simply desynced from the DOM.

**Fix:** open the date's calendar picker (`click` the textbox itself opens
a `dialog` with a month/year grid — day-level granularity isn't exposed,
only month), and actually **click a `gridcell`** via
`role=gridcell[name="July 1, 2025"]` even if that month is already visually
`[selected]` — reselecting through the real UI control is what clears the
stale error, a plain textbox edit does not. If the target month is already
selected, click a neighboring month first, then click back to the desired
one, to force a real change event.

## The first (top) Experience entry never visually collapses after Save

Every experience entry BELOW the first one collapses into a read-only
summary (title/company/dates + Edit/Delete buttons) once saved. The first
entry — the one auto-expanded by the resume parser — stays visually "open"
(still showing Title/Company comboboxes, date fields, Cancel/Save buttons)
even after a successful Save click with no validation errors. **This is
cosmetic, not a stuck state** — confirmed twice by clicking "Next" anyway:
the page advances normally to the screening questions, and the values
entered are retained. Don't loop on this waiting for it to collapse; if
there's no error text/alert visible near the fields, it's safe to move on.

## Screening page (after "Next"): salary, right-to-work, EEO diversity dropdowns

A second page ("Preliminary questions") follows Experience/Education/
Profiles/Resume/Message — typically: free-text desired salary, a right-to-
work-restrictions radio group, then several EEO/diversity comboboxes
(gender, religion, disability [+ a conditional "select all that apply" if
disability=Yes], ethnicity, sexual orientation), a privacy-notice checkbox,
then Submit. All EEO comboboxes reliably include a "Prefer not to say"
option — use the skill's default demographic-answer policy (see
`references/applicant-profile.md`) unless told otherwise for a specific
application. The final privacy checkbox starts unchecked (its a11y label
shows `"on"` as the HTML `value` attribute, NOT its checked state — verify
via the shadow-DOM-recursive `evaluate` checked-state read below, not by
eyeballing the snapshot line).

## Verifying real checkbox state (shadow DOM makes the snapshot's own tags unreliable)

The a11y snapshot sometimes shows a checkbox as `[checked]: "on"` and
sometimes as bare `: "on"` (no `[checked]` tag) for the SAME logical state —
the tag isn't reliable evidence either way on this page. To get ground
truth, run (via `evaluate`):

```js
(function(){
  function all(root, sel, out){
    out = out || [];
    root.querySelectorAll(sel).forEach(e => out.push(e));
    root.querySelectorAll('*').forEach(e => { if (e.shadowRoot) all(e.shadowRoot, sel, out); });
    return out;
  }
  return all(document, 'input[type=checkbox]').map(b => b.checked);
})()
```

This recursively walks every shadow root reachable from the top document and
reads the real `.checked` property. (Note: this only works if the checkbox
lives in the top-level document's shadow tree, not inside a cross-origin
iframe — SmartRecruiters' form is same-origin shadow DOM, not an iframe, so
this works here specifically.)

## Tab can silently die mid-form — no error, just vanishes

Once during a long form-fill session, the managed camofox tab simply stopped
responding (`snapshot`/`click` calls timed out, then `GET /tabs` came back
with an empty `tabs: []` list — the tab was gone, not just slow). No crash
log or error was surfaced to the REST client. Recovery: just open a fresh
tab (`POST /tabs` with `sessionKey`+`url`) and redo the flow from the
beginning — as long as nothing had been Submitted yet, there's no data-loss
risk, just repeated typing. Re-upload the resume PDF again to re-trigger
autofill; don't assume the new tab inherits any state from the old one.

## VERIFIED 2026-07-16 (Experian User Researcher) — full driving recipe + the CV blocker

Drove the whole Easy-Apply form headlessly. Confirmed method:
- **Text fields:** `POST /tabs/{tab}/type` with `selector: role=textbox[name="<label>"]`,
  `mode: fill`. Works for First/Last name, Email, Confirm email, Phone number, LinkedIn,
  Website. ⛔ **CSS selectors (`#first-name-input`) 500** — the input handlers hang the
  server-side op on this shadow-DOM page; role= selectors go through Playwright's engine and
  succeed. (Reads via `evaluate document.querySelector('#id')` DO work — it's only *mutations*
  through CSS that 500. Isolation-verified: same mutation succeeds on a non-SR tab.)
- **City autocomplete:** `type` "London" (role=combobox[name="City"]) → the option list is
  shadow-DOM (role=option clicks time out) → **`press ArrowDown` then `press Enter`** selects
  the first suggestion ("London, England, United Kingdom"). Keyboard beats option-clicking.
- ⛔ **Resume upload is the blocker.** `#file-input` is shadow-DOM. `POST /upload` with a CSS
  selector → 500 (can't pierce). `POST /uploadViaChooser` → **404 (route not deployed)**. The
  fix is the chooser-gated upload route in `server.js` (`references/camofox-file-upload-endpoint.md`)
  — it needs the **camofox-browser container restarted** to deploy (docker is permission-denied
  for <your-user>; ask the user/admin). Same restart also unblocks CVLibrary. Until then, a required
  Resume field on SmartRecruiters can be reached + the rest of the form filled, but NOT submitted.
- Experience/Education sections ("+ Add") had no `*` → optional (the CV covers work history).
- Multi-step: a **Next** button advances past Personal-info/Resume to later pages (screening/
  review). Don't expect a single-page submit.
