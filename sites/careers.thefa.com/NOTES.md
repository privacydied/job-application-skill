# careers.thefa.com (The FA — Eploy ATS) — verified site notes

## Discovery path
Totaljobs listings for The FA route through totaljobs' own harmonised-apply-button,
which OPENS A NEW TAB to `careers.thefa.com` rather than doing an in-platform Totaljobs
Smart Apply. The totaljobs "confirmation/success" page shown in the ORIGINAL tab
("Did all go well with your application? If not, you can still submit your application
on the company website") is NOT proof of a real submission — always check
`cfx.list_tabs()` for a newly-spawned tab to the real employer ATS before trusting that
totaljobs confirmation screen. Drive the REAL application in the new tab.

## Eploy ATS account + form pattern (verified live 2026-08-23, UX Designer WNSL1121)
- New account: email → "Next" reveals a full register form (password, confirm password,
  first/last name, "Where did you see this vacancy?" dropdown, GDPR consent checkbox).
  Creds saved to `ats-credentials.csv` under `careers.thefa.com`.
- Application is a 5-section wizard: Personal Details, CV & Cover Letter,
  Equality/Diversity/Inclusion, Referral, Submission. Ground truth for whether a section
  actually counts is the `ulListItem` class on the "My Application Form" page
  (`https://careers.thefa.com/jobs/app/<id>/home/`) — `ToDo` vs `Completed` — NOT the
  read-view display of saved data, which can render correctly while the section is still
  `ToDo`.
- ⚠️ **Trap: filling fields + clicking the field-level "Save" (`buttonSubmit_ajaxSave`)
  is NOT enough to mark a section `Completed`.** It re-renders a correct READ VIEW (values
  all shown correctly) but the section stays `ToDo`. You MUST additionally click the
  page-level **`buttonSubmit_next`** ("Next") button from that read view to flip the
  section to `Completed`. Verified: Personal Details and Equality/Diversity both stayed
  `ToDo` after ajaxSave-only; both flipped to `Completed` immediately after a subsequent
  `Next` click with no field changes.
- Referral section's inline select (radio-like single select, "Have you been referred by
  one of our employees?") needs the ROWLINK edit pattern: the read view shows a link whose
  text renders as the raw template stub `ROWLINK:ENTERREQUIREDINFO:` when the section is
  incomplete — click it to open the field-level edit widget, set the select, click ITS
  "Save" button (not Next) to commit that row.
- CV upload: the visible instructions say "txt, rtf, doc or docx" but the actual
  `data-fileextensionlist` attribute on the `a.fileuploadbutton` trigger includes `pdf` —
  a PDF resume uploads and is accepted despite the misleading copy. Use
  `cfx.post('/tabs/<tab>/uploadViaChooser', {trigger:'a.fileuploadbutton', path:'<file>.pdf'})`
  (plain `atsform.upload()` fails — no `<input type=file>` exists until the chooser button
  is clicked).
- Submission section: tick `checkboxlegal` (mandatory, "Please tick the box to complete
  your application"), leave `contactconsent` ("I am happy to be considered for other
  vacancies") per the applicant's own "similar jobs" preference. The visible
  "REVIEW APPLICATION FORM" button is a DISTRACTOR — it just navigates back to the
  My Application Form summary and does not submit. The real action is the `<input
  type=submit id="buttonSubmit_submit_application">` ("Submit Application"), which exists
  in the DOM alongside "Review Application Form" but may render off past the visible
  viewport in a screenshot — click it directly via id/JS rather than relying on a
  screenshot showing it. Confirmation page title: "Application Finished" / "New
  Application Submitted".

## CAPTCHA
None observed on this flow (registration or application wizard).
