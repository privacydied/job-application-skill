#!/usr/bin/env python3
"""feed.py — enumerate job postings from eFinancialCareers UK (efinancialcareers.co.uk).

The finance-sector board. Relevant because banks/insurers/asset managers run large in-house
IT estates and hire the §13/§14 lanes — application support, trade-floor/desktop support,
infrastructure, SOC — but budget them on *finance* payscales, so junior/mid IT roles here pay
materially above the general-market equivalent. Distinct inventory vs the aggregators.

**No HTML scraping and no browser.** The search page is server-rendered and ships the entire
result set as JSON in a `<script id="dataTransfer">` blob (an Angular micro-frontend hands off
its SSR state through `function transferredData() { return {...} }`). The job array lives at
`window.ssdl.searchObj.jobs[]` and each row already carries title, company, location, salary
and the canonical URL — so `parse` is a JSON pluck, not a selector guess.

Hunted for a REST API first, as the brief requires: the page references
`https://job.efinancialcareers.com/api/v1/jobs/popular` (live, returns full JobPosting JSON),
but that endpoint only serves an editorial "popular" list — every plausible search route
(`/api/v1/jobs/search`, `/api/v1/jobs`, `/api/v1/search`, with `q`/`keyword` params) returns
**404**. The embedded `dataTransfer` blob is the real search surface, so this feed uses it.

Search params (verified live 2026-07-17): `?q=<terms>&location=<place>&page=N`.
Page size is **15** and `search_page_number` echoes back in the blob, confirming pagination.
`num_results` reports the full server-side count (6,653 for support/London).

Usage:
    python3 feed.py [--what "application support"] [--where London] [--pages N] [--all] [--force]
    python3 feed.py --nav "https://www.efinancialcareers.co.uk/jobs?q=support&location=London"
"""
import json
import os
import re
import sys

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_here, "..", "..", "_common", "scripts"))
import httpfeed  # noqa: E402

BASE = "https://www.efinancialcareers.co.uk"
PER_PAGE = 15

BLOB_RE = (r'(?is)<script id="dataTransfer"[^>]*>\s*function transferredData\(\)\s*\{\s*'
           r'return\s*(\{.*?});?\s*\}\s*</script>')


def search_url(what, where, page):
    q = {"q": what or ""}
    if where:
        q["location"] = where
    if page > 1:
        q["page"] = page
    return f"{BASE}/jobs?" + httpfeed.urlencode(q)


def parse(text, ctx):
    """Pure: HTML -> the embedded search rows. Returns [] when the blob shape moves, which
    surfaces as an honest 'no jobs' rather than a wrong-shaped scrape."""
    m = re.search(BLOB_RE, text or "")
    if not m:
        return []
    try:
        blob = json.loads(m.group(1))
    except ValueError:
        return []
    jobs = httpfeed.jsonpath(blob, "window", "ssdl", "searchObj", "jobs", default=[])
    return jobs if isinstance(jobs, list) else []


def normalize(raw, ctx):
    """Pure: one search row -> the shared posting shape."""
    jid = str(raw.get("job_id") or raw.get("jobId") or "").strip()
    title = httpfeed.clean(raw.get("job_title"))
    if not jid or not title:
        return None
    # eFC publishes placeholder salaries with no figure in them — "Competitive",
    # "£Competitive", even "£/annum + benefits". Anything carrying no digit is not a real
    # number, so keep the field honestly empty rather than let precheck read it as one.
    salary = httpfeed.clean(raw.get("salary"))
    if not re.search(r"\d", salary):
        salary = ""
    return {
        "id": jid,
        "url": httpfeed.absolutise(raw.get("destination_url"), BASE),
        "title": title,
        "company": httpfeed.clean(raw.get("company_name")),
        "location": httpfeed.clean(raw.get("job_location")),
        "salary": salary,
        "ats_hint": "",          # per-employer; resolves on the JD page
        "source": "efinancial",
    }


BOARD = httpfeed.Board(
    board="efinancial", name="eFinancialCareers", base=BASE,
    search_url=search_url, parse=parse, normalize=normalize,
    seen_pattern=r"efinancialcareers\.co\.uk/jobs-[^\"'\s]*\.id(\d+)",
    fetch="http", per_page=PER_PAGE, default_where="London",
    apply_hint=("Iterate each .url; apply is per-employer (bank/recruiter ATS) — some rows "
                "apply on-board behind a free eFC account, most redirect off-site."),
)

if __name__ == "__main__":
    sys.exit(httpfeed.main(BOARD))
