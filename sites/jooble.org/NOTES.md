# jooble.org ("Jooble", uk.jooble.org) — site notes

Large international aggregator; the UK index carries agency + direct-employer listings that
overlap Adzuna/Talent only partially. Single JSON POST — no browser, no scraping.
Feed: `scripts/feed.py` (board slug `jooble`).

**Status: NEEDS-KEY.** Built and unit-tested; runs the moment a key lands.

## Why on-profile
`location` filters server-side (with `radius`), so the feed only emits London-area roles.
Adds aggregator breadth beyond Adzuna without a browser.

## Key — `ats-credentials.csv`, never env
Add:

    jooble-api,<YOUR_API_KEY>,,<today>

`site` = `jooble-api`, **email column = the key**, password column empty — mirrors the
`adzuna-api` row convention. (Grepping env for the key is the documented false-negative —
the key lives in the CSV.)

Get a key: <https://jooble.org/api/about>. **Not self-serve like Adzuna**: you submit a form
(name, position, email, **website**, phone) and Jooble issues the key to webmasters/portal
operators. There is no instant-download key page — the API is pitched at sites republishing
Jooble results, so the "website" field is a real barrier, not a formality.

## API
    POST https://jooble.org/api/<KEY>
    Content-Type: application/json
    {"keywords": "...", "location": "London", "radius": "25", "page": "1"}

The key is part of the **path**, not a header or query param. The query is the POST body —
this is the only POST-based board in the repo, which is why `httpfeed.Board` has a `body`
knob (set `body`, and the fetch becomes a JSON POST).

## Verified without a key (2026-07-17) — two failure modes that look nothing alike
- A **UUID-shaped but unregistered** key reaches Jooble's **origin** and is rejected:
  `HTTP 403` + body `Error 403 Access is available only for registered users`, with
  `cf-cache-status: DYNAMIC` proving it passed through Cloudflare to the app. So the
  endpoint is **alive** and plain urllib reaches it — no browser needed.
- A **malformed (non-UUID)** key instead trips Cloudflare's "Just a moment…" JS challenge.
  That is a routing artefact, **not** evidence the API is bot-walled. Do not "fix" it with a
  browser — fix the key.
- `feed.py --all` with no key exits **2** and prints the CSV row + signup URL.

## ⚠️ Unverified-live
Request and response field names are Jooble's conventional partner-API shape and are **not
confirmed**: no key exists to make a real call, and Jooble publishes **no public schema
page** — `https://jooble.org/api/about` describes the product and the key-request form only,
and the deeper `/api/*documentation` paths 403. `parse()`/`normalize()` are defensive
(multiple key spellings, tolerant of missing fields).

Expected response:

    {"totalCount": N,
     "jobs": [{"title","location","snippet","salary","source","type","link","company",
               "updated","id"}]}

**On the first run with a real key, dump one raw response and tighten this** — do not assume
these names are right.

Live test once the key is in:

    python3 sites/jooble.org/scripts/feed.py --what "designer" --where London --all

## Apply-path reality
`link` points **off-site** — Jooble is an index, not an ATS. It forwards to the originating
board or the employer's own ATS, so there is no Jooble account and no apply form. Expect
destinations that this repo already handles as their own boards, so **cross-board duplicates
are normal**; the tracker/precheck dedup absorbs them.

## Quirks
- Body values are sent as **strings** (`"page": "1"`, `"radius": "25"`), not ints.
- Salary is free text (`"£40,000 - £50,000 a year"`), not numeric min/max — passed through
  as-is rather than reformatted.
- `id` may be absent on some rows; the feed falls back to the `link` as the id.
