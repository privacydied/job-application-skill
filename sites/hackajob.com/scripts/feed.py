#!/usr/bin/env python3
"""feed.py — enumerate job postings from hackajob (hackajob.com).

⚠️ READ THIS FIRST — hackajob is a **reverse marketplace**: employers message *you*, and the
normal route in is a profile + skills assessment, not an application. The brief expected this
board to have NO public listing surface. **It does** — `/jobs` is a public, server-rendered
(Astro) directory of ~8,540 live roles with a working `?search=` and `?page=` (712 pages ×
12), plus a `sitemap-jobs.xml` carrying 17,078 URLs (8,539 jobs × 2 locales). So this feed is
real and browser-free.

What this feed is FOR — read `NOTES.md` before leaning on it. Sourcing here is honest, but
the **apply path is not a normal apply**: every card's CTA is "Get matched" → `/talent/sign-up`.
You cannot submit an application to a hackajob listing from outside; the listing is a *demand
signal*. Use these rows to (a) see which employers are hiring the support/SOC/devops lanes,
and (b) decide whether the one-off profile setup is worth it — then apply to the same role at
source (most are also posted on the employer's own ATS). This is a **discovery feed**, which
is why every row carries `ats_hint: "hackajob-match"`.

Parsing (verified live 2026-07-17):
  card     `<article class="job-card">`
  title    `h4.jc-title > a[href="/job/<uuid>-<slug>"]` — the UUID is the stable id
  company  `h5.jc-company`
  location `span.jc-location` — contains an inline `<svg>` pin; `clean()` strips it
  (no salary and no posted-date on the card; the JD page carries JobPosting ld+json)

Search is `?search=<terms>` (the `/jobs` GET form's only input — there is **no location
filter**, so `--where` is ignored by design and precheck.py does the London/remote screening).
`/jobs/search` is a 404 — the search lives on `/jobs` itself.

Usage:
    python3 feed.py [--what "support"] [--pages N] [--all] [--force]
    python3 feed.py --nav "https://hackajob.com/jobs?search=devops"
"""
import os
import re
import sys

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_here, "..", "..", "_common", "scripts"))
import httpfeed  # noqa: E402

BASE = "https://hackajob.com"
PER_PAGE = 12

CARD_RE = r'(?is)<article class="job-card"[^>]*>(.*?)</article>'
JOB_HREF_RE = r'(?is)<h4 class="jc-title"[^>]*>\s*<a\s+href="(/job/([0-9a-f-]{36})-[^"]*)"[^>]*>(.*?)</a>'


def search_url(what, where, page):
    q = {}
    if what:
        q["search"] = what
    if page > 1:
        q["page"] = page
    return f"{BASE}/jobs" + (("?" + httpfeed.urlencode(q)) if q else "")


def parse(text, ctx):
    """Pure: HTML -> raw card chunks."""
    return [{"html": c} for c in httpfeed.cards(text, CARD_RE)]


def normalize(raw, ctx):
    """Pure: one card -> the shared posting shape."""
    body = raw.get("html") or ""
    m = re.search(JOB_HREF_RE, body)
    if not m:
        return None
    href, uuid, title = m.group(1), m.group(2), httpfeed.clean(m.group(3))
    if not title:
        return None
    return {
        "id": uuid,
        "url": httpfeed.absolutise(href, BASE),
        "title": title,
        "company": httpfeed.first(body, r'(?is)<h5 class="jc-company"[^>]*>(.*?)</h5>'),
        # clean() drops the inline <svg> map-pin that opens this span.
        "location": httpfeed.first(body, r'(?is)<span class="jc-location"[^>]*>(.*?)</span>'),
        "salary": "",            # not published on the card
        "ats_hint": "hackajob-match",   # NOT applyable from outside — see NOTES.md
        "source": "hackajob",
    }


BOARD = httpfeed.Board(
    board="hackajob", name="hackajob", base=BASE,
    search_url=search_url, parse=parse, normalize=normalize,
    seen_pattern=r"hackajob\.com/job/([0-9a-f-]{36})",
    fetch="http", per_page=PER_PAGE, default_where="",
    apply_hint=("DISCOVERY ONLY — 'hackajob-match' rows cannot be applied to from outside "
                "(CTA is /talent/sign-up). Treat as a hiring signal; apply at source. "
                "See sites/hackajob.com/NOTES.md."),
)

if __name__ == "__main__":
    sys.exit(httpfeed.main(BOARD))
