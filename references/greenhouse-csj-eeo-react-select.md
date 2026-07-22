# Greenhouse CSJ "Civil Service UK Diversity Questions" EEO react-selects

VERIFIED 2026-07-21 on posting `job-boards.eu.greenhouse.io/csjobs/jobs/4924778101`
(AISI Strategy & Delivery Adviser). Reproduce with the packaged driver:
`scripts/fill_csj_eeo.py` (see that file for the exact JS recipe, which is the
verified inline probe from this session).

## The wall
CSJ Greenhouse postings carry a **"Civil Service UK Diversity Questions"** section
with several **required** react-selects (age group, ethnic group, ethnicity,
national identity, religion, parent-occupation-at-14, employee/self-employed,
school-type-11-16, etc). They render fine visually but `gh_apply.py`'s shared
`combobox_pick` engine (and the `_fill_eeo` plan) **fail to set them**, so submit
blocks with `This field is required.` Three compounding causes:

1. **Async option list.** The `.select__menu .select__option` nodes only appear
   ~1s after the control is opened. `combobox_pick` opens and reads synchronously
   -> sees `NO_OPTION` -> gives up. The menu CLOSES between two separate `evaluate`
   calls (react-select blurs on any navigation/eval gap), so open-then-read-in-a
   second call never sees options. **Must open AND read in ONE async call that
   polls for `.select__menu .select__option` to exist.**
2. **Viewport gate.** The menu only mounts if the `.select__control` is scrolled
   into the viewport first (`scrollIntoView({block:'center'})`). Opening a control
   that's off-screen yields an empty/never-mounted menu.
3. **Curly apostrophe.** The "I don't wish to answer" option uses U+2019
   (`don't`), not a straight `'`. An exact `=== 'I don't wish to answer'` (straight
   quote) NEVER matches -> `NOTARGET`. Normalize both sides:
   `s.replace(/[\u2018\u2019]/g,"'")`.

## The verified driving recipe (one async eval per select)
```
scroll .select__control into view
dispatch mousedown + mouseup + click on .select__control
poll up to ~2s for document.querySelector('.select__menu .select__option') to exist
find option whose textContent (curly-normalized, lowercased) includes the target
scroll it into view; dispatch mousedown + mouseup + click on the OPTION NODE
read .select__control .select__single-value to confirm BOUND
```
Do NOT use keyboard ArrowDown/Enter for these — index drifted (landed one-off from
the highlighted default), whereas clicking the normalized-match node bound exactly.
(If node-click ever re-races, the keyboard fallback is: open, press ArrowUp x20 to
reset highlight to top, then ArrowDown `idx` times, then Enter — but prefer the
click path; it was the one that worked.)

## Two more footguns on this exact form
- The field **id** is stable per posting but the *option text* uses hyphens, not
  words: age group is `"30-34"` (NOT `"30 to 34"`). Match on the literal option
  string — read it first if unsure (open the menu, dump `opts.map(o=>o.textContent)`).
- `cfx.evaluate` (python) **500s** on this heavy Greenhouse page. Route every read/
  fill through `bash sites/_common/scripts/cfx.sh eval '<js>'` (same endpoint, no
  python 500s). Keep expressions returning FLAT primitives (a string), never a
  structured object/array that mirrors DOM nodes (that 500s the wrapper too).

## Are these required or optional?
On CSJ Greenhouse they are `aria-required: true` AND gate submit — the form refuses
to submit until all are set. They are the applicant's own protected-characteristic
disclosures (the user's 2026-07-19 instruction wants them filled with real values).
When the applicant's real answer is unknown/uncomfortable to assert, the explicit
`I don't wish to answer` option is present in every one of these selects and is the
truthful choice — never fabricate a specific demographic to clear the field.
