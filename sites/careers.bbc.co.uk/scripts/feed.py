#!/usr/bin/env python3
"""feed.py — enumerate vacancies from BBC careers.

The BBC is a major London public-service digital employer and hits several profile families
at once: design/UX and digital content (§14), software/DevOps and platform (§13), plus
charity-adjacent public-service culture. Its openings are mostly NOT syndicated to the
aggregators, so this is additive reach.

Platform is **SAP SuccessFactors RMK**, but the modern React variant: `careers.bbc.co.uk/
search/` renders an EMPTY shell to plain curl (0 job tiles) and hydrates results client-side.
So the HTML is a dead end — do not scrape it. The React module calls a clean JSON API:

    POST https://careers.bbc.co.uk/services/recruiting/v1/jobs
    {"locale":"en_GB","pageNumber":0,"keywords":"…","location":"…","facetFilters":{},…}

which this feed uses via `httpfeed.Board.body` (the runtime's POST hook). Verified: the API
needs **no auth, no cookie and no CSRF token** — the browser sends `x-csrf-token` but the
endpoint returns 200 without it. GET is rejected (405), so it must stay a POST.

⚠️ `pageNumber` is **0-based** (10 results/page), unlike every other board here — hence the
`page - 1` below. Response is `{"jobSearchResult":[{"response":{…}},…], "totalJobs":N}`.

⚠️ The BBC board is INTERNATIONAL — BBC World Service posts Delhi/Abuja/Nairobi roles with
NGN/ZAR salaries, and those rows carry no `jobLocationShort` at all. `location` in the POST
body is a real server-side filter (`digital` → 45 unfiltered vs 11 for London), so --where
does the work; rows with no location are passed through with "" for precheck to judge.

Salary is NOT in the search API (only a `currency` hint), so this feed emits "" rather than
guessing; the JD page carries the band.

Apply is on-site and **account-gated** — the RMK candidate flow needs a BBC careers profile.

Usage:
    python3 feed.py [--what digital] [--where London] [--pages N] [--all] [--force]
"""
import os
import re
import sys

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_here, "..", "..", "_common", "scripts"))
import httpfeed  # noqa: E402

BASE = "https://careers.bbc.co.uk"
API = f"{BASE}/services/recruiting/v1/jobs"
PER_PAGE = 10


def search_url(what, where, page):
    """The POST target is constant — the query travels in the body (see `body`)."""
    return API


def body(what, where, page):
    """The JSON body the RMK React module posts. `pageNumber` is 0-based."""
    return {
        "locale": "en_GB",
        "pageNumber": max(0, page - 1),
        "sortBy": "",
        "keywords": what or "",
        "location": where or "",
        "facetFilters": {},
        "brand": "",
        "skills": [],
        "categoryId": 0,
        "alertId": "",
        "rcmCandidateId": "",
    }


def parse(text, ctx):
    """Pure: API JSON -> raw job rows (each wrapped in a `response` envelope)."""
    import json
    try:
        data = json.loads(text)
    except ValueError:
        return []
    return [r.get("response") or {} for r in (data.get("jobSearchResult") or [])]


def _location(raw):
    """jobLocationShort is a LIST of '<City>, <ISO3>, <postcode><br/>' — often repeated once
    per posting site. De-duplicate, strip the trailing <br/>, keep order."""
    out = []
    for a in (raw.get("jobLocationShort") or []):
        s = httpfeed.clean(a).strip().rstrip(",")
        if s and s not in out:
            out.append(s)
    return " / ".join(out)


def normalize(raw, ctx):
    """Pure: one API row -> the shared posting shape. Unit-tested in tests/test_core.py."""
    jid = str(raw.get("id") or "").strip()
    title = httpfeed.clean(raw.get("unifiedStandardTitle") or raw.get("jobTitle"))
    if not jid or not title:
        return None
    # urlTitle is ALREADY percent-encoded by the API ("Digital-Video-Manager%2C-Bluey") —
    # re-encoding it would double-escape the %2C and 404.
    slug = raw.get("unifiedUrlTitle") or raw.get("urlTitle") or ""
    dept = raw.get("filter2") or []
    return {
        "id": jid,
        "url": f"{BASE}/job/{slug}/{jid}/" if slug else f"{BASE}/job/{jid}/",
        "title": title,
        "company": f"BBC — {httpfeed.clean(dept[0])}" if dept else "BBC",
        "location": _location(raw),
        "salary": "",      # Not exposed by the search API — see module docstring.
        "created": _date(raw.get("unifiedStandardStart")),
        "ats_hint": "successfactors",   # RMK candidate account required.
        "source": "bbc",
    }


def _date(s):
    """'15/07/2026' -> '2026-07-15'."""
    m = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", str(s or "").strip())
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else ""


BOARD = httpfeed.Board(
    board="bbc", name="BBC careers", base=BASE,
    search_url=search_url, parse=parse, normalize=normalize, body=body,
    seen_pattern=r"careers\.bbc\.co\.uk/job/(?:[^/,\s]*/)?(\d+)",
    fetch="http", per_page=PER_PAGE, default_where="London",
    headers={"Accept": "application/json"},
    apply_hint=("Iterate each .url; apply is SuccessFactors RMK on careers.bbc.co.uk and "
                "needs a BBC careers candidate account."),
)

if __name__ == "__main__":
    sys.exit(httpfeed.main(BOARD))
