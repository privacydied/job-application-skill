# *.careers.hibob.com ("HiBob" / "Bob Hiring") — site notes

External ATS reached via Indeed/LinkedIn's "Apply on company site" redirect (confirmed
on UNiDAYS: `unidays.careers.hibob.com`). Standard native-HTML form for most fields —
no shadow DOM — but three components are custom Angular widgets, not plain
`<input>`/`<select>`, and the page re-renders enough that accessibility-tree refs
(`click <ref>`) go stale mid-form. First application completed 2026-07-13.

## Known failure mode + verified fix: stale a11y-ref clicks silently 500
Clicking a `click <ref>` on this ATS partway through the form intermittently returns
`{"error":"Internal server error","hint":"The page may have changed. Call snapshot to
see the current state and retry."}` — confirmed live on both a radio button click and
the final Submit button, in each case seconds after a fresh `snap` had shown that exact
ref present. Re-snapshotting and retrying the same ref reproduces the same error — it
is NOT a one-off flake to retry through.
**Fix: click via `eval` targeting a stable DOM property instead of the a11y ref.**
- Radios: `document.querySelector('input[type=radio][value="<option-value>"]').click()`
  — HiBob's radio `value` attributes are stable option ids, unaffected by re-renders.
- Buttons with unique visible text (e.g. the final "Apply" submit): find by
  `[...document.querySelectorAll('button')].find(b => b.textContent.trim() === 'Apply')`.
Every eval-based click in this recipe worked on the first try after the equivalent
ref-based click had just failed on the same target — treat eval as the primary
approach on this ATS, not a fallback.

## Form mechanics that matter
- **"Desired salary" is actually TWO required fields, not one** — a plain
  `<input type=tel role=spinbutton>` for the number, AND a separate custom
  `<b-single-select>` component (Angular, not a native `<select>`) for currency,
  sitting right next to it. Filling only the number produces a **silent** "Both
  fields are required" error banner below the salary row that's easy to miss if
  you don't scroll/screenshot after filling it.
  - **Do NOT click the currency selector by an accessibility-tree `button` ref** —
    on this page there were multiple generic `button`s in play and one wrong click
    navigated clean away from the application form entirely (`/apply` → `/jobs`,
    losing all form state and requiring a full re-fill). Instead, locate it
    precisely from the salary input: `document.getElementById('bsiss-/application/desiredSalary').closest('b-input').parentElement.querySelector('b-single-select [role=button]')` (or find the `<b-single-select>` element directly and click it / its inner `[role=button]` child).
  - The currency dropdown has a **type-to-filter search combobox** (`[role=combobox]`)
    — type the currency code (e.g. `GBP`) via a proper value-setter + `input` event
    dispatch (plain `.value =` won't fire Angular's change detection), then click the
    filtered `[role=treeitem]` whose text matches (e.g. `"GBP £"`). Don't try to find
    the option before filtering — the full currency list is long and the target may
    not be in the initially-rendered subset.
- **Pronouns is a similar custom dropdown** (a `[role=treeitem]` tree, not a native
  `<select>`) — click the button to open it, then `[...document.querySelectorAll('[role=treeitem]')].find(e => e.textContent.trim() === 'He / Him')` (or whichever
  option) and `.click()` it directly; no search-filter needed for this one, the
  options render immediately.
- **File uploads (Resume / Cover Letter / Portfolio) use Uppy** — clicking each
  section's "Add file" button dynamically creates a **pair** of hidden
  `input[type=file]` elements (one plain, one `webkitdirectory` for folder
  uploads) with **no `id`** and shared `name="files[]"` — you cannot distinguish
  them by id/name alone. Tag the non-directory one yourself right after clicking
  "Add file": `document.querySelector('input[type=file]:not([webkitdirectory])').setAttribute('data-upload-target','resume')`, then pass that attribute selector to
  camofox's `/upload` endpoint. **A confirmation modal ("Add document") opens after
  the upload with a "Done" button — click it to close the modal and commit the
  attachment**; the filename doesn't appear in the underlying form's visible text
  until Done is clicked, which can look like the upload silently failed if you only
  check the page body text without accounting for the modal being on top.
- **Cover letter upload slot wants a FILE, not pasted text** — there's no textarea
  option here (unlike some ATS forms); convert the markdown cover letter to a
  simple HTML file and print it to PDF via the Playwright container (see global
  CLAUDE.md / SKILL.md step 4) before uploading, the same as the resume.

## Verified working end-to-end
UNiDAYS Product Designer application, 2026-07-13: all fields above filled correctly,
reviewed via full-page screenshot before submit, submitted successfully. Confirmation
text: `"Application submitted. The recruiter has been notified about your application."`
