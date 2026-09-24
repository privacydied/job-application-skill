# the-dots.com ("The Dots") — site notes

UK creative/design network — high on-profile density for junior-mid design/UX/UR. Job
listings are LOGIN-GATED but exposed via a clean JSON:API, so `scripts/feed.py` sources
without a browser (like Adzuna). Verified live 2026-07-15.

## Auth: OAuth2 password grant (email/password in ats-credentials.csv)
- Login is passwordless magic-link BY DEFAULT, but there's a **"Log in with password"**
  option (and social SSO). The feed uses the password grant:
  `POST https://api.the-dots.com/v1/oauth/token`
  body `{"client_id":"1","client_secret":"","grant_type":"password","username":<email>,"password":<pw>}`
  → `{access_token: <JWT>}`. Creds come from the `the-dots.com` row in `ats-credentials.csv`.
- **The API 403s non-browser requests** — browser-like headers are REQUIRED (User-Agent,
  `Origin: https://the-dots.com`, `Referer`). The feed sets them; a bare urllib call is blocked.

## Sourcing: `scripts/feed.py [--pages N] [--all] [--force]`
- `POST /v1/search/jobs/query?include=organisation-page,level,job-type,professions,location&page=N`
  body `{"data":{"filters":[],"order":"latest"}}` → JSON:API (`data[]` + sideloaded `included[]`,
  24/page, `meta.pagination.total_pages`).
- Field mapping (JSON:API resolution): company = the `organisation-page` rel → `included` type
  **`pages`**, name under **`title`** (NOT `name`). Location rel → type `locations`
  (`postalTownLong`). Canonical URL `https://the-dots.com/jobs/<slug>`; apply hops to
  `attributes.applicationWebsite`.
- **Keyword search** (verified live): the keyword is a TOP-LEVEL `data.query` with
  `order:"relevance"` — `{"data":{"query":"UX Designer","filters":[],"order":"relevance"}}`
  (NOT inside `filters` — a `filters:[{type:keyword…}]` shape 500s). Omit `--what` → latest
  feed (`order:"latest"`). `--nav <the-dots url>` extracts its `q` param as the keyword, so a
  `searches.csv` row like `thedots,ux designer,https://the-dots.com/jobs/search?q=UX+Designer`
  rotates like any other board.

## Apply
Off-site: each posting's `apply_url` (`applicationWebsite`) hops to the real ATS (Workday,
Greenhouse, company careers, …) — tailor + drive that ATS as usual; The Dots itself isn't
the apply surface.

**⚠️ SOME postings apply IN-PLATFORM instead** (`.../jobs/<slug>/apply`, no `apply_url` hop) —
verified live 2026-09-24, Fever Design/Graphic Designer. Login persists in the browser profile
(creds: `the-dots.com` row in `ats-credentials.csv`). Form fields: `input[type=email]`,
`input[type=url]` (portfolio link), `#input-resume` (file input, `id` not `name` — upload via
`cfx.post('/tabs/<tab>/upload', {selector:'#input-resume', path:'base-resume.pdf'})`), plus a
`[contenteditable=true]` cover-letter div.

**⛔ DO NOT type into the cover-letter `[contenteditable]` div — it reliably crashes the page
to an "Oops! Something went wrong..." error screen** (verified 2× — `document.execCommand
('insertText', …)` on it, even after a clean reload with no other DOM edits, triggers the
crash every time). Cover letter is optional (form submits fine without it) — skip it, fill
email + portfolio URL + CV upload only, then click the `Apply` button. A dismissed Seers CMP
cookie banner renders as an `<iframe>` — hide it with `iframe.style.display='none'`, do NOT
mass-hide "cookie"-named elements or remove the iframe node itself (this also crashed the
page once — collateral damage from a too-broad `[class*=cookie]` sweep). Success text:
"Great that you're interested in this role!" / "Connect with people at &lt;company&gt;".
