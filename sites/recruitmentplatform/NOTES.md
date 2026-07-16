# recruitment.hackney.gov.uk / Lumesse TalentLink — verified apply recipe

Hackney's "Apply Now" routes to **Lumesse TalentLink**
(`emea3.recruitmentplatform.com/apply-app/pages/application-form?jobId=…`).
This IS automatable — a first application (Help Desk Operative, 2026-07-14) was
submitted end-to-end via `sites/recruitmentplatform/scripts/talentlink.py`.
The earlier "Lumesse TalentLink … NOT yet automated" note in `sites/hackney/NOTES.md`
is STALE — ignore it; the adapter now exists.

## Form shape (single long page, ~117 fields)
Contact → multi-employer Work History (each block = Employer name + Job title +
start/end date dropdowns + responsibility textarea) → Education → Qualifications →
role-specific competency textareas → declarations → Equality & Diversity → **Data
Privacy Statement** (required) → Submit.

## Quirks / gotchas (all solved in talentlink.py)
- **Date dropdowns share a `name`**: each employment date is THREE `<select>`
  elements with the SAME name (Day / Month / Year, in document order). Set them
  by `querySelectorAll(name)[0..2]`, NOT a single name lookup. Month text =
  "January"…"December"; Year = 1946…2046.
- **Data Privacy Statement** looks like a clickable "I agree" label that opens a
  dialog — but synthetic clicks on the dialog button do NOT persist to the form's
  validation model. The real control is a **HIDDEN `<select name="dps">`**
  (options: `Please agree`='' / `I agree`='true'). Set that select directly
  (`s.value='true'` + change/input events) — that's what clears the
  "Data Privacy Statement is required" error. (Verified 2026-07-14.)
- **Conditional fields**: e.g. `custom_question_2746` (work-permit type) only
  renders when "need work permit = Yes". If you select "No, I do not need a work
  permit", that field is `display:none` and must be SKIPPED (a naive "empty
  required" audit will false-positive on it — the adapter's review() ignores
  hidden fields).
- **Upload**: the camofox `/upload` API wants the file staged in the skill's
  `uploads/` dir (bind-mounted as `/uploads`); send only the basename as `path`.
  The adapter copies the CV there first.
- **Equality/monitoring**: Hackney marks most as Required. Use "Prefer not to
  say" for optional demographic questions per the standing rule; answer the
  genuinely-required ones truthfully (marital status, religion, ethnicity,
  nationality, gender, sexual orientation, disability, age range, pregnant/
  maternity in past 2 years).
- **Competency questions**: free-text; answer from Jane's real experience
  (your relevant support/IT experience).

## Usage
```bash
python3 sites/recruitmentplatform/scripts/talentlink.py \
  "<TalentLink application-form URL>" apply_<role>.json --submit
# apply JSON keys: text{name:value}, select{name:option}, dates{name:[DD,Month,YYYY]},
#                  radio{name:value}, upload:"<cv pdf>", company, accept_dps:true, submit:bool
```
The adapter fills by stable `name` attribute, sets dates by index, accepts DPS,
uploads CV, reviews (ignoring hidden fields), and submits. Reused for every
Hackney (and any other Lumesse-backed) posting.
