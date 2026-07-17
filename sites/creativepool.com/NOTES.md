# creativepool.com/jobs ("Creativepool") — site notes

UK creative-sector network and job board — the **volume** board for the applicant's design
lane (§14): ~437 live vs If You Could's ~61. Verified live 2026-07-17.

## Why it's on-profile
Widest design-specific net available without an aggregator: design / UX / digital / branding /
graphic at agencies, studios and in-house teams (Harrods, Accenture, eVenturing …). Lower
signal-to-noise than If You Could — a lot of it is recruiter-posted agency inventory, and the
same role often appears from several agencies — so precheck's title gate matters here.
Cards ship structured salary min/max, which most boards don't.

## Sourcing: `scripts/feed.py [--what "ux design"] [--pages N] [--all] [--force]`
Despite marketing copy implying a JS app, listing pages are **fully server-rendered** — plain
HTTP, no browser, no key, and **no login to source** (only to apply).

Cards are `div.jobitem12[id="j<ID>"]`. `<ID>` is the stable numeric id and also the URL's
trailing segment (`/jobs/UX-Designer-job-in-London.177582`), which is what the tracker stores.

| field | selector |
|---|---|
| link | `a.viewjob-link[href]` |
| title | `h5.viewjob-link__title` |
| company | `h6.viewjob-link__subtitle` |
| location | `li.location` |
| contract | `li.role` |
| salary | `li.salary` → **hidden** `span[itemprop=minValue\|maxValue][content]` |

**Salary quirk:** the visible text is almost always `£Undisclosed`. The real numbers sit in
hidden `<span itemprop="minValue" content="40000">` siblings, so the feed reads the itemprops
and formats via `httpfeed.money()` — that's why postings show `£40,000–£45,000` where the page
shows nothing.

### Two paging schemes — the board's main trap
- **No `--what`:** `/jobs?action=front&page=N` — 25/page, 18 pages, 437 jobs.
- **With `--what`:** the SEO discipline path `/<slug>-jobs?page=1&start=<offset>` — 30/page,
  where `start` is the offset (0/30/60…) and `page` stays pinned at 1.
  `--what "ux design"` → `/ux-design-jobs` (73 jobs).
- These do **not** interchange: `?action=front&page=2` is **ignored** on a discipline path
  (page 2 returns page 1's cards), and `?title=` / `?q=` / `?keyword=` do **not** filter on
  `/jobs`. The slug path is the only server-side keyword filter.
- ~630 discipline slugs exist (listed at `/jobs/browse-jobs-by-location-and-job-title`).
  On-profile ones: `ux-design`, `product-design`, `graphic-design`, `digital-designer`,
  `web-design`, `branding-design`, `customer-experience-designer`. **Unknown slugs 404**
  (`/ux-jobs` does not exist — it's `/ux-design-jobs`).
- **No server-side location filter** — `/jobs/london` and `/design-jobs/london` both 404.
  `--where` is accepted and ignored; precheck does location.

## Apply — requires a Creativepool account
The JD's CTA is `a.applylink.requirelogin[data-href="/jobs/<slug>.<ID>"]`, which hops to
`/login/?m=Please+login&r=…`. Listing metadata and JD body text are **public**; only the apply
action is gated. Postings are flagged `ats_hint="creativepool-account"`. Credentials, when
present, live in the `creativepool.com` row of `ats-credentials.csv` (the only sanctioned
source — never grep env).

## Quirks
- Canonical host is `creativepool.com`; `www.creativepool.com/jobs` 301s to
  `creativepool.com/jobs/`. The seen-pattern matches the id, not the host, so both are safe.
- Clicking pagination in a browser triggers a "Want to see more great jobs?" signup overlay —
  that's client-side JS only; the server still serves `?action=front&page=N` to plain HTTP.
