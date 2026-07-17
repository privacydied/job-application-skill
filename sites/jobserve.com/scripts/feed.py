#!/usr/bin/env python3
"""feed.py — enumerate job postings from JobServe (jobserve.com).

One of the largest UK IT inventories (6,700+ live hits for a bare "support"/London query).
Heavily **contract/agency-skewed** — which is a legitimate pivot, not a downside: day-rate
1st/2nd-line, deskside and infrastructure contracts are exactly the §14 support/devops lanes,
and they turn over far faster than perm. Distinct recruiter inventory vs the aggregators.

⚠️ THE SEARCH IS POST-ONLY — this is the whole trick of this board.
JobServe stores each search **server-side** behind a 20-hex `shid` handle; results are then
GET-able and pageable. There is no keyword query param: the desktop form is ASP.NET WebForms
(viewstate hell) and `GET /gb/en/mob/jobsearch?JobSearch.Keywords=…` is rejected outright
(164-byte body — the MVC action is [HttpPost]). So this feed:

  1. POSTs `JobSearch.Keywords`/`JobSearch.Location` to the **mobile** MVC endpoint
     `/gb/en/mob/jobsearch` (no cookies, no viewstate, no login) → mints an `shid`;
  2. GETs the **desktop** `/gb/en/JobListing.aspx?shid=<shid>&page=N` for results.

The shid minted by the mobile endpoint works on the desktop listing (verified live) — and the
desktop listing is used deliberately because the mobile card **omits the company**, while the
desktop card carries it as an "Employment Agency"/"Employment Business" row. 20 jobs/page;
page size is a stored session preference, so `&pp=100` etc. are ignored (verified).

Parsing (verified live 2026-07-17):
  card     `<div class="jobListItem …" id="<JOBID>">` — the id IS the stable job id
  title    `a.jobListPosition` (+ href = canonical `/gb/en/search-jobs-in-<place>/<SLUG>-<ID>/`)
  location `label "Location"`  → `span#summlocation`
  salary   `label "Rate"`      → `span#summrate`
  company  `label "Employment Agency"` | `"Employment Business"`
  created  `label "Posted Date"`

robots.txt: `/gb/en/JobListing.aspx` and `/gb/en/mob/jobsearch` are both allowed. The per-job
`/gb/en/W<ID>.jsap` apply link IS disallowed, so this feed never emits it — `.url` is the
crawlable canonical listing URL instead.

Usage:
    python3 feed.py [--what "1st line support"] [--where London] [--pages N] [--all] [--force]
    python3 feed.py --nav "https://www.jobserve.com/gb/en/JobListing.aspx?shid=<SHID>"
"""
import os
import re
import sys
from urllib.request import Request, urlopen

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_here, "..", "..", "_common", "scripts"))
import httpfeed  # noqa: E402

BASE = "https://www.jobserve.com"
SEARCH_POST = f"{BASE}/gb/en/mob/jobsearch"
PER_PAGE = 20

CARD_RE = (r'(?is)<div class="jobListItem[^"]*"\s+id="([A-F0-9]{10,})"(.*?)'
           r'(?=<div class="jobListItem|<div id="jobListPagingControl_Bottom|</body>)')

# shid cache: the POST costs a request, so mint once per (what, where) per process.
_SHID = {}
_NAV_SHID = {"v": ""}


def _mint_shid(what, where):
    """POST the search → the server-side `shid` handle. One extra request per run."""
    body = httpfeed.urlencode({
        "JobSearch.Keywords": what or "",
        "JobSearch.Location": where or "",
        "JobSearch.LocationID": "0",
        "JobSearch.IncludeRemoteWorking": "false",
        "JobSearch.SearchMode": "QuickSearch",
        "ChangeMode": "false",
        "ClearMode": "false",
    }).encode()
    req = Request(SEARCH_POST, data=body, headers={
        "User-Agent": httpfeed.UA,
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-GB,en;q=0.9",
        "Referer": SEARCH_POST + "/",
    })
    try:
        with urlopen(req, timeout=30) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except OSError as e:
        raise httpfeed.FetchError(f"JobServe search POST failed: {e}") from e
    m = re.search(r'/mob/jobsearch/(?:results/)?([0-9A-F]{16,})', html)
    if not m:
        raise httpfeed.FetchError("JobServe search POST returned no shid (form contract moved?)")
    return m.group(1)


def query_from_nav(nav):
    """Cooldown key from a JobServe URL — and, as a side effect, stash the nav's `shid`.

    run() only hands `nav` to page 1 and calls search_url() for pages 2+; without capturing
    the shid here, page 2 would mint a *fresh, empty* search and silently return the wrong
    inventory. This is the one Board hook that receives `nav`.
    """
    m = re.search(r"[?&]shid=([0-9A-F]{16,})", nav or "", re.I)
    if m:
        _NAV_SHID["v"] = m.group(1)
    return httpfeed.query_param(nav, "q", "keywords", "what", "query")


def search_url(what, where, page):
    shid = _NAV_SHID["v"]
    if not shid:
        key = (what or "", where or "")
        if key not in _SHID:
            _SHID[key] = _mint_shid(what, where)
        shid = _SHID[key]
    return f"{BASE}/gb/en/JobListing.aspx?shid={shid}&page={page}"


def _labelled(body, *labels):
    """Value of the first matching `<label …>Name</label><span …>value</span>` detail row."""
    for lab in labels:
        m = re.search(r'(?is)<label class="jobListLabel[^"]*">\s*' + re.escape(lab)
                      + r'\s*</label>\s*<span[^>]*>(.*?)</span>', body)
        if m:
            return httpfeed.clean(m.group(1))
    return ""


def parse(text, ctx):
    """Pure: HTML -> raw card dicts."""
    return [{"job_id": i, "html": b} for i, b in re.findall(CARD_RE, text)]


def normalize(raw, ctx):
    """Pure: one card -> the shared posting shape."""
    body = raw.get("html") or ""
    jid = raw.get("job_id") or ""
    if not jid:
        return None
    m = re.search(r'(?is)<a\s+href="([^"]+)"[^>]*class="jobListPosition">(.*?)</a>', body)
    if not m:
        return None
    title = httpfeed.clean(m.group(2))
    if not title:
        return None
    salary = _labelled(body, "Rate")
    return {
        "id": jid,
        "url": httpfeed.absolutise(m.group(1), BASE),
        "title": title,
        "company": _labelled(body, "Employment Agency", "Employment Business"),
        "location": _labelled(body, "Location"),
        "salary": "" if salary.lower() in ("negotiable", "competitive") else salary,
        "created": _labelled(body, "Posted Date"),
        "ats_hint": "",           # per-listing; agency ATS only resolves on the JD page
        "source": "jobserve",
    }


BOARD = httpfeed.Board(
    board="jobserve", name="JobServe", base=BASE,
    search_url=search_url, parse=parse, normalize=normalize,
    seen_pattern=r"jobserve\.com/[^\"'\s]*?-([A-F0-9]{16,})/",
    fetch="http", per_page=PER_PAGE, default_where="London",
    query_from_nav=query_from_nav,
    apply_hint=("Iterate each .url; apply is the posting agency's own ATS (mostly recruiters "
                "— contract-heavy). Expect a JobServe 'Apply' interstitial before the ATS."),
)

if __name__ == "__main__":
    sys.exit(httpfeed.main(BOARD))
