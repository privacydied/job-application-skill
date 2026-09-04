# SmartRecruiters (jobs.smartrecruiters.com) — verified apply flow (2026-08-28)

No shipped driver existed before this. First real submission: Legal & General, "Product
Analyst (Funds Oversight)", 744000145913189 — verified end-to-end via camofox.

**Driver shipped 2026-09-04: `sites/smartrecruiters/scripts/apply.py`.** Encapsulates the
recipe below into `start`/`fields`/`fill-text`/`pick`/`radio`/`checkbox`/`upload`/`next`/
`submit`/`apply <config.json> [--submit]`. Two real bugs found and fixed while building it
(verified live, Mirantis 744000132893057):
1. **The `walk()` "first match" helper silently binds the WRONG element.** Both the outer
   `SPL-AUTOCOMPLETE` wrapper AND its inner `SPL-INPUT` share the SAME id
   (`spl-form-element_N`) — walking for that id and taking the first hit returns the
   OUTER wrapper. Writing `.value` + dispatching `input`/`change` on the wrapper reports
   `committed='London'` on read-back (the wrapper's own value setter reflects it) but the
   VISIBLE `City` field stays empty and the "Please provide your place of residence"
   validation error stays lit. Fix: collect ALL elements sharing the id, prefer a real
   `INPUT`/`TEXTAREA` tag among them (`_FIND_REAL_INPUT_JS` in `apply.py`), never the
   first-in-document-order hit. This generalizes the NOTES-documented `SPL-AUTOCOMPLETE`/
   `SPL-INPUT` case to every id-duplicated field, not just city.
2. **The file input's `id="file-input"` is DUPLICATED across a hidden mobile/desktop DOM
   copy** (verified: 2 elements, both `visible:true`, both correctly sized — not a
   display:none dupe). Playwright's `/upload`/`/uploadViaChooser` REST endpoints call
   `page.locator(selector)` in STRICT mode, so `input[id="file-input"]` 500s
   ("strict mode violation" — logged server-side, not surfaced in the REST error body).
   Fix: `input[id="file-input"] >> nth=0` pins the first match; Playwright's locator
   engine supports `>> nth=N` chaining directly in the selector string, no extra param
   needed. **This nth-duplicate pattern likely affects other SmartRecruiters ids too —
   if a future field intermittently 500s where NOTES/apply.py's `walk()` reports exactly
   one hit, suspect a duplicate id first before assuming a different failure mode.**
3. **⛔ THE CITY/LOCATION AUTOCOMPLETE DOES NOT COMMIT VIA JS `.value=`/dispatchEvent, NOR
   VIA REAL-TYPE-THEN-ENTER — ONLY A REAL PLAYWRIGHT CLICK ON THE SUGGESTION NODE WORKS**
   (verified 2026-09-04, Mirantis 744000132893057; supersedes the "drive it via KEYBOARD
   — cfx.press('Enter')" claim in the field-by-field recipe above for THIS field type —
   that claim was verified on a different posting/field and may have been a different
   autocomplete variant). Two approaches both LOOK like they worked — the input visibly
   shows the typed text and reads back correctly — but the "Please provide your place of
   residence" validation error stays lit and clicking Next silently no-ops (page doesn't
   advance, no visible error toast):
     a. JS `.focus()` + `.value=` + `dispatchEvent('input'/'change')` on the real `<input>`
        (found via the id-duplicate-safe walk) — `document.activeElement !== input`
        afterward, i.e. the JS `.focus()` never actually took real browser focus on this
        shadow-nested element, so a following `cfx.press('Enter')` had nothing to commit.
     b. Real focus+typing via the camofox `/type` endpoint's `mode=keyboard` (which does
        `page.focus(selector)` + real `keyboard.press` per character — genuine browser
        focus, genuine keydown events) followed by `cfx.press('Enter')` — text updates
        correctly and reads back correctly, but the error still does not clear and Next
        still doesn't advance. Enter alone does not select the highlighted suggestion on
        THIS component (unlike other ATS autocompletes documented elsewhere in the
        skill — do not assume the Enter-after-type pattern transfers here).
   **The fix that actually cleared the error and advanced the form:** `/type
   mode=keyboard` to filter the suggestion list (as in (b)), THEN
   `cfx.click_selector('spl-select-option[value="<value>"] >> nth=0')` — a REAL
   Playwright mouse click via the REST endpoint, NOT a JS `.click()` on the same node
   (a JS `.click()` on an `spl-select-option` was already documented above as unreliable
   for the salary/EEO autocompletes; it is unreliable here too — always use
   `click_selector`, never `evaluate(...click()...)`, for committing an SPL
   autocomplete option). After the click: input shows "London, England, United Kingdom"
   with a clear-✕ affordance (visual proof of a bound selection, not just typed text),
   error gone, Next advances. City options follow the value scheme
   `GB_<REGION>_CITY_<lowercase_slug>` (observed: `GB_ENG_CITY_london`) — confirm the
   exact value via `spl-select-option[value^="GB_"]` enumeration if a city other than
   London 404s the guessed value. **Folded into `sites/smartrecruiters/scripts/apply.py`'s
   `pick()` — use that, not a hand-rolled sequence.**

