# tfl.gov.uk (Transport for London careers) — verified site notes

One of the largest **London-only** public-sector tech employers. On-profile for gov digital
(§14) — TfL runs a big in-house digital/data estate — and for DevOps/security (§13):
infrastructure, networks, and OT/cyber (there is a standing "Head of Profession — Tel/OT
Cyber" line). Every role is London by construction, so nothing needs location filtering.
Mostly **not syndicated** to the aggregators, so this is additive reach. Feed slug `tfl`.

## ⚠️ tfl.gov.uk/corporate/careers/ is a brochure, not a board
It holds **zero vacancies**. The live vacancy search is an **SAP SuccessFactors RMK
(jobs2web)** site at **`https://london-gov.jobs2web.com/tfl/`**, which the feed sources
directly. The brochure page also still links a legacy `tfl.taleo.net` careersection; the
jobs2web host is the current one.

The RMK instance is shared by **three employers — TfL, the GLA and OPDC** (site title: "TfL,
GLA or OPDC Jobs"). The search tiles do not say which, and every JD's own `Company:` field
reads literally `TfL, GLA or OPDC` — which is what the feed emits, verbatim, rather than
guessing.

## Sourcing (VERIFIED live 2026-07-17)
- **Server-rendered HTML** — plain curl, no browser, key or login.
- `GET /tfl/search/?q=<terms>&locationsearch=&startrow=N`. ⚠️ `startrow` is a **0-based row
  offset, not a page index** (`startrow=25` = page 2); 25 rows/page. Total is in
  `Showing 1 to 24 of 24 Jobs`.
- Rows: `li.job-tile.job-id-<ID>` with `data-url="/tfl/job/<slug>/<ID>/"`. `<ID>` (10-digit,
  e.g. `1360655555`) is the stable tracker id. Each tile **repeats its fields 3×**
  (desktop/tablet/mobile blocks) — every extractor is a first-match, so this is harmless.
- **Board size is small: 24 total open vacancies** at time of verification. It is one
  employer group, not an aggregator — a handful of matches is the expected shape.
- Cooldown key = the `q` term.

### ⚠️ The search page has no salary and no location
Tiles carry **only** title / date / department. The facets are `dept` and `shifttype` — there
is deliberately no location facet because the whole board is London. So the feed emits:
- `salary: ""` — not guessed. The JD carries it (`Salary: £55,000 - £75,000`, `Grade: Band 3`).
- `location: "London"` — constant, true by construction. The JD carries the precise site and
  hybrid split (`Location: VSH / Hybrid`; "VSH" = Victoria Station House).

The URL slug does embed the site as a prefix (`/tfl/job/VSH-Digital-Strategy-Manager/…`,
`Palestra-…`, `Woolwich-Ferry-…`), but it is **truncated to ~30 chars** and not cleanly
separable from the title, so it is not parsed. jd.py resolves the real detail.

`locationsearch` is accepted by the site but is pointless here; the feed only forwards a
non-London `--where` rather than silently dropping it.

## Apply path reality — account-gated SuccessFactors
The JD's "Apply now" goes to **`/talentcommunity/apply/<ID>/?locale=en_GB`** — the
SuccessFactors RMK candidate flow, which requires an **RMK candidate profile**. Treat as a
login gate: source freely, apply with the user's authenticated session (creds in the
gitignored `ats-credentials.csv`). `ats_hint` is set to `successfactors`.

Same ATS class as `sites/careers.bbc.co.uk/` — but BBC runs the **newer React RMK** whose
results are API-only, whereas this instance is still classic server-rendered RMK. Do not
assume one recipe covers both.

## Quirks
- No JSON-LD on JD pages (`application/ld+json` count is 0) — the JD is server-rendered HTML,
  so `Key Information` must be text-extracted.
- No CAPTCHA on the sourcing path.
