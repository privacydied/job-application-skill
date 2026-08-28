# SmartRecruiters (jobs.smartrecruiters.com) — verified apply flow (2026-08-28)

No shipped driver existed before this. First real submission: Legal & General, "Product
Analyst (Funds Oversight)", 744000145913189 — verified end-to-end via camofox.

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

## Net takeaway for a future driver
A proper `sites/smartrecruiters/scripts/apply.py` should: (1) walk-shadow-DOM to enumerate
every `SPL-INPUT`/`SPL-RADIO`/`SPL-CHECKBOX`/`SPL-AUTOCOMPLETE` on the page by id, (2) read
the `definition` JSON attribute for question metadata instead of parsing rendered text,
(3) route radios and checkboxes through the native-input-inside-shadow-root click path, and
(4) route every autocomplete/dropdown through type-then-`Enter` (never a synthetic click on
the option node). This recipe converted the first-ever SmartRecruiters submission for this
skill; reuse it rather than re-discovering the shadow-DOM traps from scratch.
