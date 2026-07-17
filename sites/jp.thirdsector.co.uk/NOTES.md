# jp.thirdsector.co.uk (Third Sector Jobs) — verified site notes

Third Sector's charity-sector board — a sibling of CharityJob (`sites/charityjob.co.uk/`) with
distinct employer inventory, skewed to charity comms/digital/fundraising (§14). **Small**:
~97 live postings across 5 pages, so it sweeps whole in one pass and exhausts fast. Wire into
`pipeline.py FEEDS` as `thirdsector`.

## Domain (VERIFIED 2026-07-17)
- `thirdsectorjobs.co.uk` — **dead** (connection timeout, no response).
- `jobs.thirdsector.co.uk` — 301 → **`jp.thirdsector.co.uk`**, the canonical live host.

## ⚠️ NOT a Madgex board
Despite the Guardian-style "Third Sector Jobs" branding, this is **not** Madgex — no
`Keywords=` param, no `.lister__item`. It is a **nopCommerce storefront repurposed as a job
board** (`product-item`, `product-title`, `price actual-price`, `wishlist-btn`,
`add-to-cart-button`). Do not reuse the `sites/jobs.theguardian.com/` selectors.

## Sourcing (VERIFIED live 2026-07-17)
Plain server-rendered HTML — no browser, no key, no login to search or view.
- Search: `/jobs?q=<terms>&pagenumber=<N>`. 20 cards/page; `pagenumber` past the end returns 0
  cards, so pagination self-terminates.
- Cards: `div.product-item.job-box[data-productid]` → `data-productid` is the stable id.
- Title: `h2.product-title > a[href="/jobdetail/<id>/<slug>"]`.
- `ul.job-info-list > li > p` ×3, **positionally `[location, salary, hours]`** — verified
  consistent on 20/20 cards of a full page.
- `.description` teaser, `.days-count` ("9 days ago" / "5 days left").

### ⚠️ Entities are HEX, and `httpfeed.clean()` does not decode them
Salaries arrive as `&#xA3;45,000`. `clean()` handles named entities and **decimal** (`&#163;`)
but not **hex**, so it leaks a literal `"&#xA3;45,000"` into the salary field. `feed.py` wraps
`clean()` in a local `_txt()` that adds `html.unescape`. Worth lifting into `httpfeed.clean()`
if another board hits the same thing.

## ⚠️ `--where` is accepted but NOT sent — there is no working location filter
| probe | result |
|---|---|
| `?q=digital` | 2 |
| `?q=digital&location=london` | 2 — the param is **ignored** |
| `?q=digital london` | **0** — `q` doesn't match location text |
| `/jobs/london-(greater)?q=digital` | 1 — path browse works, but see below |

The only location lever is a **path browse**, and the taxonomy is employer free-text turned
into slugs — hopelessly fragmented. London alone splits across ~30 slugs: `london-(greater)`
(12), `london-(central)` (8), `london` (5), `central-london` (5), `london-greater` (3),
`greater-london` (2), `city-of-london` (2), `wandsworth-london` (2), plus bare postcodes
(`e20-1hz`), and even street addresses
(`10-11-carlton-house-terrace-st-james-park-london-sw1y-5ah`). Any single slug silently drops
most London roles. So the feed sweeps the whole (tiny) inventory, emits the card's raw location
text, and lets **precheck.py** screen London/remote — which it does far more reliably.

## ⚠️ `company` is always empty
Search cards carry **no** employer name — verified: no `EmployerName` in the listing markup,
and the card `<img alt>` is just the job title repeated. The JD page has it (both JSON-LD and
`.EmployerName`); jd.py surfaces it per-listing. Do not try to derive it from the card.

## Apply
Off-site per employer — JD pages show **"Apply on website"**. Some rows carry the board's own
**"Easy apply"** badge (`apply-via-email` class) — an email-based apply. Board account
(`/login`) is only needed to *save* jobs, not to search or view. **Apply is not HTTP-probed**;
treat the path as unverified.

## CAPTCHA
⛔ Per `references/captcha-policy.md`: full halt for any CAPTCHA except the two sanctioned
reCAPTCHA-v2 auto-solves. reCAPTCHA (`recaptcha/api.js`) is present site-wide but **not**
encountered on the sourcing path.

## Live tests
```
$ python3 sites/jp.thirdsector.co.uk/scripts/feed.py --what digital --where London --all
2 FRESH Third Sector Jobs jobs (0 already tracked, filtered).

$ python3 sites/jp.thirdsector.co.uk/scripts/feed.py --where London --pages 5 --all
97 FRESH Third Sector Jobs jobs (0 already tracked, filtered).   # 97 unique ids = whole board
```
Emitted URLs verified 200.
