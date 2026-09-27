# caterer.com — site notes

A TotalJobs Group sub-brand (StepStone-owned, same as totaljobs.com) — hospitality/catering
jobs. Discovered live 2026-09-27 via an Adzuna redirect (Caprice Restaurants AI/Motion
Designer posting).

## Drivable with `sites/totaljobs.com/scripts/tj_apply.py` directly, no separate driver needed

Runs the identical Smart Apply flow as totaljobs.com — same review-form shape (Contact
details -> Experience/CV -> Additional questions -> Send application), same confirmation
banner ("Application sent!"). `tj_apply.py <caterer.com-job-url>` worked unmodified on a
live posting. Add `caterer.com` job URLs to the same drivable-board bucket as totaljobs.com
when triaging an Adzuna redirect target — do not build a separate driver (no-divergent-
duplicate rule).

## Screening-question widget shape (verified live)

This posting's "Additional questions" block used:
- Positional radio groups with NO discoverable label/name association in the DOM
  (`atsform.set_radio`/`combobox_pick` both report NOT_FOUND) — but each `<input
  type=radio>` DOES carry its real option text as its `value` attribute, and a
  `data-testid` like `sqIndexatsiQuestions.id:atsFlexi-XXXX-comp0-radio-0` where `compN`
  indexes the QUESTION and `radio-N` indexes the OPTION within it. Fix: query
  `input[type=radio]`, filter/click by `.value` directly (e.g. `r.value==='Yes'`) rather
  than trying to resolve a label. When two questions share an option string ("No" appeared
  in both here), use position within the filtered list to disambiguate (second "No" was the
  second question's answer here).
- A plain native `<select>` for "How did you hear about us?" — genuinely offered "Caterer"
  as a source option, which is both accurate and the honest choice when sourced via this
  board.

Same underlying StepStone/Genesis form-rendering engine as other TotalJobs-family boards, so
this shape likely recurs on totaljobs.com itself and other Group brands — if
`atsform.set_radio` NOT_FOUNDs on a totaljobs-family posting, try the value-based
positional-click technique above before concluding the field can't be driven.
