# reed.co.uk — Reed **official API** notes (`scripts/feed_api.py`)

Scoped to the API feed only. The browser scraper (`scripts/feed.py`, board slug `reed`) is a
separate, pre-existing feed and is **not** documented or modified here.

**Status: NEEDS-KEY.** Built and unit-tested; runs the moment a key lands.

## Why a second Reed feed
Same site, two sourcing paths. `feed.py` drives camofox against Reed's bot-walled search
HTML (slow, needs `CFX_KEY`). `feed_api.py` is a plain authenticated HTTPS GET returning
structured JSON — no browser, no login, runs anywhere. Both are kept: the API needs a key,
the scraper does not.

## Dedup contract (the part that matters)
The two feeds share an id scheme and a tracker. `feed_api.py` emits the **same bare numeric
id** and the **same `source: "reed"`** as the scraper, and reuses the scraper's tolerant
pattern `reed\.co\.uk/jobs/(?:[^/,\s]+/)?([0-9]+)`, which folds both shapes together:

    https://www.reed.co.uk/jobs/132                  -> 132   (bare, as stored in tracker)
    https://www.reed.co.uk/jobs/bank-manager/132     -> 132   (slugged, as returned live)

If the two feeds ever disagree on the id, every posting sourced by one gets re-applied by
the other. Only the cooldown slug differs (`reedapi` vs `reed`) so the two paths exhaust
independently.

## Key — `ats-credentials.csv`, never env
Add:

    reed-api,<YOUR_API_KEY>,,<today>

`site` = `reed-api`, **email column = the API key**, password column empty — mirrors the
`adzuna-api` row convention. Free key:
<https://www.reed.co.uk/developers/jobseeker> → "Sign up for a reed.co.uk API Key" (an
in-page form; there is no standalone `/developers/signup` URL — that path 404s).

**The existing `reed.co.uk` row is the website login** used by the scraper's apply flow. It
is not an API key and this feed cannot use it. (Grepping env for the key is the documented
false-negative — the key lives in the CSV.)

## API
    GET https://www.reed.co.uk/api/1.0/search
        ?keywords=<terms>&locationName=<city>&distanceFromLocation=<miles>
        &resultsToTake=<n ≤100>&resultsToSkip=<n>
    -> {"results":[…], "ambiguousLocations":[…], "totalResults":N}

Auth, quoted from Reed's docs: *"You will need to include your api key for all requests in a
basic authentication http header as the username, leaving the password empty."* So
`Authorization: Basic base64("<KEY>:")` — key as username, **empty password**.

Location sanity is server-side (`locationName` + `distanceFromLocation`, default 10 miles of
London via `--radius`). No title filtering — precheck.py's job.

## Verified without a key (2026-07-17)
- The exact URL the feed builds returns **HTTP 401 with an empty body** — auth is the only
  thing missing; the params are accepted (a bad param would 400).
- Keyless and bogus-key calls both 401, so the error path is unambiguous.
- `feed_api.py --all` with no key exits **2** and prints the CSV row + signup URL.

## ⚠️ Unverified-live
The per-row JSON **field names** (`jobId`, `jobTitle`, `employerName`, `locationName`,
`minimumSalary`, `maximumSalary`, `currency`, `date`, `jobUrl`) come from Reed's published
docs, which list them in prose ("Job Id", "Employer Name") rather than as a JSON sample.
No real response has been seen. `normalize()` is defensive (camelCase first, PascalCase
fallback). **On the first run with a real key, dump one raw response and tighten this.**

Live test once the key is in:

    python3 sites/reed.co.uk/scripts/feed_api.py --what "designer" --where London --all

## Quirks
- `resultsToTake` is capped at 100; paging is `resultsToSkip`, not a page number.
- Dates are `dd/mm/yyyy` and are converted to `yyyy-mm-dd`.
- Salary is hidden entirely when the employer marks it hidden — expect empty salary rows.
- `ats_hint` is always empty: the search API does not expose the Easy Apply badge that the
  scraper reads off the card, so only the JD page reveals whether apply is on-site.
- Ambiguous locations come back in `ambiguousLocations`, which this feed ignores.
