#!/usr/bin/env python3
"""feed.py — enumerate job postings from jobs.ac.uk (UK universities & research).

The academic-sector board. Relevant because every London university hires the exact
"one-person digital team" family (§14) plus IT/AV support (§13): web editor, digital
content officer, learning technologist, AV technician, service desk. Slow-moving and
under-competed compared with LinkedIn/Indeed — postings sit for weeks.

Plain server-rendered HTML — no browser, no key, no login. Cards are
`div.j-search-result__result[data-advert-id]`; the title link is `/job/<CODE>/<slug>`
(CODE is the stable id used in the tracker URL).

Apply is off-site per employer: most London unis run **Stonefish** (sites/stonefish/) or
the university's own portal; `ats_hint` is left empty because it only resolves on the JD
page (jd.py surfaces it).

Usage:
    python3 feed.py [--what "digital officer"] [--where London] [--pages N] [--all] [--force]
    python3 feed.py --nav "https://www.jobs.ac.uk/search/?keywords=ux&location=london"
"""
import os
import re
import sys

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_here, "..", "..", "_common", "scripts"))
import httpfeed  # noqa: E402

BASE = "https://www.jobs.ac.uk"
PER_PAGE = 25

CARD_RE = r'(?is)<div class="j-search-result__result[^"]*"\s+data-advert-id="(\d+)"(.*?)(?=<div class="j-search-result__result|<div id="pagination|</body>)'


def search_url(what, where, page):
    start = (page - 1) * PER_PAGE + 1
    return f"{BASE}/search/?" + httpfeed.urlencode({
        "keywords": what or "", "location": where or "", "sortOrder": 1,
        "pageSize": PER_PAGE, "startIndex": start,
    })


def parse(text, ctx):
    """Pure: HTML -> raw card dicts."""
    return [{"advert_id": aid, "html": body} for aid, body in re.findall(CARD_RE, text)]


def normalize(raw, ctx):
    """Pure: one card -> the shared posting shape. Unit-tested in tests/test_core.py."""
    body = raw.get("html") or ""
    m = re.search(r'(?is)<a\s+href="(/job/([A-Z0-9]+)/[^"]*)"[^>]*>(.*?)</a>', body)
    if not m:
        return None
    href, code, title = m.group(1), m.group(2), httpfeed.clean(m.group(3))
    if not title:
        return None
    salary = httpfeed.first(body, r'(?is)<strong>Salary:\s*</strong>(.*?)</div>')
    salary = re.sub(r'\s*\(.*?\)\s*$', '', salary).strip()
    return {
        "id": code,
        "url": httpfeed.absolutise(href, BASE),
        "title": title,
        "company": httpfeed.first(body, r'(?is)j-search-result__employer[^>]*>\s*<b>(.*?)</b>'),
        "location": httpfeed.first(body, r'(?is)<div>Location:(.*?)</div>'),
        "salary": salary,
        "created": httpfeed.first(body, r'(?is)<strong>Date Placed:\s*</strong>(.*?)</div>'),
        "ats_hint": "",
        "source": "jobsac",
    }


BOARD = httpfeed.Board(
    board="jobsac", name="jobs.ac.uk", base=BASE,
    search_url=search_url, parse=parse, normalize=normalize,
    seen_pattern=r"jobs\.ac\.uk/job/([A-Z0-9]+)",
    fetch="http", per_page=PER_PAGE, default_where="London",
    apply_hint=("Iterate each .url; apply is the university's own portal "
                "(most London unis = Stonefish → sites/stonefish/)."),
)

if __name__ == "__main__":
    sys.exit(httpfeed.main(BOARD))
