# hackajob.com — verified site notes (feed = DISCOVERY ONLY, apply is profile-gated)

A **reverse marketplace**: you build a profile, employers open conversations with you. The
brief expected no public listing surface here. **That expectation was wrong** — `/jobs` is a
public, server-rendered (Astro) directory with a working search, so `feed.py` exists and is
browser-free. But read "Apply-path reality" below before treating it as a normal board: the
listings are **not applyable from outside**. Wired in `pipeline.py FEEDS` as `hackajob`.

## Sourcing (VERIFIED live 2026-07-17) — plain HTTP, no browser, no account

- `/jobs` — public, server-rendered, **no login**. `robots.txt` explicitly `Allow: /`
  (only `/api/`, `/talent/login`, `/talent/apply`, `/employer/login` etc. are disallowed).
- Search: **`?search=<terms>`** — the `/jobs` GET form's **only** input
  (`<form method="get" action="/jobs">`, `name="search"`). Pagination `&page=N`,
  **12 cards/page**, 712 pages unfiltered (~8,540 live roles). Verified: 3 pages → 36 unique
  ids, no overlap; every row had company + location.
- **`/jobs/search` is a 404** — the search lives on `/jobs` itself. Don't chase it.
- **No location filter exists** — `feed.py` ignores `--where` (`default_where=""`) and
  precheck.py does the London/remote screening.
- `sitemap-jobs.xml` (12 MB) carries **17,078 URLs** = 8,539 jobs × 2 locales (`/job/…` and
  `/en-us/job/…`). Not used by the feed — `?search=` is better — but it confirms the
  inventory is genuinely public and enumerable.
- Cards: `<article class="job-card">`; title `h4.jc-title > a[href="/job/<uuid>-<slug>"]`
  (the **UUID is the stable id**), company `h5.jc-company`, location `span.jc-location`.
- ⚠️ `span.jc-location` **opens with an inline `<svg>` map-pin** — `httpfeed.clean()` strips
  it. A naive text grab yields a wall of SVG path data.
- **No salary and no posted-date on the card.** The JD page carries `JobPosting` ld+json
  (`hiringOrganization`, `jobLocation`, `datePosted`, `employmentType`) but `baseSalary` is
  frequently `null`. Not worth the N+1 fetch.

## ⚠️ Apply-path reality — you CANNOT apply from outside

Every card's CTA is **"Get matched" → `/talent/sign-up`**. The JD page is the same: the only
primary action is `/talent/sign-up`. There is no application form, no external ATS link, no
apply endpoint. The whole `/api/` tree is `Disallow:`-ed and account-scoped.

**The listing is a demand signal, not an application target.** This is why every row carries
`ats_hint: "hackajob-match"` and the feed's `apply_hint` says DISCOVERY ONLY. Do not queue
these rows for the apply loop — they will dead-end at a signup wall.

**Correct use:** (a) see which employers are hiring the support / SOC / devops lanes, and
(b) apply to the same role **at source** — most are also posted on the employer's own ATS.

## Manual channel — the one-off profile setup

If the user wants the inbound side (this is the platform's actual value):

1. Sign up at `https://hackajob.com/talent/sign-up`.
2. Complete the profile — skills + years, salary expectation, London / remote preference,
   right-to-work (British citizen), CV.
3. hackajob is **assessment-led**: technical challenges materially raise match rate. The
   cybersecurity Level 1 + DevOps/Linux homelab work is the story to lead with.
4. Employers then message you; you accept/decline conversations.

**Yield:** inbound approaches, no application writing. **Zero agent leverage** — nothing here
is automatable or trackable by the loop.

## Quirk — heavily international, thin on London

hackajob is **not** London-dense. An 8-page `--what support` sweep (96 rows) came back:
**76 non-UK / 17 UK-outside-London / 3 London**, with the volume in US defence and
outsourcing (Lockheed Martin, MANTECH, DXC, Atos) plus Barclays. Given London-or-remote-only,
expect a **low hit rate per page** — query narrowly and let precheck screen hard, or treat
this board as a low-priority sweep.
