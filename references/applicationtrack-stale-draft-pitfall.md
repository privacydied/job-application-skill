# applicationtrack — stale draft vs live editable eform

A role that appears ONLY as a row in the candidate "Your applications" list — with
NO matching open vacancy on the live jobboard (`/candidate/jobboard/vacancy/N`) —
is frequently a STALE draft. Seen live: MI5 **Interaction Designer Ref. 3639**,
a 2016 submission that still shows in the app list but is not currently open.

**How to tell it is NOT drivable (don't burn a pass):**
- The opp detail page (`/candidate/so/pm/1/pl/4/opp/<ref>-.../en-GB`) has NO apply
  form/button — only informational job text. (A LIVE role has a hidden
  `form[action*="/apply"]` whose submit creates the application — see
  `applicationtrack-vacancyfiller-fieldmap.md` §1.)
- The application's "View Application" page exposes only `view_form/<ID>` links
  (read-only summaries). There is:
  - NO `/candidate/eform/<ID>/page/N` editable path,
  - NO `a.jump-to-page` section tracker (so `diagnose.py` errors "not on an eform
    tab"),
  - NO Edit / Continue / Submit button.
- Personal Details may already be pre-filled from the old draft, but you cannot
  edit or submit it from the read-only `view_form` view.

**Conclusion:** if a role is not on the live jobboard AND its app page has only
`view_form` links, it is not submittable through the sanctioned
`diagnose.py -> autofill.py` path. Skip it; do NOT fabricate an apply or log it
`Applied` (no confirmation artifact exists).

**Drive-order discipline:** always enumerate the LIVE jobboard vacancies first
(`/candidate/jobboard/vacancy/N`, filter by Department). Only drive roles that
(a) appear live AND (b) pass `check_title` (on-profile, not senior/off-tier). A
stale draft that happens to be on-profile is not a live opening.
