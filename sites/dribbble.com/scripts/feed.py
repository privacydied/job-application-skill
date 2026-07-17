#!/usr/bin/env python3
"""feed.py — enumerate job postings from Dribbble Jobs (dribbble.com/jobs).

The designer-network board — product/UX/UI/graphic roles, heavily **remote-first**, which is
the applicant's second acceptable geography (London OR fully-remote). ~69 live. Inventory is
mostly product/startup design teams and skews international, so precheck's London/remote gate
does the heavy lifting; what this board uniquely adds is genuine remote design work that the
UK boards don't carry.

Plain server-rendered HTML — no browser, no key, no login to SOURCE. Verified live 2026-07-17.

**Algolia is a dead end here** — the page DOES ship a public Algolia config
(`data-algolia-application-id="W5ZOF5AQ8X"`, `data-algolia-search-api-key=…`), but its indexes
are `Screenshot_query_suggestions` / `User_query_suggestions` / `ServiceOffering_query_suggestions`
— nav autocomplete for shots, designers and services. **There is no jobs index**, so querying
Algolia would return shots, not jobs. The board's own GET search is the real interface and it
is server-side; this feed uses it.

Search is the `form.js-job-search-form[action="/jobs"][method=get]`, verified live:
    ?keyword=<terms>&location=<place>&anywhere=true&page=N
  keyword really filters (`animator` -> 1, `zzzznonsense` -> 0, unfiltered -> 48);
  `location=London` -> 3; `anywhere=true` is the remote toggle. Pagination is `?page=N`,
  ~48/page, page 3 is empty (so ~69 total).

Cards are `li.job-list-item`; the id is the numeric prefix of `a.job-link[href="/jobs/<ID>-<slug>"]`.
Selectors verified live:
  link     a.job-link[href]          title    h4.job-title
  company  span.job-board-job-company
  location span.location             posted   .posted-on
Cards carry NO salary — Dribbble does not surface one on the index (left "" rather than faked).

Apply REQUIRES a Dribbble account: the card's "Apply now" is
`button[data-signup-trigger="true"][data-context="apply-job"]` — it opens a signup/login wall,
not an employer hop. Sourcing is free; applying is gated. Creds, when present, live in the
`dribbble.com` row of ats-credentials.csv.

Usage:
    python3 feed.py [--what "product designer"] [--where London] [--pages N] [--all] [--force]
"""
import os
import re
import sys

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_here, "..", "..", "_common", "scripts"))
import httpfeed  # noqa: E402

BASE = "https://dribbble.com"
PER_PAGE = 48

CARD_RE = r'(?is)<li class="job-list-item[^"]*".*?(?=<li class="job-list-item|</ul>)'


def search_url(what, where, page):
    q = {"page": page}
    if what:
        q["keyword"] = what
    if where:
        q["location"] = where
    return f"{BASE}/jobs?" + httpfeed.urlencode(q)


def parse(text, ctx):
    """Pure: HTML -> raw card chunks."""
    return [{"html": c} for c in httpfeed.cards(text, CARD_RE)]


def normalize(raw, ctx):
    """Pure: one card -> the shared posting shape."""
    body = raw.get("html") or ""
    m = re.search(r'(?is)<a class="job-link"[^>]*href="(/jobs/(\d+)-[^"?]*)', body)
    if not m:
        return None
    href, jid = m.group(1), m.group(2)
    title = httpfeed.first(body, r'(?is)<h4 class="job-title[^"]*"[^>]*>(.*?)</h4>')
    if not title:
        return None
    return {
        "id": jid,
        "url": httpfeed.absolutise(href, BASE),
        "title": title,
        "company": httpfeed.first(body, r'(?is)<span class="job-board-job-company"[^>]*>(.*?)</span>'),
        "location": httpfeed.first(body, r'(?is)<span class="location"[^>]*>(.*?)</span>'),
        "salary": "",                    # Dribbble surfaces no salary on the index
        "created": httpfeed.first(body, r'(?is)<div class="posted-on[^"]*"[^>]*>(.*?)</div>'),
        "ats_hint": "dribbble-account",  # "Apply now" is a signup wall
        "source": "dribbble",
    }


BOARD = httpfeed.Board(
    board="dribbble", name="Dribbble Jobs", base=BASE,
    search_url=search_url, parse=parse, normalize=normalize,
    seen_pattern=r"dribbble\.com/jobs/(\d+)",
    fetch="http", per_page=PER_PAGE, default_where="",
    apply_hint=("Iterate each .url; APPLY needs a Dribbble account (Apply now is a "
                "data-signup-trigger wall) — creds in ats-credentials.csv."),
)

if __name__ == "__main__":
    sys.exit(httpfeed.main(BOARD))
