# CSJ TAL eform — submit-wall gotchas (learned 2026-07-17)

Driving a Civil Service Jobs TAL eform end-to-end (S1 eligibility/personal/diversity +
S2 CV/PS/declaration) is the only fully-automatable hard-board apply. These are the
failure modes that silently block submission and how to fix them.

## 1. Diversity sub-option value mismatch -> silent submit-wall (ROOT CAUSE of most walls)
- Field `datafield_35302_1_1` (ethnicity sub-option) must equal an **option the live eform
  actually offers**. The filled spec had `"Any other Mixed/Multiple background"` but the
  eforms offered `"Any other Mixed background"` (and `Mixed / multiple ethnic groups`, not
  `Mixed or Multiple ethnic groups`).
- Effect: `tal_eform.py` reports the field `NO_OPT` (not `OK`) but still "advances"; the
  Diversity page is marked server-side **Incomplete**; the final declaration page renders
  **only a "Back" button -- no Submit/Continue**; the live Applications view shows
  "Application in progress". Looks like a tool gap; it's a spec-value bug.
- Fix: set the diversity values to the exact offered option text. After the fix, S1
  completes -> S2 spawns -> full submit works. (Recovered 3 roles that were wrongly logged
  `Blocked`.)
- The spec lives at repo root as `spec_csj_s1_jane.json` (gitignored). PII-safe: it holds
  Jane's real diversity answers; never commit it / never fill `templates/csj_s1_spec.json`
  in place.

## 2. S1 page-1 "provide details" field is required
- `datafield_50629_1_1` ("Provide details of how you meet the experience and skills
  outlined above", 250 words) on S1 page 1 must be non-empty. Leaving it empty produces a
  validation error "There is a problem -- Desirable experience and skills" and blocks
  submit even after the declaration is ticked. Fill it with a tailored statement.
- The eligibility radio `datafield_50626_1_1` ("Do you have the relevant experience?") must
  be set to Yes (value "1") -- `tal_eform.py` does NOT support `radio` kind, so set it
  manually via cfx if the driver skips it.

## 3. S1 -> S2 flow
- After S1 declaration (`datafield_22499_1_1` checked) the driver may report `NO_ADVANCE`
  on the final page. For **multi-section** eforms this is normal: S1 submitted and S2
  spawned at a NEW eform ID (e.g. `57074915` -> `57074961`). Navigate to the S2 eform and
  run `tal_sec2.py`.
- For **single-section** eforms there is no S2; the S1 declaration page itself must submit.
  If it won't (only "Back"), it's the sec-1 value bug, not a missing S2.

## 4. S2 field IDs vary per campaign -- map before building the spec
- `tal_sec2.py` re-fills each page from a per-eform spec; `pages` must match the REAL page
  count. Extra/phantom page numbers cause a wrap that loses state.
- Common S2 IDs (verify per eform with cfx before writing the spec):
  - `99856_1_1` / `99863_1_1` -- CV employment / CV skills (textarea)
  - `53854_1_1` -- qualification level (select; "Degree" for Jane)
  - `217326_1_1` -- name-blind "removed personal info" checkbox (true)
  - `72158_1_1` / `72117_1_1` / `72220_1_1` -- Personal Statement (textarea; ID varies)
  - `217348_1_1` -- declaration checkbox (true)
  - `205967_1_1` -- final declaration checkbox (true)
  - `76575_1_1` -- "Full Application Form Submitted?" select = "Yes"
  - `53467/53470/53473` -- location preferences (some eforms)
  - `64783_1_1` -- "statements on technical skills" (optional textarea, some eforms)
- **Submit only renders after `205967` checked AND `76575=Yes`** on the final page. If
  Submit still doesn't appear, a required earlier field is empty -- read the "There is a
  problem" summary; it names the section, which maps to the page with the missing field.

## 5. Proof + log
- After `advance -> submit`, navigate to the eform `save_page`; confirmation text is
  "This application form has already been submitted" or "Application received". Capture it
  to `applications/<slug>/confirmation.txt`, then `log-application.py ... Applied --proof
  <file>` (HARD gate: no proof => refused).
