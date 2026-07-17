#!/usr/bin/env python3
"""feed.py — enumerate remote job postings from Jobicy via its public JSON API
(feature-roadmap P.2).

Jobicy is a remote-jobs board with a **public, keyless** v2 JSON API. No key, no login, no
browser. Same class of win as Remotive/Himalayas: a keyless HTTP source that runs anywhere,
with each posting's geo eligibility stated explicitly so UK-workability is decidable from the
feed.

API shape (verified live 2026-07-17):
    GET https://jobicy.com/api/v2/remote-jobs?count=<n>&geo=<slug>&industry=<slug>&tag=<q>
    -> {apiVersion, jobCount, jobs:[…], success}
    job: {id, url, jobSlug, jobTitle, companyName, jobIndustry[], jobType[], jobGeo,
          jobLevel, jobExcerpt, jobDescription(HTML), pubDate, salaryMin, salaryMax,
          salaryCurrency, salaryPeriod}

Verified API facts:
  1. `count` is capped at 50 server-side; there is NO offset paging → page 1 only, volume
     from `--count`.
  2. `tag=` is a real server-side keyword filter → `--what` narrows the query.
  3. `geo=` is a server-side location facet ("anywhere", "united-kingdom", "emea", …). This
     feed leaves geo unset and filters `jobGeo` client-side (so one pass covers UK + Anywhere
     without two requests), matching how the other remote feeds work.

LOCATION FILTER (never title — precheck.py owns that):
  `jobGeo` is a label like "Anywhere", "USA", "United Kingdom", "EMEA", "Europe". Kept when
  UK-workable: UK-named, or Anywhere/Worldwide. Europe/EMEA imply local right-to-work
  (British citizen) → OFF by default, --europe to include. Everything else → dropped.

Usage:
    python3 feed.py [--what design] [--count 50] [--europe] [--all] [--force]
"""
import json
import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_here, "..", "..", "_common", "scripts"))
import httpfeed  # noqa: E402

BASE = "https://jobicy.com"

UK_TOKENS = ("united kingdom", "uk", "britain", "england", "scotland", "wales",
             "northern ireland", "great britain")
WORLDWIDE = ("anywhere", "worldwide", "global")
EUROPE_TOKENS = ("europe", "emea", "european", "eea")
CURRENCY_SYMBOL = {"USD": "$", "GBP": "£", "EUR": "€", "CAD": "CA$", "AUD": "A$"}


def _count():
    if "--count" in sys.argv:
        try:
            return max(1, min(50, int(sys.argv[sys.argv.index("--count") + 1])))
        except (ValueError, IndexError):
            pass
    return 50


def _europe_enabled():
    return "--europe" in sys.argv


def search_url(what, where, page):
    if page != 1:
        return ""
    tag = (what or "").strip()
    return f"{BASE}/api/v2/remote-jobs?" + httpfeed.urlencode(
        {k: v for k, v in (("count", _count()), ("tag", tag)) if v})


def parse(text, ctx):
    try:
        payload = json.loads(text)
    except ValueError:
        return []
    jobs = payload.get("jobs")
    return [j for j in jobs if isinstance(j, dict)] if isinstance(jobs, list) else []


def eligibility(geo, europe=False):
    low = (geo or "").lower()
    if not low:
        return "Remote"
    if any(t in low for t in UK_TOKENS):
        return f"Remote ({geo.strip()})"
    if any(t in low for t in WORLDWIDE):
        return f"Remote ({geo.strip()})"
    if europe and any(t in low for t in EUROPE_TOKENS):
        return f"Remote ({geo.strip()})"
    return None


def _salary(row):
    cur = (row.get("salaryCurrency") or "").upper()
    symbol = CURRENCY_SYMBOL.get(cur, (cur + " ") if cur else "£")
    text = httpfeed.money(row.get("salaryMin"), row.get("salaryMax"), cur=symbol)
    period = (row.get("salaryPeriod") or "").strip()
    if text and period and period.lower() not in ("annual", "yearly", "year"):
        text += f" / {period}"
    return text


def normalize(raw, ctx):
    jid = str(raw.get("id") or "").strip()
    title = httpfeed.clean(raw.get("jobTitle"))
    url = (raw.get("url") or "").strip()
    if not jid or not title or not url:
        return None
    location = eligibility(raw.get("jobGeo"), europe=ctx.get("europe", False))
    if not location:
        return None
    created = ""
    pd = raw.get("pubDate") or ""
    if pd:
        created = pd.split("T")[0]
    return {
        "id": jid,
        "url": url,
        "title": title,
        "company": httpfeed.clean(raw.get("companyName")),
        "location": location,
        "salary": _salary(raw),
        "created": created,
        "ats_hint": "",
        "source": "jobicy",
    }


BOARD = httpfeed.Board(
    board="jobicy", name="Jobicy", base=BASE,
    search_url=search_url, parse=parse, normalize=normalize,
    seen_pattern=r"jobicy\.com/jobs/(\d+)",
    fetch="http", default_where="Remote",
    headers={"Accept": "application/json"},
    sparse=True,
    apply_hint=("Iterate each .url (Jobicy job page) → the employer's real apply link. "
                "JD is in the API row already."),
)

if __name__ == "__main__":
    _orig = normalize

    def _normalize_with_flag(raw, ctx):
        ctx["europe"] = _europe_enabled()
        return _orig(raw, ctx)

    BOARD.normalize = _normalize_with_flag
    sys.exit(httpfeed.main(BOARD))
