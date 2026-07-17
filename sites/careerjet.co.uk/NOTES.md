# careerjet.co.uk ("Careerjet") — site notes

UK-facing aggregator indexing employer sites and other boards. Plain JSON over HTTPS — no
browser, no scraping. Feed: `scripts/feed.py` (board slug `careerjet`), targeting **API v4**.

**Status: NEEDS-KEY (v4).** The legacy public API this board was historically reached
through is **dead**. Built and unit-tested against v4; runs the moment a key lands.

## The legacy public API is dead — do not resurrect it
`http://public.api.careerjet.net/search?...&affid=<id>` — the historically "free partner id"
endpoint — no longer works for new users. Verified 2026-07-17, verbatim:

    HTTP 401
    {"error":"The legacy Job Search API is only accessible for authenticated legacy users.
      Please use the new API (v4) instead: https://www.careerjet.com/partners/api",
     "type":"ERROR"}

Reproduced identically **with and without an affid**, and **with and without a Referer
header** — no generic or borrowed affid revives it. Two red herrings guard the real blocker
and each looks like the actual problem:
- omitting `user_ip`/`user_agent` → `{"error":"missing param user_ip or user_agent"}`
- omitting a Referer → HTTP 403 `{"error":"Undeclared referrer. Please add a Referer header…"}`

Satisfy both and you still hit the 401 above. The endpoint answers HTTP 200 on the error
JSON in some of these states, so "it returns 200" proves nothing here.

## API v4 — alive
    GET https://search.api.careerjet.net/v4/query
        ?keywords=&location=&locale_code=en_GB&page=<1-10>&page_size=<1-100>
        &sort=date&radius=<n>&user_ip=<ip>&user_agent=<ua>

Auth, confirmed live by the API's own keyless error, verbatim: *"You did not provide an API
key. You need to provide your API key via HTTP Basic Auth as username value. The HTTP Basic
Auth password needs to be empty."* So `Authorization: Basic base64("<KEY>:")` — the same
scheme Reed uses.

`user_ip` and `user_agent` are **required on every call**. They are meant to be the end
user's; an unattended agent has no end user, so they default to this host's outbound values
(override with `--user-ip`).

## Key — `ats-credentials.csv`, never env
Add:

    careerjet-api,<YOUR_API_KEY>,,<today>

`site` = `careerjet-api`, **email column = the key**, password column empty — mirrors the
`adzuna-api` row convention. (Grepping env for the key is the documented false-negative —
the key lives in the CSV.)

Get a key: <https://www.careerjet.com/partners/api>. **Not self-serve**: per their docs,
*"Each publisher website requires a unique API key, which you can obtain from your Publisher
account"* — so it needs a publisher registration (a website), not a free instant id. This is
a strictly higher bar than the old affid it replaced.

## Verified without a key (2026-07-17)
- v4 keyless **and** bogus-key calls both return HTTP 401 with the JSON auth message above —
  endpoint alive, error path unambiguous.
- `feed.py --all` with no key exits **2** and prints the CSV row + signup URL, and warns off
  the dead affid route.

## ⚠️ Unverified-live
Field names come from Careerjet's published v4 docs rather than a real response (no key to
call with). They are more trustworthy than Reed's — the v4 docs name JSON fields explicitly
— but still confirm against a raw dump once a key lands.

Documented response:

    {"type":"JOBS", "hits":N, "pages":N, "response_time":…, "message":…,
     "jobs":[{"title","company","date","description","locations","salary",
              "salary_currency_code","salary_min","salary_max","salary_type","site","url"}]}

Live test once the key is in:

    python3 sites/careerjet.co.uk/scripts/feed.py --what "designer" --where London --all

## Apply-path reality
`url` is a careerjet.co.uk job page that forwards **off-site** to the originating board or
the employer's ATS. Careerjet hosts no apply form and needs no account, so there are no
login credentials for it. Since it indexes other boards, **cross-board duplicates are
normal**; the tracker/precheck dedup absorbs them.

## Quirks
- `page` is capped at **10** and `page_size` at **100**; the feed returns an empty URL past
  page 10 so the runtime stops cleanly instead of 400-ing.
- v4 ships **both** a pre-rendered `salary` string and numeric `salary_min`/`salary_max` +
  `salary_type` (Y/M/W/D/H). The feed prefers the string (already localised) and composes
  from the numbers only as a fallback.
- Location sanity is server-side (`location` + `radius`, default 25). No title filtering —
  precheck.py's job.
- Job ids are the `/jobad/<hash>` segment of the URL.
