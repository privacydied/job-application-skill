# talent.com ("Talent.com", uk.talent.com) — site notes

Large UK aggregator: agency stock (Hays, Robert Half) plus direct employers (LexisNexis,
CloserStill Media, hedgehog lab, Royal Mail). Server-rendered HTML — no key, no login, no
browser. Feed: `scripts/feed.py` (board slug `talent`).

## Why on-profile
`l=London` filters server-side, so the feed only ever emits London-area roles — no
client-side geography guessing. Coverage overlaps Adzuna/Reed only partially, so it adds
distinct employers rather than duplicating an existing board.

## Sourcing — HTML cards, **not** JSON-LD, and **not** an API
Read this before "improving" the parser; each of these is a verified dead end:
- The search page ships exactly **one** `application/ld+json` blob, and it is an `ItemList`
  of bare `{"url": "https://uk.talent.com/view?id=…"}` entries — **no JobPosting objects**,
  no titles, no companies. `httpfeed.ld_json()` alone yields ids and nothing else.
- **There is no public JSON API.** `uk.talent.com/api/jobs` and `/jobs/api` both return the
  SPA's HTML shell with **HTTP 200** (the router treats "api" as a locale — the response
  literally says `<html lang="api">`), which looks like a working endpoint until parsed.
  `api.talent.com/v2/*` returns 403 `{"message":"Missing Authentication Token"}`.
- The real source is the card markup, anchored on the **stable data attributes**:
  `<div data-job-id=… data-new-id="<id>" data-testid="jobcard-container-<id>">`.
  `data-new-id` is the id used by `/view?id=<id>` and stored in the tracker.

Everything else is CSS-module hashed (`JobCard_title__X32Qk`) and the hash changes on
redeploy, so every selector matches `JobCard_<part>__\w+` — never a literal hash.

## Paging — `p=<n>`
Verified. **`page=` and `start=` are silently ignored** and return page 1 unchanged: fake
pagination that looks like it works and quietly re-scrapes the first page forever.

## Apply-path reality — not a plain redirect
- `/view?id=<id>` is a Talent.com-**hosted** JD page. It returns HTTP 200 with **no
  server-side redirect** (`num_redirects:0`) — following it with `curl -L` lands you back on
  talent.com, not on the employer.
- Its "Apply" control is an anchor to `/redirect?id=<id>&pid=<hash>&action=f-link`, a
  Talent.com interstitial that performs the off-site hop. That hop is **client-side**:
  curling `/redirect` also returns 200 with no `Location` header, so the final ATS
  destination is only resolvable in a browser, and `pid` is minted into the page at render
  time (it cannot be constructed from the feed row alone).
- Sourcing stays fully HTTP-only; only **applying** needs the browser.
- Talent.com hosts no apply form and needs no account, so there are no credentials for it in
  `ats-credentials.csv`.

## Quirks
- Salary is absent from most cards and has **no dedicated class** — it sits in an
  unlabelled chip whose class is fully hashed (`sc-fcd630a4-10`), alongside
  "Full-time"/"Temporary" chips. The feed matches it on its `£` text instead. Typically
  ~6/35 rows are priced.
- `location` strings are inconsistent for the same place: `London, England, GB`,
  `London, England, GBR`, `London, LND, GB`, `London, England, .GB`, `City of London, GB`.
  Treat as display text, not a key.
- Company can be a feed handle rather than a name (e.g. `hays-gcj-v4-pd-online`).
- ~20 cards/page; `--pages 2` yields ~35 postings.
