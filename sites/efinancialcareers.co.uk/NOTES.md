# efinancialcareers.co.uk (eFinancialCareers) — verified site notes

The finance-sector board. On-profile because banks / insurers / asset managers run large
in-house IT estates and hire the §13/§14 lanes — application support, trade-floor and
desktop support, infrastructure, SOC — but budget them on **finance payscales**, so
junior/mid IT roles here pay materially above the general-market equivalent. Distinct
inventory vs the aggregators. Wired in `pipeline.py FEEDS` as `efinancial`. Plain HTTP —
no browser, no key, no login.

## Sourcing (VERIFIED live 2026-07-17) — embedded JSON, no scraping

The search page is server-rendered and ships **the whole result set as JSON**, so there are
no CSS selectors to guess. An Angular micro-frontend (`/apps/host/shell/browser/*.js`) hands
off its SSR state through:

```html
<script id="dataTransfer" type="text/javascript">function transferredData() { return {…}; }</script>
```

Job array: **`window.ssdl.searchObj.jobs[]`**. Each row already carries `job_id`, `job_title`,
`company_name`, `job_location`, `salary`, `destination_url` — plus `num_results` (full
server-side count, 6,653 for support/London) and `search_page_number`.

- Search params: **`?q=<terms>&location=<place>&page=N`**. Page size **15** (verified;
  `search_page_number` echoes back, and 3 pages → 45 unique ids, no overlap).
- Canonical URL: `/jobs-<Country>-<City>-<Title_Slug>.id<JOBID>`; the id after `.id` is the
  stable job id and what `seen_pattern` matches.

## ⛔ The REST API is a dead end — don't re-hunt it

The page references a real API base, `https://job.efinancialcareers.com/api/v1/`, and
`/api/v1/jobs/popular?locale=en_GB` **works** (returns full JobPosting JSON, ~105 KB). It is
**not a search endpoint** — it serves an editorial "popular jobs" list only. Every plausible
search route 404s:

| Probe | Result |
|---|---|
| `/api/v1/jobs/search?q=support&locale=en_GB` | 404 |
| `/api/v1/jobs?q=support&locale=en_GB` | 404 |
| `/api/v1/search?q=support&locale=en_GB` | 404 |
| `/api/v1/jobs/search?keyword=support&location=London&locale=en_GB` | 404 |

The `dataTransfer` blob **is** the search surface. It's server-rendered JSON, so it's as
stable as an API and needs no browser — the outcome the "JSON beats HTML" rule was after.

## Salary is dirty — the feed filters it

eFC publishes placeholder salaries with **no figure in them**: `Competitive`, `£Competitive`,
even `£/annum + benefits`. `feed.py` drops any salary containing **no digit**, keeping the
field honestly empty rather than letting precheck read a placeholder as a number. Real values
survive (`£40k - £45k`, `£500 - £870 per day (via Umbrella)`, `GBP80000 - GBP130000 per annum`).
Roughly **8 of 45** rows on an "IT support"/London sweep carry a real figure.

## Apply — per-employer

`ats_hint` is left empty; it resolves on the JD page. Some rows apply on-board behind a free
eFC account; most redirect off-site to the bank's or recruiter's own ATS.

## Quirks

- `q=support` matches the word broadly across finance — expect legal/broker "support" roles
  (e.g. "Paralegal/Support Lawyer", "Placement Broker Support") mixed in with IT support.
  Query the IT lane explicitly (`--what "IT support"`, `"application support"`, `"desktop
  support"`) rather than a bare `support`; precheck screens the rest.
