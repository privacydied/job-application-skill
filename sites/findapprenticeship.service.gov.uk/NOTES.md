# findapprenticeship.service.gov.uk (GOV.UK Find an Apprenticeship) — verified site notes

DfE's statutory apprenticeship board. Every English apprenticeship vacancy **must** be
advertised here, so it is the complete national set, not a sample. Feed slug `apprentice`.

On-profile for DevOps/security and IT support (§13) via **Level 4 Cyber Security
Technologist / Network Engineer / Software Development Technician** and the **Level 6 Digital
& Technology Solutions** degree apprenticeship — the funded route into gov/defence tech that
does not need a prior degree. Employer mix skews SME + big-corp early careers.

## Sourcing (VERIFIED live 2026-07-17)
- **Server-rendered GOV.UK Design System HTML** — plain curl, no browser, key or login.
- `GET /apprenticeships?searchTerm=<terms>&location=<place>&distance=<miles>&pageNumber=N`.
  `pageNumber` is **1-based**, 10 results/page. Result total is in `<title>`
  (`"51 results found (page 1 of 6)"`).
- Cards: `li.das-search-results__list-item`; title link
  `a.das-search-results__link[href="/apprenticeship/<VACREF>"]` where VACREF (e.g.
  `VAC2000040502`) is the stable tracker id. Employer is the bare
  `p.govuk-body.govuk-!-margin-bottom-0`, location the `p.govuk-body.das-!-color-dark-grey`;
  every later `<p>` is a labelled `<b>Wage</b>` / `<b>Training course</b>` field.
- Cooldown key = the `searchTerm`.

### ⚠️ Two traps that misrepresent the board's size
1. **`distance` defaults to `all` ("across England"), which silently ignores `location`.**
   A `?searchTerm=cyber&location=London` URL is a *national* search, not a London one. The
   `<select name="distance">` only accepts `2/5/10/15/20/30/40` or `all` — `50`/`100` are not
   options and render an error page with an empty `<title>`. The feed therefore always sends
   a mileage (default **30**, ≈ commutable London) whenever `--where` is given.
2. **`searchTerm` matches the apprenticeship *standard*/title, not free text** — far stricter
   than an aggregator keyword search.

Measured counts:

| query | results |
|---|---|
| no params (whole board) | **4,659** |
| `location=London&distance=30` | 921 |
| `location=London&distance=10` | 119 |
| `location=NOTAPLACE&distance=30` | 0 (geocoding is real) |
| `searchTerm=digital` (national) | 51 |
| `searchTerm=cyber` (national, `distance=all`) | **2** |
| `searchTerm=cyber&location=London&distance=30` | 1 |

So a near-empty result for a sensible query is the **board being honest**, not the feed
breaking. Widen by dropping `--what` (London/30mi alone = 921 live vacancies) and let
precheck.py do the title filtering. Volume is also **seasonal**: postings cluster Jan–May for
September starts, so mid-July is a trough.

## Apply path reality — account-gated, DfE-native or employer link-out
"Apply now" on a vacancy leads to the DfE apprenticeship application, which requires a **Find
an Apprenticeship candidate account** (sign in / create account). Some employers instead link
out to their own site. Which one it is only resolves on the JD page, so `ats_hint` is left
empty.

## Quirks
- ⚠️ **GOV.UK escapes with HEX entities** (`&#xA3;` for £, `&#x27;` for `'`), and
  `httpfeed.clean()` decodes only NAMED (`&pound;`) and DECIMAL (`&#163;`) entities — hex
  ones pass straight through and would ship `"&#xA3;19,747"` as the salary. The feed decodes
  them locally via `html.unescape` (`_txt`). Worth fixing in the shared `clean()` if another
  board hits it.
- Wage is free text: `"£19,747 a year"`, `"Competitive"`, or a band. `"Competitive"` is
  normalised to `""` rather than kept as a fake salary.
- Location can be `"Recruiting nationally"` (i.e. remote/dispersed), which passes the
  distance filter — precheck decides.
- No CAPTCHA on the sourcing path.
