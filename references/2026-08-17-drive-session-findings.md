# 2026-08-17 drive session — what broke, what was fixed, what is still open

A single long Greenhouse-heavy drive, run as parallel lanes. Every item below was found by
DRIVING, not by reading code — which is the point: eleven defects had survived in-tree because
nothing exercised them end to end.

## Fixed (committed, 306/306 guard tests green after each)

| # | File | Defect | Cost when it fired |
|---|---|---|---|
| 1 | `cfx.py` | `prune_tabs` reaped other processes' tabs (its own docstring documented the hazard and deferred the fix) | killed live drives mid-application; also the root cause of two lost applications |
| 2 | `gh_apply.py` | uploaded a hardcoded `/uploads/base-resume.pdf`, ignoring the config's documented `cv` | **every** Greenhouse application sent the generic master résumé |
| 3 | `gh_apply.py` | a mid-drive tab death raised out of `_fill_eeo` | traceback, no tracker row, posting silently lost |
| 4 | `gh_apply.py` | page location gate trusted the first 4 lines of `<main>` | invented "abroad" from form chrome; rejected Stripe (Ireland/UK) |
| 5 | `gen_gh_config.py` | ~12 label patterns missed (rightS to work, expected BASE salary, work permit, convictions, opt-in, first-hear, US-state residency, …) | each blocked a whole posting on a question with a truthful answer |
| 6 | `gen_gh_config.py` | `build()` overwrote the config file | destroyed written essay answers; 4 postings then timed out on empty required fields |
| 7 | `gen_gh_config.py` | sentence-option work-auth selects matched nothing | 700s timeout per affected posting |
| 8 | `atsform.py` | `NO_TARGET` after a React re-render treated as fatal | **all five** 700s timeouts ended on this line |
| 9 | `atsform.py` | no country synonym; no first-person ethnicity labels; no `legal address` alias; parenthetical not stripped from EEO values | required fields left empty → submit bounced |
| 10 | `atsform.py` | typeahead retry only shortened from the LEFT | "University of the Arts London" degraded to "Univer"; School never bound |
| 11 | `fetch_verification_code.py` | emailed codes treated as reusable | two applications to one employer raced; a correct one was logged `Blocked` |
| 12 | `blockers.py` | `record` read kind/site positionally and silently discarded `--kind/--site/--detail` | the highest-leverage human action was filed as an empty, mislabelled row |

Plus `prerender-pdfs.sh`: serial retry for concurrent-Playwright connect timeouts (4 of 11
healthy renders were being reported FAIL).

## Channel unblocked: Trac (`apps.trac.jobs`) — NHS + UKHSA + CSJ "advertiser's site"

`sites/trac/NOTES.md` had concluded apply was *"account-walled with a reCAPTCHA, which is a
full halt"*. Both halves were wrong — reCAPTCHA v2 is a **sanctioned auto-solve**, and ATS
account creation is explicitly **not** a hard stop (SKILL.md §Hard stops). Account created,
recorded, and a full UKHSA application filled. Details + the three traps: `sites/trac/NOTES.md`.

## Still open (do not re-derive these)

1. **Referees** — the only thing between the filled UKHSA draft (194503463, deadline
   20-Aug 23:59) and submission, plus every other NHS/UKHSA vacancy. Also the socio-economic
   question (main earner's occupation at age 14). Neither is in `applicant-profile.md`, and
   neither may be invented. Blocker `20260817T024422-apps.trac.jobs`.
2. **SmartRecruiters is shadow DOM.** The form is web components, so `atsform`'s light-DOM
   resolver finds nothing — and `_RESOLVE` returns a *selector* that callers pass to
   `document.querySelector`, so the fix means changing how primitives ADDRESS a control, not
   just how they find one. Verified piercing probe + shape of the fix: `sites/smartrecruiters/NOTES.md`.
   Worth building: 41 companies / 1,986 jobs in the registry.
3. **`fill_gaps_from_bank` cannot see some required-empty fields.** Scopely's `Preferred Last
   Name*` and `Country*` bounced the submit while the bank held both answers and reported
   `0 answered, 4 unknown`. So its `_UNANSWERED` walk is missing fields the validator counts —
   the same class as the duplicate-name fields on Akuna ("Legal First Name" alongside a plain
   "First Name": the defaults pass binds the first and leaves the second empty). Needs a
   post-fill backstop that re-reads what the FORM says is required, rather than what the walk
   found.
4. **Creativepool** — an account already exists for the applicant's email but no password is
   stored, and the reset email had not arrived after ~10 minutes. ~13 on-lane London design
   roles sit behind it.
5. **ifyoucouldjobs applications are `mailto:`** — real applications, but sending email is a
   capability this skill does not have (IMAP read only, no SMTP send).

## Honest inventory note

A full keyless ats-direct harvest returned **48,029 jobs / 860 employers**. After UK+remote
screening, the seniority screen (junior→mid), and tracker dedup, the genuinely fresh
convertible pool was **14 postings**, plus ~20 retryable from the 141 previously-`Blocked`
rows. That is consistent with SKILL.md's convertible-pool warning that raw counts run 10–50×
the convertible set — worth re-reading before promising any large N.