## Structural gotcha: everything is inside NESTED SHADOW DOM (SPL web components)

SmartRecruiters' apply form ("Easy apply" / oneclick-ui) is built entirely from `spl-*`
custom elements (Smart Recruiters' own design system) with **open shadow roots several
levels deep**. Plain `document.querySelectorAll` from the top level finds almost nothing —
you must recursively walk `el.shadowRoot` for every element. `atsform.py`'s label-substring
matchers do NOT work here (no plain `<label>`/`<input>` pairing at the top level).

### Finding the Apply CTA
The posting page (`jobs.smartrecruiters.com/<Company>/<jobId>`) has an `<a>` with text
**"I'm interested"** (appears multiple times on the page — click the first). It navigates to
`jobs.smartrecruiters.com/oneclick-ui/company/<Company>/publication/<uuid>?dcr_ci=<Company>`
— this is the actual apply widget, "Easy apply".

### The walk-shadow-DOM helper (reuse this JS snippet in every eval)
```js
const walk = (root, id) => {
  for (const el of root.querySelectorAll('*')) {
    if (el.id === id) return el;
    if (el.shadowRoot) { const f = walk(el.shadowRoot, id); if (f) return f; }
  }
  return null;
};
```
Two gotchas this exposed:
1. **Duplicate ids across nesting levels.** e.g. an `SPL-AUTOCOMPLETE` wrapper and an inner
   `SPL-INPUT` can share the SAME id. If you need the real `<input>`, filter by
   `el.tagName==='SPL-INPUT'` (or whatever the leaf custom element is) before walking further
   — `walk()` above returns the FIRST match in document order, which is usually the outer
   wrapper, not the leaf.
2. **The id you can query is on the CUSTOM ELEMENT HOST, not the native input** for text
   fields. `host.value = 'x'` (a form-associated custom element's own value setter) can
   report success on read-back (`el.value` returns what you set) **without ever updating the
   visibly-rendered native `<input>` inside `host.shadowRoot`** — the on-screen field stays
   empty and validation still fails. **Always drill one more level**:
   `const realInput = host.shadowRoot.querySelector('input')` (or `textarea`) and set THAT
   element's `.value`, then dispatch `input`+`change` with `{bubbles:true}`. Verify by
   re-reading `realInput.value`, not the outer host's `.value`.

### Field-by-field recipe (Personal information page)
- Text fields (`first-name-input`, `last-name-input`, `email-input`,
  `confirm-email-input`, phone's national-number input): plain
  `el.value = '...'; el.dispatchEvent(new Event('input',{bubbles:true})); el.dispatchEvent(new Event('change',{bubbles:true}))`
  works directly on the elements found by id (no extra un-wrap needed for these — they ARE
  the real `<input>`s already, verified live).
- **City / location autocomplete**: typing into its input opens a suggestion list of
  `LI`/`DIV` nodes with plain text country/city names (e.g. "London, England, United
  Kingdom") — click the exact-text match. A synthetic `.click()` on the matched node DID
  commit correctly here (unlike the dropdown-select case below) — this may depend on whether
  it's a native autocomplete list vs. a `SPL-DROPDOWN`.
- **Resume upload**: the real `<input type=file>` (`id=file-input`) is ONE level down inside
  an `SPL-DROPZONE`'s shadow root. The camofox `/upload` endpoint's `selector` param, given
  the plain id selector (`#file-input`), DOES pierce the shadow DOM successfully (Playwright's
  built-in shadow-piercing CSS engine) — verified: file chip "base-resume.pdf" rendered and
  stuck. If a first attempt reports `ok:true` but `el.files.length` still reads `0` on
  verification, don't trust the read — re-screenshot; the DOM read-back path used in one
  probe here was itself unreliable (found a *different*, stale element). The **more robust
  path when the plain upload doesn't visibly attach**: `/uploadViaChooser` with `trigger`
  = the same id selector — arms Playwright's real filechooser listener and worked
  immediately when plain `/upload` was ambiguous.
- **"Message to the Hiring Team" textarea**: same host-vs-inner-input trap likely applies;
  in this run the direct `findDeep` match on `hiring-manager-message-input` WAS the real
  `<textarea>` (verified via screenshot) — no extra unwrap needed for textareas encountered
  so far.
- **"Next" button**: it's an `SPL-BUTTON` custom element, not a plain `<button>` — match by
  `el.tagName==='SPL-BUTTON' && el.textContent.trim()==='Next'`, then `.click()` on the
  SPL-BUTTON host itself (not a nested button) — this worked directly.

### Preliminary questions page (dynamically generated per posting)
Each question's full definition (`type`, `label`, `required`, options) is embedded as JSON in
a `definition` attribute on the outer `SPL-FORM`-ish host — grep/read that attribute
(`[...host.attributes].map(a=>a.name+'='+a.value)`) rather than trying to reverse-engineer
labels from rendered text; the rendered text does NOT reliably associate to hidden ids via
`innerText` (shadow DOM again) and `SPL-TYPOGRAPHY-BODY`/`-LABEL` elements are inconsistently
used for question vs. option text. The `definition` JSON gives you the ground truth: which
questions exist, their `id`, `type` (`text`/`radio`/`autocomplete`/etc.), `required`, and
(for select-like ones) the exact option `label`/`fieldValue` pairs.

- **Radio questions** (e.g. "Have you previously been employed by X?", "Do you currently
  have the right to legally reside and work in the UK?"): rendered as `SPL-RADIO` custom
  elements — **no native `<input type=radio>` exists at all**, it's a fully custom
  ring/dot widget. Just `.click()` the `SPL-RADIO` host with the matching id
  (`spl-form-element_<N>`) directly — this DOES toggle its internal `--checked` CSS class
  correctly (verified via `shadowRoot.innerHTML` showing `c-spl-radio--checked`). No native
  setter needed, unlike the checkbox case elsewhere in this skill's other ATS notes.
- **Checkbox questions** (privacy declaration, talent-community consent): the checkbox
  custom element (`SPL-CHECKBOX`) DOES have a nested native `<input type=checkbox>` sharing
  the SAME id as the outer host — find it with `el.tagName==='INPUT'` filter, then
  `.click()` that inner input directly (`.checked` reads back correctly afterward).
- **⛔ Dropdown/autocomplete questions (salary expectations, "how do you identify",
  ethnicity, etc.) — THE #1 SILENT-FAIL TRAP.** These are `SPL-AUTOCOMPLETE` (outer) wrapping
  an inner `SPL-INPUT` (same id) wrapping the real `<input>`. Setting the inner input's
  `.value` directly and firing `input`/`change` DOES filter the dropdown list (you can read
  back the matching `SPL-DROPDOWN-ITEM` option texts), but **clicking the option node — via
  plain `.click()`, or via a manually dispatched pointerdown/mousedown/pointerup/mouseup/click
  sequence with computed coordinates — did NOT commit the selection** in this session
  (verified: the field went back to empty with a "Value is required" error after the
  dropdown visually closed). **The fix that worked reliably: after typing to filter, drive
  it via KEYBOARD — `cfx.press('Enter')`** (no `ArrowDown` needed when the filtered list has
  exactly one match; **first press `ArrowDown` once if you need to disambiguate multiple
  matches, but verify which option ends up highlighted before pressing Enter** — one probe
  here typed "Male" and a stray extra `ArrowDown` moved the highlight onto the WRONG option
  ("Female") one row down; the fix was to re-type and press Enter with NO ArrowDown at all
  since the top/first match was already highlighted by default). **Always re-read the real
  inner `<input>`'s `.value` after pressing Enter to confirm the committed text, never trust
  the mid-flight typed/filter value.**
- A required "please specify" free-text sibling appears after selecting an "Any other ..."
  option — same real-input-vs-host-value rule as other text fields; fill genuinely (never a
  placeholder) and dispatch `input`+`change`.
- Non-required diversity/social-mobility questions (parental job/school/education) can be
  left blank; the marketing-consent checkbox should stay unchecked (declined) per the
  applicant's standing "receive similar jobs = No" rule.
- **Submit button**: another `SPL-BUTTON` (text `Submit`), same click pattern as `Next`.
  A successful submit replaces the whole page with "Application submitted!" — screenshot
  that as proof (`applications/<slug>/confirmation.png`), there is no separate confirmation
  page/URL to capture.

## Cheap location pre-screen: the public postings API (no auth, no browser)
Before opening a posting in camofox to screen it, hit
`https://api.smartrecruiters.com/v1/companies/<company-slug>/postings/<jobId>` (plain
`curl`, no auth/CFX needed — verified live 2026-09-04, Playtech 744000146694014). Returns
JSON including `location: {city, country, remote, hybrid, fullLocation}` — the posting
PAGE itself can render this section as an image/map widget with NO extractable text
(verified: Playtech's "Job Location" section had zero matching text under
`[class*=location]`/`address` and no `application/ld+json`, but the API answered
instantly: `city:"Kyiv", country:"ua", remote:true`). `remote:true` alone does NOT mean
UK/EMEA-remote-acceptable — always check `country` too (a `remote:true` Ukraine/US/etc.
posting is still off-lane per the applicant's London/remote-UK screen). Use this to
pre-filter a whole `ats_hint=smartrecruiters` batch from the queue in one HTTP round-trip
each, before spending a camofox nav+eval cycle on postings that are off-location anyway.

## Net takeaway for a future driver
A proper `sites/smartrecruiters/scripts/apply.py` should: (1) walk-shadow-DOM to enumerate
every `SPL-INPUT`/`SPL-RADIO`/`SPL-CHECKBOX`/`SPL-AUTOCOMPLETE` on the page by id, (2) read
the `definition` JSON attribute for question metadata instead of parsing rendered text,
(3) route radios and checkboxes through the native-input-inside-shadow-root click path, and
(4) route every autocomplete/dropdown through type-then-`Enter` (never a synthetic click on
the option node). This recipe converted the first-ever SmartRecruiters submission for this
skill; reuse it rather than re-discovering the shadow-DOM traps from scratch.
