# dezeen.com/jobs → dezeenjobs.com ("Dezeen Jobs") — site notes

The biggest architecture-and-design title in the world; its board carries ~140 live roles at
name studios. **The only browser-only board in this batch.** Probed 2026-07-17.

## Why it's on-profile
Architecture/interiors-weighted, so the on-profile slice is the digital / graphic / product /
brand-design roles rather than the studio-architect bulk (§14). Worth sourcing rather than
reading — precheck's title gate is what makes it pay.

## Two facts that will otherwise cost you a session
1. **`https://www.dezeen.com/jobs/` 302s to `https://www.dezeenjobs.com/`** — a *separate
   domain*, which is where the board actually lives. `BASE` is `dezeenjobs.com`.
2. **Every dezeenjobs.com endpoint sits behind a Cloudflare managed challenge** — HTTP 403 +
   `Cf-Mitigated: challenge` + a "Just a moment…" interstitial.

### The 403 is not a header problem — don't re-litigate it
Verified 403 with a full browser header set (realistic UA, `Accept`, `Accept-Language`,
`Accept-Encoding`, `Sec-Fetch-*`, `Upgrade-Insecure-Requests`, `--compressed`) on **all** of:

| endpoint | result |
|---|---|
| `https://www.dezeenjobs.com/` | 403 challenge |
| `/feed/`, `?feed=job_feed` | 403 challenge |
| `/wp-json/wp/v2/job_listing` | 403 challenge |
| `/jm-ajax/get_listings/` | 403 challenge |
| `www.dezeen.com/wp-sitemap.xml` (per robots.txt) | 403 challenge |

`www.dezeen.com/` root and `robots.txt` return 200 — that's edge cache, not access; every
*jobs* route is challenged. The gate is JS/TLS-fingerprint based, so curl/urllib cannot pass
it at any header fidelity. **`fetch="cfx"` is a hard requirement, not a convenience.** A real
browser clears the challenge automatically in ~5s, after which every route works
(`render_wait=8` covers it).

## Sourcing: `CFX_KEY=… CFX_TAB=… python3 scripts/feed.py [--where London] [--pages N] [--all]`
Like MBW and Design Week, Dezeen Jobs runs **WP Job Manager**, so the transport is the
plugin's AJAX endpoint — *navigated to* (not XHR'd) so camofox renders it:

```
https://www.dezeenjobs.com/jm-ajax/get_listings/?search_location=&per_page=50&page=N
→ {"found_jobs":bool,"max_num_pages":int,"html":"<li class=\"post-<ID> … job_listing…"}
```

Chrome renders a bare JSON response inside `<pre>`, so `cfx_get`'s `outerHTML` yields
`<html>…<body><pre>{…}</pre></body></html>`. `parse()` unwraps `<pre>` + unescapes before
`json.loads`, and also accepts raw JSON directly (so the parser is testable offline and
survives a future fetch-mode change).

| param | verified behaviour |
|---|---|
| `per_page=50` + `page=N` | **real** pagination — `max_num_pages:3`, page 2 is a distinct set (~140 jobs) |
| `search_location` | works — `London` → 2 pages |
| `search_keywords` | **BROKEN — HTTP 500 "critical error"** on this install, for real terms *and* nonsense terms |

Because `search_keywords` 500s, the feed **never sends it**; `--what` is deliberately not
forwarded and sourcing is location-scoped only. precheck does the title filtering.

**`/page/2/` is a decoy** — the public archive returns page 1's 50 ids verbatim, so it must not
be used for paging. jm-ajax is the only real pagination.

Selectors, verified against the real rendered payload:

| field | selector |
|---|---|
| card | `li[class*="post-<ID> … job_listing"]` (ID = WP post id, also the URL suffix) |
| link | `a[href="https://www.dezeenjobs.com/job/<slug>-<ID>/"]` |
| title | `h1.entry-title > a` |
| company | the `/company/<slug>` link inside `h1.entry-title` ("*… at <a>*") |
| location | `.location-tag-list` links, comma-joined |
| salary | `.salary-range` (`Salary: €85,000 - €90,000`) |
| date | `time.entry-date` |

### Two parser traps (both cost real debugging — leave the guards in)
- **The raw jm-ajax payload breaks the line between `<li` and `class="post-…"`.** A literal
  `<li class=` matches *nothing*. A browser's DOM serializer normalises that whitespace away —
  so the *rendered* page looks single-line and hides the trap; only the raw AJAX HTML shows it.
  The card regex uses `<li\s[^>]*class="post-\d+…`.
- **`httpfeed.first()` runs `clean()`, which strips tags.** Feeding it the location block and
  then walking `<a>` tags returns zero locations. The location extraction uses a raw
  `re.search` for that reason.

## Test status — parser verified, live cfx run pending
`fetch="cfx"`, and camofox is reserved elsewhere, so **the end-to-end cfx run has not been
executed.** The parser is *not* guesswork: real payloads were captured through a browser
(headless Chrome via the host's Playwright container, which is not camofox and does not
contend with it) and `parse()`/`normalize()` validated offline against both shapes:

| payload | cards | postings | coverage |
|---|---|---|---|
| `per_page=10`, `<pre>`-wrapped (**byte-identical to `cfx_get` output**) | 10 | 10 | id/url/title/company/location/created 10/10; salary 2/10 |
| `per_page=50`, raw JSON envelope | 50 | 50 | id/url/title/company/location/created 50/50; salary 10/50 |

Sparse salary is the board's own data, not a parse miss — Dezeen often omits it.
What remains unverified is only the transport: that camofox clears the challenge and returns
the `<pre>` payload within `render_wait=8`.

## Apply
Off-site per studio on the JD; no Dezeen account needed to read a listing. `ats_hint` is left
empty — it resolves per-studio on the JD page.
