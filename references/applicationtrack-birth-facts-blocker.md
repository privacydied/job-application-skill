# applicationtrack birth/nationality — RESOLVED (MI5 / MI6 / GCHQ)

## Status: RESOLVED 2026-07-17 — the facts ARE now recorded. Do NOT re-block on this.

The `applicationtrack.com` (VacancyFiller) multi-page eform used by all three UK
intelligence tenants (MI5, MI6, GCHQ — one credential row in `ats-credentials.csv` spans
all three) has a **Personal Details** section that requires the applicant's OWN birth /
nationality facts. **They are recorded** in `references/applicant-profile.md`
(§"Applicant's own birth / nationality", user-confirmed 2026-07-17) — read them there and
fill the eform; do NOT ask the user again, and do NOT re-report this as a wall.

## ⛔ TEST-GATE HARD STOP (the real remaining blocker, not birth facts)
Some MI5/MI6/GCHQ vacancies do NOT open a fillable eform first — starting the application
lands on **"Test in progress"** with a Cubiks (or similar) **timed online aptitude /
psychometric assessment** (e.g. MI5 SRE 3772 → "connected to our integrated online
assessment provider, Cubiks … complete within 90 minutes"). **This is a hard stop, not a
wall:** it is the applicant's own reasoning test; you cannot truthfully complete it. Surface
the test gate and stop — do NOT fabricate answers or skip past it. Verify by reading the
application landing text ("Test in progress" / "Cubiks") before assuming the eform is
reachable. Roles whose application opens the eform directly (e.g. MI5 Platform Engineer
3781) are fully drivable.

## Apply-entry recipe (vacancy detail page has NO visible Apply button)
On the opp detail page there is no "Apply" button — only an info link. The apply action is a
hidden **POST form** whose action ends in `/opp/<REF>/apply/en-GB`. Submit it (click its
submit button) to create the application and land on `/candidate/application/<ID>` (state
"Application For <Role>"). From there, the form sections are reached via the
`/candidate/eform/<ID>/page/N` URLs; the section tracker's `a.jump-to-page` anchors carry
`href`s to page/1…page/7 (Personal Details → Minimum Eligibility → OOI → Adjustments →
Security Vetting → Equal Opportunities → Submit). Direct URL nav to `/page/N` does NOT switch
VacancyFiller pages (position is tracked via hidden `page_number`/`next_page_num` fields) —
advance with the `continue_button` POST, then re-open the eform to read the refreshed tracker.

## The Personal Details fields the eform needs (fill from the profile)
- **Country of birth** (the select only offers "United Kingdom"; the applicant was born in
  England → pick **United Kingdom**).
- **County of birth** — dependent select, populates AFTER Country is set.
- **Town/city of birth**.
- **Nationality at birth**; **currently holds British nationality?**.
- **Any other / dual nationality?** — the applicant IS a dual national (confirmed): set
  "other nationality"/"dual nationality" = Yes, pick the second nationality, and fill the
  revealed "please state other nationalities" free-text truthfully.
- **Resided outside the UK in the past 10 years?** — No.
All exact values are in the profile's birth/nationality block.

## Mechanics that made 3788 submit (reusable for the other MI5/MI6/GCHQ roles)
- **Not an account wall:** the MI5 credential row logs into all three tenants; login
  redirects to the candidate area (MI5 = `appcentre-1/brand-5/user-<id>`). MI5 3788 and GCHQ
  3780 are already submitted on this account.
- Drive the section tracker with `sites/applicationtrack.com/scripts/diagnose.py` (read-only,
  per-section status) → `autofill.py`; hand-fill Personal Details / Family Details from the
  profile (Country of birth is a dependent select — set Country first, then County).
- **CV is a PASTE textarea, not an upload.** **Family Details** needs both parents' full
  vetting detail (names/addresses/nationalities/DOBs/places of birth) — all in the profile's
  Family details block. Address fields reject commas.
- After Submit, the eform may advance to a secondary "Helpful Hint" eform — the main
  application IS submitted; **verify "Submitted <date time>" on the candidate application
  list**, capture that as `--proof`, and log it.

See `sites/applicationtrack.com/NOTES.md` + `sites/applicationtrack.com/quirks.jsonl` for the
full flow and tenant paths.
