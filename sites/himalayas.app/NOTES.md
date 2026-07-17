# himalayas.app ("Himalayas") — site notes

Remote-first job board with a **public, keyless JSON API** carrying ~97k live postings.
The only keyless API board in the repo besides the HTML scrapers: no key, no login, no
browser for sourcing. Feed: `scripts/feed.py` (board slug `himalayas`).

## Why on-profile
100% remote roles, and each posting states its own eligibility (`locationRestrictions` /
`timezoneRestrictions`), so "can a London-based British citizen actually take this?" is
decidable from the feed rather than guessed. Complements the London-geography boards
(Reed/Adzuna/Talent) with the fully-remote half of the profile.

## Sourcing — `GET https://himalayas.app/jobs/api?limit=20&offset=0`
Returns `{comments, updatedAt, offset, limit, totalCount, jobs:[…]}`. Each job carries
`title, companyName, companySlug, employmentType, minSalary, maxSalary, salaryPeriod,
currency, seniority[], categories[], locationRestrictions[], timezoneRestrictions[],
description(HTML), pubDate, expiryDate, applicationLink, guid`.

Three verified API facts the feed depends on:
- **`limit` is hard-capped at 20.** Asking 50/100/250 returns 20 rows and still reports
  `"limit":20`. Volume comes from `--pages` (offset paging), never a bigger limit.
- **No server-side keyword search.** `search=` / `q=` / `keywords=` / `category=` are all
  silently ignored — each returns the identical newest-first firehose. `--what` is only the
  cooldown key; it does not narrow anything. (Fine: precheck.py screens titles, feeds don't.)
- **Newest-first by `pubDate`**, so `--pages` walks backwards in time.

## Location filter (the only filtering this feed does)
Keeps a posting when it is plausibly workable from the UK:
- `locationRestrictions` names the United Kingdom, or
- `locationRestrictions` is empty (worldwide) **and** `timezoneRestrictions` is empty or
  includes UTC+0.

Everything else is a residency requirement (a British citizen would need sponsorship
abroad). `--europe` widens to EEA countries — off by default, since those still need local
right to work. Measured yield: **48/400 sampled postings (12%) are UK-eligible**; over 400
sampled rows `timezoneRestrictions` was never empty and included UTC+0 in 53.

Because ~88% of rows are dropped, a page can legitimately yield zero keepers. The board is
declared `sparse=True` so the shared runtime does not treat a barren page as the end of the
results — only a short raw page (<20) ends pagination.

## Apply-path reality
- The API exposes **no direct ATS link**: `applicationLink` == `guid` == the himalayas.app
  job page. Only 6/400 sampled `description` fields contain an ATS URL; 43/400 contain a
  `mailto:`.
- **Job pages are Cloudflare-challenged** ("Just a moment…", HTTP 403) to plain GETs *and*
  to vanilla headless Chrome — while `/jobs/api` itself is wide open (200).
- So sourcing and screening are fully HTTP-only (the whole JD ships as `description` in the
  API row — no page fetch needed), but **applying needs the stealth browser (camofox/CFX)**.
- The claim that Himalayas links straight to real ATSes is therefore **unverified** here:
  the outbound link is only observable from behind the Cloudflare challenge.

## Quirks
- `guid` is 100% consistently `https://himalayas.app/companies/<companySlug>/jobs/<slug>`
  (400/400 sampled) — the feed's id is the path after `/companies/`.
- Salary is mostly USD (141/160 priced rows); `salaryPeriod` was `annual` on 400/400.
  `currency` is null when unpriced.
- `--pages 1` yields ~2 UK-eligible postings. Use `--pages 10–25` for a real harvest
  (~40 at 15 pages).
