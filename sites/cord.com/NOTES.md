# cord (cord.co → cord.com) — ⛔ VERIFIED NO PUBLIC FEED (profile platform, manual channel)

`cord.co` 301s to **`cord.com`** — same product, current domain (hence this directory name).
London-centric tech hiring, direct-message model: you build a profile, companies open
conversations with you. **There is no public job-search surface to source from**, so there is
no `feed.py` here and none should be written. This is a one-off manual profile channel.

## Evidence — why there is no feed (probed 2026-07-17)

| Check | Result |
|---|---|
| `GET /`, `/jobs`, `/roles`, `/search`, `/companies`, `/jobs/london`, `/browse` | all **HTTP 200, all exactly 8,764 bytes — byte-identical** |
| That 8,764-byte body | SPA shell: *"JavaScript is not enabled — JavaScript must be enabled in order for you to use cord in standard view"* |
| `GET /u/catapult/jobs/141039-senior-engineer` (a real JD from the sitemap) | **byte-identical to the homepage shell** — zero SSR on job pages |
| `GET /search/jobs/devops-engineer` (a real sitemap URL) | **byte-identical to the homepage shell** |
| App bundle `assets.co-hire.com/react/p/static/index-*.js` (2.9 MB) | 323 distinct `/api/` routes, **all `/api/v2/account/*`, `/api/v2/application/*`, `/api/v2/admin/*`** — no public search route; no GraphQL |
| `GET /api/v2/position`, `/api/v2/position/<id>`, `/api/v2/position/external`, `/api/v2/account/candidate/search` | **401 `{"status":"error","message":"unauthorized"}`** on every one |
| `GET /api/jobs`, `/api/v1/jobs`, `/api/search/jobs` | 200/8,764 — the SPA catch-all, not an API |

Every route is the same JS shell and every API route is 401. Nothing is sourceable without
an authenticated session.

## The sitemap is not a feed — and why I didn't build one on it

`https://www.cord.com/sitemap.xml` does list **~3,169 individual job URLs** across **102
companies**, shaped `/u/<company-slug>/jobs/<id>-<title-slug>`. That is the only public
artifact. It was deliberately **not** turned into a feed:

- **No location and no salary** — the pipeline is London/fully-remote only, and precheck.py
  screens on `location`. A feed emitting 3,169 blank-location rows defeats the screen rather
  than feeding it.
- **Titles are only slugs** — `founding-ai-research-engineer` reverse-engineered to a title
  is lossy and wrong as often as it's right.
- **No freshness signal** — every `<lastmod>` is the *sitemap generation* timestamp
  (identical `2026-07-13T02:30:07Z` on every entry), not the posting date. Closed roles are
  indistinguishable from open ones.
- **It wouldn't help anyway** — see below: you can't apply from outside regardless.

Emitting that as a feed would look like coverage and deliver noise. Reporting it honestly is
worth more.

## Apply-path reality — profile platform, not an ATS

You cannot apply to a cord role from outside. The model is inverted: create a candidate
profile, set preferences, and **companies message you** (`/api/v2/application/candidate/*`
routes: `start`, `accept`, `decline`, `message` — a conversation flow, not a submission flow).

**What the user must do manually (one-off, ~30 min):**
1. Sign up at `https://cord.com/signup` (candidate/talent side).
2. Complete the profile — cord gates visibility on completeness: skills + years per skill,
   salary expectation, London / remote preference, right-to-work (British citizen), CV.
3. Set preferences to the on-profile lanes — DevOps / Linux / infrastructure / IT support /
   security — and London **or** fully-remote.
4. Keep the profile "active" — cord ranks by recency of activity, so a stale profile stops
   surfacing. Log in periodically.

**What it yields:** inbound messages from London tech companies (102 currently hiring on the
public sitemap) for direct-hire roles, no application writing. Low effort per outcome, but
**zero agent leverage** — nothing here can be automated or tracked by the loop, and the
inventory overlaps heavily with boards that *do* have feeds. Worth the one-off setup; not
worth revisiting as a sourcing target.
