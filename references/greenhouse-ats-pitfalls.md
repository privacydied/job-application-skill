# Greenhouse ATS — field-filling pitfalls (from the Canonical UX Designer run, 2026-07-13)

Companion to `sites/greenhouse/NOTES.md`. These cost many tool-calls to discover;
encode them so the next session doesn't repeat.

## 1. Resume upload input is hidden + randomly named
The `<input type=file>` is `class="visually-hidden"` with a random id like
`question_58264591` — NOT labelled "Resume" and not exposed as a snapshot ref.
- `atsform.py upload "Resume" ...` → FAILS (resolves by label text).
- `atsform.py upload "#question_58264591" ...` → FAILS (helper 500s with
  `stale_refs`; the `/upload` endpoint wants a *snapshot ref* like `e11`, not a CSS selector).
- **WORKING:** stage the PDF in `uploads/`, then verify attach by the rendered
  paragraph text (`canonical-xxx.pdf` + a "Remove file" button), NOT by `input.files[0]`.
  If you must POST directly: curl -X POST .../tabs/<tab>/upload -d '{"userId":...,"ref":"<snapshot ref of the file input>","path":"<basename>"}'.

## 2. `atsform.py fill` is a NO-OP on react-select comboboxes
Degree, Discipline, Time zone, math/native-language ratings, consent ("agree to use
only my own words" / "read and agree"), In-country-work, employment-count, and the
EEO gender/nationality/race fields are ALL react-selects. `fill` sets the hidden
`<input>` value but never opens the menu or picks an option -> field shows "Select..."
on snapshot and submits empty. **Use `select` (ArrowDown then click-option) for EVERY
react-select, even ones that look like textboxes.** Canonical's form is heavy with them.

## 3. EEO fields can be REQUIRED (not optional)
Canonical marks Gender / Nationality / Race mandatory. Empty -> 3x "This field is
required" on submit. Answer truthfully from `applicant-profile.md`:
Gender=[your gender], Nationality=British, Race=the "[your ethnicity]"/"[your ethnicity]"
option (profile ethnicity: [your ethnicity]; NOT White, NOT British).
Option lists are long - match EXACTLY (substring .includes matched "Female" when
searching "Male"; use exact === match for gender).

## 4. react-selects RESET on a failed submit
When submit fails validation, Greenhouse re-renders and CLEARS all react-select
values (revert to "Select..."). After ANY failed submit, re-set every react-select
and submit again in one stable pass. Don't trust a "selected" reading taken before
the click.

## 5. Pre-submit review is blind to react-selects
`atsform.py review` / empty-field probes reading `input.value` report react-selects
as empty even when visually filled. Trust the a11y **snapshot** ("option X, selected.")
over `input.value`.

## 6. "This field is required" with no visible empty field = a hidden react-select
you filled with `fill` (see #2). Re-do those fields with `select`.

## 7. Time zone = London
Select the "Europe, Middle East or African Time Zones" region group (covers London).
User instruction: always set time zone to London/GMT.

## 8. Broken EEO react-select (no options) = structural wall, NOT a flake
Some CSJ/DSIT Greenhouse postings render the REQUIRED EEO/diversity react-selects
(age group, ethnic group, ethnicity) with an EMPTY option list — focus + keystroke
does not populate the menu (verified 2026-07-21 on the AISI Strategy & Delivery
Adviser posting, job-boards.eu.greenhouse.io/csjobs/jobs/4924778101). `combobox_pick`
returns `NO_OPTION` and the field never binds. The form then blocks submit with
"This field is required." This is a BROKEN EMPLOYER FORM (no options to pick),
NOT a capability gap to keep probing with `probe_widget.py`. Log `Blocked`
(retryable) and let the applicant complete those specific "Civil Service UK Diversity
Questions" fields manually, then submit — do NOT pad the count or fabricate. The
core essays + required non-EEO fields CAN be filled by the agent first (`gh_apply.py`
with `no_submit: true`) so only the 3 EEO selects are left for the human. Note the
contrast with pitfall #3 (required EEO that DOES have options): there, drive it;
here it's empty, so don't loop.
