# volcanic.cloud ("Volcanic" ATS) — site notes

Custom branded ATS platform seen on employer career sites (e.g.
`<company>.staging.krakatoa.eu-2.volcanic.cloud`). Reached this session via a LinkedIn
"Apply" (not Easy Apply) external redirect that opened the employer's own careers page
first, then a separate `/apply` form page after clicking that page's own "Apply Now" link.
Live example: Fortnum & Mason, Junior Website Designer, 2026-09-27.

## Navigation pattern (2-hop)
1. LinkedIn external Apply → new tab lands on the JOB LISTING page (not the form),
   e.g. `https://<company>.<env>.volcanic.cloud/job/<slug>`.
2. That page has its own `<a>` "Apply Now" (NOT a `<button>` — matches the general
   pattern seen elsewhere this session of Apply controls being anchor tags with an
   external-link icon, not `<button>` elements. A `querySelectorAll('button')` scan for
   "Apply" text will legitimately return 0 here even though visible text says Apply).
3. Click that `<a>` → same tab navigates to `/job/<slug>/apply`, the real form.

## Form mechanics
- Plain server-rendered Rails-ish form (`job_application[answers_attributes][<qid>][content]`
  named inputs/selects/textareas, `question_id` hidden siblings). No React — plain DOM
  querySelector + native `value` setter (input vs textarea prototype) + `input`/`change`
  events works directly; no need for `atsform.combobox_pick`.
- **Labels are NOT `label[for]`-linked to the field.** Resolve by walking up to the nearest
  ancestor `<div>` and finding a `<label>` element within a few levels — reliable in
  practice (verified against all ~25 fields on the Fortnum & Mason form).
- **Honeypot fields present**: an input named something random (e.g. `jbtyiofdersq-`) and a
  `source` input, both with visible/label text "If you are a human, ignore this field."
  Leave them empty — do not fill.
- **A "please choose an option" conditional select can still be a hard-required field on
  submit even when its label text says "if applicable".** Live case: "If you are here on a
  visa, please choose an option for your VISA status?" — form validation rejected submit
  (silently re-rendered same URL, no visible error banner, had to screenshot to see the
  still-open form with the field outlined) until this was set to "Not Applicable" despite
  the applicant not being on a visa. **If a submit silently does nothing (same URL, same
  title, no navigation), screenshot the form — the still-focused/outlined field is usually
  the validation culprit; check its label for "if applicable" wording.**
- **CV upload**: standard `<input type=file>`, works via the shared `atsform.upload()`
  helper (label match on "CV Upload").
- **Two required legal consent checkboxes** (`legal_documents[<id>]`, e.g. "Applicant
  Privacy Notice" and "Terms and Conditions") — both plain native checkboxes, click()
  works directly, no react-state gotcha.
- **Secondary OPTIONAL "Volcanic" diversity screen appears AFTER the main form submits**,
  on its own page, with its own two ethnicity/gender selects that come pre-set to
  arbitrary (not blank) defaults (seen: "Asian British..." and "Non-binary" — neither
  matched the applicant). It has its own "Skip" button distinct from "Submit" — using Skip
  is the correct move when not wanting to answer here (main-form demographic questions,
  if present, are the actual place to answer truthfully; this second screen is a duplicate
  ask). Clicking Skip completes the application and lands on `/apply/completed` with a
  "Your application has been sent!" success message — this is the definitive success
  signal to check for.

## Success signal
URL changes to `.../apply/completed` and page shows "Success — Your application has been
sent! Thank you for applying for <role>."
