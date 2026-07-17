# escapethecity.org (Escape the City) — verified site notes

Curated purpose-driven board: charity / social-enterprise / B-Corp roles, London-heavy, with
a strong "one-person digital team" (§14) seam — digital officer, content, comms, campaigns.
~2,476 live listings. Under-competed vs the aggregators because inventory is curated and the
board is small. Wire into `pipeline.py FEEDS` as `escapecity`.

## Sourcing (VERIFIED live 2026-07-17) — the site's own Algolia index, over plain HTTP

No browser, no login, no board account. `feed.py` queries Algolia directly:

```
GET https://6e1nsxntth-dsn.algolia.net/1/indexes/listings-live?query=<q>&hitsPerPage=20&page=<n>
    X-Algolia-Application-Id: 6E1NSXNTTH
    X-Algolia-API-Key: d4ceccfb371537bb6eab4cebd7f33f98
```

- **Credentials are public by design.** They ship in the page bundle `/js/main/app.js` as
  `{algolia:{app_id:"6E1NSXNTTH", app_key:"d4ceccfb371537bb6eab4cebd7f33f98"}}` — a
  search-only key handed to every anonymous visitor. Nothing is bypassed. If the key ever
  rotates, re-read that literal out of `app.js`.
- Algolia's **GET** form is used (not POST), so it drops straight into `httpfeed.http_get`
  with the keys as headers. Verified identical results to the POST `/query` form.
- Indexes: **`listings-live`** (relevance — used here) and `listings-live-latest` (recency).
  `listings-test*` also exist; ignore them. Page is **0-based** (`page = N-1`).
- Listing URL: `https://www.escapethecity.org/opportunity/<slug>`. `<slug>` is the tracker id.

## ⚠️ Location is free text, NOT a facet

`--where` is folded into the Algolia `query` string. The `Regions` facet looks like the right
lever and is a trap:

| probe | result |
|---|---|
| `facetFilters=[["Regions:London"]]` + `query=digital` | **0 hits** |
| `facetFilters=[["Regions:London"]]`, empty query | 25 hits |
| `query="digital London"` | **40 hits**, genuinely London |

`Regions` is a sparse legacy field — only ~214 of 2,476 live rows carry it at all (`London` 25,
`UK - Not London` 81, most rows `[None]`). The searchable `location-txt` attribute is what
actually holds location, so free text is the only lever that works. precheck.py does the real
London/remote screening.

⚠️ **Caveat — folding `where` into the query dilutes relevance on thin terms.** Algolia's
index drops query words when a full match is scarce (`removeWordsIfNoResults`), so a *narrow*
term plus a location can let the location win: `query="content London"` returns London-ish rows
("Assistant Clubhouse Manager, London") while `query="content"` alone returns genuine
"Content Strategist" / "Video Content Creator". Broad terms are unaffected
(`query="digital London"` → 40 real London digital roles). This is the board's own index
config, not a feed bug, and precheck.py screens the noise — but if a query looks diluted, drop
`--where` and let precheck do the location work.

## `--nav` handling
⚠️ `httpfeed.run()` fetches a `--nav` URL **verbatim** on page 1 — which is wrong for an
API-backed board: a site URL would feed the Vue SPA's HTML to `json.loads` and yield **0 jobs**
(observed before the fix). `feed.py` therefore rewrites `--nav <site URL>` → `--what <query>`
in `_rewrite_argv()` so `search_url()` rebuilds the Algolia URL. This matters because
`pipeline.py` passes `--nav` whenever the loop has one. An Algolia URL passed as `--nav` is
passed through untouched (verified: `…&hitsPerPage=5` → exactly 5 rows).

## Field mapping (Algolia hit → posting shape)
| posting | source |
|---|---|
| `id` | `slug` (52/1000 slugs have no numeric prefix, so the **whole slug** is the id — matches `/opportunity/<slug>`) |
| `title` / `company` | `job-title` / `org-name` |
| `location` | `location-txt` (844/1000); else `option-remote` ("Remote - 100%", "Hybrid - 60%") — the only signal the other 156 carry |
| `salary` | `salary-low`/`salary-max`, sanity-guarded (below) |
| `created` | `posted-date` (epoch **ms**) |

### ⚠️ Salary data is employer-entered and partly garbage
`show-sal` is false on 975/1000 rows, but `salary-low`/`salary-max` are populated and mostly
sane annual GBP, so the feed emits them rather than dropping 97.5% of salaries. Both ends need
guarding:
- 16/453 salaried rows have `salary-low` < 1000 (day rates / shorthand / errors) → salary dropped.
- A `salary-max` can be **below** the min — IDEO's live row is `low=90000, max=100`, which
  `money()` renders as "£90,000–£100". A max is only trusted when it is itself >= 1000 **and**
  >= low; otherwise only the low is shown.

## Apply
Off-site per employer — Escape the City links out to the org's own ATS/careers page. The
Algolia record carries **no** apply/external URL field (checked every url/link/apply-ish key),
and the JD page is a Vue SPA whose apply CTA is not in the static HTML, so `ats_hint` is left
empty and the path resolves per-listing on the JD page. **Apply is not HTTP-probed** — no
browser was used per this task's constraint; treat the apply path as unverified.

## CAPTCHA
⛔ Per `references/captcha-policy.md`: full halt for any CAPTCHA except the two sanctioned
reCAPTCHA-v2 auto-solves. None observed on the sourcing path (the Algolia API is unchallenged).

## Live test
```
$ python3 sites/escapethecity.org/scripts/feed.py --what digital --where London --all
20 FRESH Escape the City jobs (0 already tracked, filtered).
```
Emitted URLs verified 200, including slugs containing an en-dash
(`/opportunity/54068-junior-consultant-–-digital-construction-rc363-at-connected-places-catapult`).
