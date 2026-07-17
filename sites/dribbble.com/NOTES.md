# dribbble.com/jobs ("Dribbble Jobs") — site notes

The designer-network board — product / UX / UI / graphic roles, heavily **remote-first**.
~69 live. Verified live 2026-07-17.

## Why it's on-profile
Remote is the applicant's second acceptable geography (London **or** fully-remote), and this
is the board that actually carries remote design work the UK boards don't. Inventory skews
international product/startup teams, so precheck's London/remote gate does the heavy lifting;
what Dribbble uniquely adds is the remote slice.

## Algolia is a dead end here — read this before "optimising" the feed
The page **does** ship a public Algolia config:

```
data-algolia-application-id="W5ZOF5AQ8X"
data-algolia-search-api-key="32b93de0e6eabd7b51cf093f0d7e3a1c"
```

but its indexes are `Screenshot_query_suggestions`, `User_query_suggestions` and
`ServiceOffering_query_suggestions` — **nav autocomplete for shots, designers and services.
There is no jobs index.** Querying Algolia returns shots, not jobs. The board's own GET search
is the real interface and it is server-side; the feed uses that.

## Sourcing: `scripts/feed.py [--what "product designer"] [--where London] [--pages N] [--all]`
Plain server-rendered HTML over HTTP. No browser, no key, **no login to source**.

Search is `form.js-job-search-form[action="/jobs"][method=get]`:

| param | verified behaviour |
|---|---|
| `keyword` | real server-side filter — `animator` → 1, `motion` → 31, `zzzznonsense` → 0, unfiltered → 48 |
| `location` | `London` → 3 |
| `anywhere=true` | the remote toggle |
| `page` | ~48/page; page 2 → 21, page 3 → 0 (≈69 total) |

Cards are `li.job-list-item`; id is the numeric prefix of `a.job-link[href="/jobs/<ID>-<slug>"]`.

| field | selector |
|---|---|
| link | `a.job-link[href]` |
| title | `h4.job-title` |
| company | `span.job-board-job-company` |
| location | `span.location` |
| posted | `.posted-on` |

**No salary** — Dribbble surfaces none on the index, so `salary` is left `""` rather than
faked. (Some JDs carry one; jd.py can pick it up per-listing.)

## Apply — requires a Dribbble account
The card's "Apply now" is `button[data-signup-trigger="true"][data-context="apply-job"]` — it
opens a signup/login wall, **not** an employer hop. Sourcing is free; applying is gated.
Postings are flagged `ats_hint="dribbble-account"`. Credentials, when present, live in the
`dribbble.com` row of `ats-credentials.csv`.

## Quirks
- Listings are global and multilingual — non-English titles appear
  (`Diseñador de Producto Senior (UX/UI)`). Don't assume an English title or a UK location.
- Every card renders its job link twice (`a.job-link` + a "View job" button); dedup is by id in
  the runner's pool, so this is already handled.
- `?keyword=designer` returns the unfiltered 48 — that is not a broken filter, it's a design
  board where nearly every posting matches "designer". `zzzznonsense` → 0 proves the filter is
  live.
