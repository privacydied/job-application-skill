#!/usr/bin/env python3
"""feed.py — enumerate job postings from Creativepool (creativepool.com/jobs).

UK creative-sector network and job board — the volume board for the applicant's design lane
(§14): ~437 live jobs vs If You Could's ~60, spanning design/UX/digital/branding/graphic at
agencies, studios and in-house teams. Lower signal-to-noise than If You Could (it carries a
lot of recruiter-posted agency inventory), but it is the widest design-specific net available
without an aggregator, and its cards ship structured salary min/max.

Despite the marketing copy implying a JS app, the listing pages are **fully server-rendered**
— no browser, no key, no login needed to SOURCE. Verified live 2026-07-17.

Cards are `div.jobitem12[id="j<ID>"]`; ID is the stable numeric id and it is also the URL's
trailing segment (`/jobs/UX-Designer-job-in-London.177582`), which is what the tracker stores.
Selectors verified live:
  link     a.viewjob-link[href]
  title    h5.viewjob-link__title
  company  h6.viewjob-link__subtitle
  location li.location      role li.role
  salary   li.salary — the VISIBLE text is usually "£Undisclosed", but the real numbers sit in
           hidden `<span itemprop="minValue|maxValue" content="40000">` siblings, so this feed
           reads the itemprops and formats them via httpfeed.money().

Two different paging schemes — this is the board's main quirk, both verified live:
  - No `--what`: `/jobs?action=front&page=N` — 25/page, 18 pages, 437 jobs.
  - With `--what`: the SEO discipline path `/<slug>-jobs?page=1&start=<offset>` — 30/page,
    `start` is the offset (0/30/60…) and `page` stays 1. `?action=front&page=N` is IGNORED on
    these paths (page 2 returns page 1's cards), and `?title=`/`?q=`/`?keyword=` do NOT filter
    on `/jobs` — the slug path is the ONLY server-side keyword filter. `--what "ux design"` ->
    `/ux-design-jobs` (73 jobs). Real slugs include ux-design, product-design, graphic-design,
    digital-designer, web-design, branding-design (~630 exist; unknown slugs 404).
  - `--where` is accepted and ignored: there is NO server-side location filter
    (`/jobs/london` and `/design-jobs/london` both 404). precheck does location.

Apply REQUIRES a Creativepool account — the JD's CTA is
`a.applylink.requirelogin` and hops to `/login/?m=Please+login&r=...`. Listing + JD content is
public; only the apply action is gated. Credentials, when present, live in the
`creativepool.com` row of ats-credentials.csv (the only sanctioned source).

Usage:
    python3 feed.py [--what "ux design"] [--pages N] [--all] [--force]
"""
import os
import re
import sys

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_here, "..", "..", "_common", "scripts"))
import httpfeed  # noqa: E402

BASE = "https://www.creativepool.com"
FRONT_PER_PAGE = 25     # /jobs?action=front
SLUG_PER_PAGE = 30      # /<slug>-jobs?start=

CARD_RE = r'(?is)<div class="jobitem12[^"]*"\s+id="j\d+".*?(?=<div class="jobitem12[^"]*"\s+id="j\d+"|<!--\s*/jobitem|<table class="pagination")'


def _slug(what):
    """'ux design' -> 'ux-design-jobs' (the board's SEO discipline path)."""
    s = re.sub(r"[^a-z0-9]+", "-", (what or "").lower()).strip("-")
    return s if s.endswith("-jobs") else f"{s}-jobs"


def search_url(what, where, page):
    if what:
        # Discipline path: offset paging via `start`, `page` pinned to 1.
        return f"{BASE}/{_slug(what)}?" + httpfeed.urlencode(
            {"page": 1, "start": (page - 1) * SLUG_PER_PAGE})
    return f"{BASE}/jobs?" + httpfeed.urlencode({"action": "front", "page": page})


def parse(text, ctx):
    """Pure: HTML -> raw card chunks."""
    return [{"html": c} for c in httpfeed.cards(text, CARD_RE)]


def normalize(raw, ctx):
    """Pure: one card -> the shared posting shape."""
    body = raw.get("html") or ""
    m = re.search(r'(?is)<a class="viewjob[^"]*"\s+href="([^"]+?\.(\d+))"', body)
    if not m:
        return None
    href, jid = m.group(1), m.group(2)
    title = httpfeed.first(body, r'(?is)<h5 class="viewjob-link__title"[^>]*>(.*?)</h5>')
    if not title:
        return None
    # Real numbers hide in itemprops; the visible salary is usually "£Undisclosed".
    smin = httpfeed.first(body, r'(?is)itemprop="minValue"\s+content="(\d+)"')
    smax = httpfeed.first(body, r'(?is)itemprop="maxValue"\s+content="(\d+)"')
    salary = httpfeed.money(smin, smax)
    if not salary:
        vis = httpfeed.first(body, r'(?is)<li class="salary">(.*?)</li>')
        vis = re.sub(r"(?i)undisclosed|competitive", "", vis).strip(" £-")
        salary = f"£{vis}" if vis and re.search(r"\d", vis) else ""
    return {
        "id": jid,
        "url": httpfeed.absolutise(href, BASE),
        "title": title,
        "company": httpfeed.first(body, r'(?is)<h6 class="viewjob-link__subtitle"[^>]*>(.*?)</h6>'),
        "location": httpfeed.first(body, r'(?is)<li class="location">(.*?)</li>'),
        "salary": salary,
        "contract": httpfeed.first(body, r'(?is)<li class="role">(.*?)</li>'),
        "ats_hint": "creativepool-account",   # apply CTA is .requirelogin
        "source": "creativepool",
    }


BOARD = httpfeed.Board(
    board="creativepool", name="Creativepool", base=BASE,
    search_url=search_url, parse=parse, normalize=normalize,
    seen_pattern=r"creativepool\.com/jobs/[^\s\"',]*\.(\d+)",
    fetch="http", per_page=FRONT_PER_PAGE, default_where="",
    apply_hint=("Iterate each .url; JD text is public but APPLY needs a Creativepool account "
                "(a.applylink.requirelogin) — creds in ats-credentials.csv."),
)

if __name__ == "__main__":
    sys.exit(httpfeed.main(BOARD))
