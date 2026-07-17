#!/usr/bin/env python3
"""feed.py — enumerate vacancies from GOV.UK Find an Apprenticeship (DfE).

The statutory apprenticeship board: every English apprenticeship vacancy must be advertised
here, so it is the complete national set, not a sample. On-profile for the DevOps/security
and IT-support families (§13) via **Level 4 Cyber Security Technologist / Network Engineer /
Software Development Technician** and the Level 6 Digital & Technology Solutions degree
apprenticeship — the funded route into gov/defence tech that does not require a prior degree.

Plain server-rendered GOV.UK Design System HTML — no browser, no key, no login. Cards are
`li.das-search-results__list-item`; the title link is `/apprenticeship/<VACREF>` where
VACREF (e.g. `VAC2000040502`) is the stable id used in the tracker URL.

Search: `/apprenticeships?searchTerm=…&location=…&distance=…&pageNumber=N` (pageNumber is
1-based; 10 results/page). `location` is geocoded server-side and is a real filter — a bogus
place returns 0, `London&distance=10` returns 119 vs `distance=30` 921 (verified).

⚠️ TWO traps that make this board look bigger/smaller than it is:
  - `distance` defaults to **"all" (across England)**, which silently ignores `location`.
    A location-only URL is a NATIONAL search, so this feed always sends a mileage.
  - `searchTerm` matches the apprenticeship *standard*/title, not free text, so it is far
    stricter than an aggregator's keyword search.
Verified 2026-07-17: 4,659 vacancies nationally; `London&distance=30` alone = 921; but
`searchTerm=cyber` = 2 in ALL of England. A barren result for a sensible query is the board
being honest, not the feed being broken — widen by dropping `--what` and let precheck.py do
the title filtering. Volume is also seasonal: postings cluster Jan–May for September starts.

Apply is on-site and **account-gated**: "Apply now" on a vacancy leads to the DfE
apprenticeship application, which needs a GOV.UK Find an Apprenticeship candidate account
(sign in / create account). Some employers instead link out to their own site; the JD page
decides, so `ats_hint` is left empty.

Usage:
    python3 feed.py [--what cyber] [--where London] [--pages N] [--all] [--force]
    python3 feed.py --nav "https://www.findapprenticeship.service.gov.uk/apprenticeships?searchTerm=cyber&location=London"
"""
import html
import os
import re
import sys

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_here, "..", "..", "_common", "scripts"))
import httpfeed  # noqa: E402

BASE = "https://www.findapprenticeship.service.gov.uk"
PER_PAGE = 10
# `distance` only accepts the <select>'s own values: 2/5/10/15/20/30/40 miles, or "all"
# (= "across England"), which is the site DEFAULT and makes `location` a no-op. So omitting
# distance does NOT mean "near London", it means nationwide — the feed must send a number for
# --where to bite. 30mi ≈ commutable London. (50/100 are not options and render an error.)
DEFAULT_DISTANCE = 30

CARD_RE = (r'(?is)<li class="das-search-results__list-item.*?'
           r'(?=<li class="das-search-results__list-item|</ol>)')


def search_url(what, where, page):
    q = {"searchTerm": what or "", "location": where or "", "sort": "AgeAsc"}
    if where:
        q["distance"] = DEFAULT_DISTANCE
    if page > 1:
        q["pageNumber"] = page
    return f"{BASE}/apprenticeships?" + httpfeed.urlencode(q)


def parse(text, ctx):
    """Pure: HTML -> raw card chunks."""
    return [{"html": c} for c in re.findall(CARD_RE, text)]


def _txt(s):
    """httpfeed.clean() + HEX entity decode.

    ⚠️ GOV.UK escapes £ as `&#xA3;` and ' as `&#x27;`, but httpfeed.clean() only decodes
    NAMED (&pound;) and DECIMAL (&#163;) entities — hex ones survive it verbatim and would
    ship "&#xA3;19,747" as the salary. Decoding locally rather than patching the shared
    clean() keeps this feed off a file other feeds are concurrently changing.
    """
    return html.unescape(httpfeed.clean(s))


def normalize(raw, ctx):
    """Pure: one card -> the shared posting shape. Unit-tested in tests/test_core.py."""
    body = raw.get("html") or ""
    m = re.search(r'(?is)<a[^>]+class="das-search-results__link[^"]*"[^>]+'
                  r'href="(/apprenticeship/(VAC\d+))"[^>]*>(.*?)</a>', body)
    if not m:
        return None
    href, ref, title = m.group(1), m.group(2), _txt(m.group(3))
    if not title:
        return None
    # The two bare <p class="govuk-body">s straight after the header are employer then
    # location; every later <p> is a labelled <b>field</b>, so anchor on the labels.
    employer = _txt(httpfeed.first(body, r'(?is)<p class="govuk-body govuk-!-margin-bottom-0">(.*?)</p>'))
    location = _txt(httpfeed.first(body, r'(?is)<p class="govuk-body das-!-color-dark-grey">(.*?)</p>'))
    wage = _txt(httpfeed.first(body, r'(?is)<b>Wage</b>(.*?)</p>'))
    return {
        "id": ref,
        "url": httpfeed.absolutise(href, BASE),
        "title": title,
        "company": employer,
        "location": location,
        # "Competitive" / "£17,000 a year" — kept verbatim; apprentice pay is often banded.
        "salary": "" if wage.lower() in ("competitive", "unknown") else wage,
        "created": httpfeed.first(body, r'(?is)Posted\s+(\d{1,2}\s+\w+\s+\d{4})'),
        "ats_hint": "",   # DfE-native vs employer link-out only resolves on the JD page.
        "source": "apprentice",
    }


BOARD = httpfeed.Board(
    board="apprentice", name="Find an Apprenticeship", base=BASE,
    search_url=search_url, parse=parse, normalize=normalize,
    seen_pattern=r"findapprenticeship\.service\.gov\.uk/apprenticeship/(VAC\d+)",
    fetch="http", per_page=PER_PAGE, default_where="London",
    apply_hint=("Iterate each .url; apply is the DfE apprenticeship form and needs a Find an "
                "Apprenticeship candidate account (some employers link out instead)."),
)

if __name__ == "__main__":
    sys.exit(httpfeed.main(BOARD))
