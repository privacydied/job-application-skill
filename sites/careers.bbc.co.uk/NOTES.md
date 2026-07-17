# careers.bbc.co.uk (BBC careers) — verified site notes

Major London public-service digital employer, hitting several profile families at once:
design/UX and digital content (§14), software/DevOps and platform (§13), plus the
public-service culture that suits the charity-digital angle. Openings are largely **not
syndicated** to the aggregators, so this is additive reach. Feed slug `bbc`.

## ⚠️ The HTML is a dead end — the board is API-only
`careers.bbc.co.uk/search/` is **SAP SuccessFactors RMK**, but the modern **React** variant:
to plain curl it returns a ~101KB page containing the search *form* and **zero job tiles**
(`jobTitle-link` count = 0), then hydrates client-side. Scraping that HTML yields nothing —
it looks like a dead board but is not.

The React module (`performancemanager.successfactors.eu/…/rmk-jobs-search/`) calls a clean
JSON API, which the feed uses via `httpfeed.Board.body` (the runtime's POST hook):

```
POST https://careers.bbc.co.uk/services/recruiting/v1/jobs
Content-Type: application/json
{"locale":"en_GB","pageNumber":0,"sortBy":"","keywords":"digital","location":"London",
 "facetFilters":{},"brand":"","skills":[],"categoryId":0,"alertId":"","rcmCandidateId":""}
```

- **No auth, no cookie, no CSRF.** The browser sends `x-csrf-token`, but the endpoint returns
  200 without it (verified with the header absent and with a bogus value).
- **GET is rejected (405)** — it must stay a POST.
- Response: `{"jobSearchResult":[{"response":{…}},…], "totalJobs":N}`.
- ⚠️ **`pageNumber` is 0-based**, unlike every other board here (10 results/page).
- Cooldown key = the `keywords` term.

Row fields: `id`, `unifiedStandardTitle`, `unifiedUrlTitle`/`urlTitle`, `jobLocationShort`,
`filter2` (department), `filter4` (contract), `unifiedStandardStart`/`End`, `currency`.
Job URL = `/job/<urlTitle>/<id>/` — ⚠️ `urlTitle` is **already percent-encoded** by the API
(`"Digital-Video-Manager%2C-Bluey"`); re-encoding double-escapes the `%2C` and 404s.

### ⚠️ The board is international
BBC World Service posts Delhi/Abuja/Nairobi roles with NGN/ZAR `currency`, and those rows
carry **no `jobLocationShort` at all**. The POST body's `location` is a real server-side
filter (`digital` → 45 unfiltered vs **11** for London), so `--where` does the work. Rows with
no location are passed through with `""` for precheck to judge rather than being dropped
here. Whole board = 67 open vacancies at verification.

`jobLocationShort` is a **list** of `"<City>, <ISO3>, <postcode><br/>"`, usually repeated once
per posting site; the feed de-duplicates and strips the trailing `<br/>`.

## Apply path reality — account-gated SuccessFactors
Apply is on-site, via the RMK candidate flow, and requires a **BBC careers candidate
profile**. Treat as a login gate: source freely, apply with the user's authenticated session
(creds in the gitignored `ats-credentials.csv`). `ats_hint` is set to `successfactors`.

Same ATS vendor as `sites/tfl.gov.uk/` — but TfL runs the **classic server-rendered RMK**
whose search HTML is scrapeable, whereas this is the React/API variant. One vendor, two
sourcing recipes; do not assume they interchange.

## Quirks
- **Salary is not in the search API** (only a `currency` code), so the feed emits `""` rather
  than guessing; the JD carries the band.
- JD pages return 200 with the generic SPA title `"This is Your BBC | Jobs and Careers with
  the BBC"` — the JD body is client-rendered too, so a title check cannot confirm a job
  exists. jd.py needs the API (or a render) for BBC detail.
- `careers.bbc.co.uk` also links `bbctechsupt4.valhalla2.stage.jobs2web.com` — a **staging**
  host leaked into the live nav. Ignore it; it is not the production board.
- No CAPTCHA on the sourcing path.
