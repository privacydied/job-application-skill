# Camofox form-filling pitfalls (learned driving Greenhouse / ATS-direct)

Driving ATS forms through camofox has several reproducible gotchas that waste whole
application attempts if you don't know them up front. All verified live 2026-07-19.

## 1. Never re-navigate mid-form — it wipes every fill
`cfx.goto` / `cfx.sh nav` reloads the page blank. If you fill name/email/etc.,
then `goto` again (even to the same URL) to drive a later step, the form
resets and validation will report `First Name is required` on a form you "just
filled."
**Rule:** do ALL of — `atsform apply` (fills + uploads) → react-select
screeners → acknowledgment checkboxes → **submit** — on ONE continuous page
load. No `goto`/`nav` between steps. If you must re-load (tab died), redo
every field.

## 2. React-select comboboxes (Greenhouse / ATS-direct screeners) — USE `atsform.py select`
Screener questions ("Are you based in…", "Visa sponsorship", "Authorization to
work", "Where did you first hear") render as react-select comboboxes
(`input.select__input` / `input[role=combobox]` inside a `.select__control`).

**These are NOT a structural limit — `atsform.py select "<label>" "<option>"` drives
every one of them** (verified live on Vercel's Greenhouse form 2026-07-19: all 14
comboboxes filled first-pass, including "Your authorization to work" and "Where did you
first hear," which a prior run wrongly declared impossible and logged `Blocked`).

⚠️ In the config, screener comboboxes go under **`"select"`**, NOT `"radios"` /
`"checkboxes"` — an acknowledgment like "By submitting… I acknowledge" is *also* a
single-option react-select, so it too goes under `"select"`. Putting them under
`radios`/`checkboxes` is a silent no-op (`set_radio` returns `NO_FIELD`).

**Root cause of the old "won't open" blindness** (fixed in `atsform.py`):
- These Greenhouse "remix" react-selects expose **`aria-controls: null`**, so the old
  opener (JS-focus + `ArrowDown`, then read `aria-controls` for the menu) found nothing
  even when a menu opened; the fallback *trusted* click on the input **hangs ~30s**.
- A synthetic value-set + `input` event (the old typing workaround) does **not** open a
  fixed-option react-select — it toggles its menu on the **control's `mousedown`**.
- The fix: dispatch `pointerdown`/`mousedown`/`mouseup` on the `.select__control` to open,
  read options from the open `.select__option` list (not `aria-controls`), and commit the
  option via its own `mousedown` (react-select `preventDefault`s the click).
- Still true: `cfx.post("/tabs/<tab>/type", …)` 404s on the live tab — never use it.

**"Mark all that apply" multi-selects** (e.g. the EEO gender/race/orientation questions):
`select` ADDS one option per call, so call it once per value; to remove a wrong chip
(e.g. a stale "I don't wish to answer"), click the chip's
`.select__multi-value__remove` before adding the correct ones.

Only stop if a combobox genuinely has no truthful option for the applicant — that's an
eligibility judgement, never a widget limit.

## 3. `atsform` upload paths must be bare basenames in `uploads/`
`atsform.py upload` POSTs `{"path": <name>}` and the server reads
`uploads/<name>` (skill `uploads/` is bind-mounted into the container at
`/uploads`). Passing `uploads/foo.pdf` or an absolute path 404s
(`file not found under /uploads`). **Stage the file as a bare basename in
`uploads/` and put just the basename in the config `upload` block.**
(See `sites/_common/scripts/upload-file.sh` for the canonical staging logic.)
Note: a post-upload poll can report `FAIL: NONE` while the file IS attached
(Greenhouse swaps the `<input>` for a filename display) — confirm via the
filename text, not the input.

## 4. Invisible reCAPTCHA = submit, not a stop
`recaptcha.py click` on an **invisible** reCAPTCHA returns
`NO-CHANGE / nothing to click` — that is NORMAL (there is no checkbox). It
scores the *submit* action. **Finish the form and click Submit; do not treat
"nothing to click" as a blocker or a halt.** Only a *visible* v2 checkbox
or image-grid is a sanctioned click/solve.
