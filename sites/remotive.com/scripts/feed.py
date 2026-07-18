#!/usr/bin/env python3
"""feed.py — enumerate remote job postings from Remotive via its public JSON API
(feature-roadmap P.1).

Remotive is a curated remote-first board whose API is **public and keyless** — a plain
HTTPS GET returning structured JSON. No key, no login, no browser, so it runs anywhere the
other httpfeed boards do (Hermes cron, CI, Claude Code). On-profile because the applicant is
London-or-fully-remote, and the API states each posting's candidate location requirement
explicitly, so UK-eligibility is decidable from the feed alone.

API shape (verified live 2026-07-17):
    GET https://remotive.com/api/remote-jobs?search=<q>&limit=<n>
    -> {job-count, total-job-count, jobs:[…]}
    job: {id, url, title, company_name, category, tags[], job_type, publication_date,
          candidate_required_location, salary, description(HTML)}

Two verified API facts this feed is built around:
  1. There is NO offset pagination — `search=` + `limit=` returns up to `limit` newest
     matches in ONE response; there is no `page`/`offset`. Volume comes from `limit`, so
     this feed fetches page 1 only (a bigger `--limit`), and returns nothing for page>1.
  2. `search=` DOES narrow server-side (unlike Himalayas), so `--what` is a real query.

LOCATION FILTER (never title — precheck.py owns that):
  `candidate_required_location` is free text like "Worldwide", "UK", "Europe", "USA Only",
  "Americas, Europe, Israel". Kept when plausibly workable from the UK:
    - names the UK / United Kingdom / Britain / England, OR
    - is Worldwide / Anywhere (London TZ is fine).
  "Europe"/"EMEA" imply local right-to-work (the applicant is a British citizen), so they
  are OFF by default and enabled with --europe. USA/Americas/other-country-only → dropped.

Apply-path reality: `url` is the Remotive job page, which carries the employer's real apply
link (often an external ATS or a mailto:). Sourcing + screening are HTTP-only (the JD ships
as `description`); reaching the ATS to APPLY may need the account/driver for that ATS.

Usage:
    python3 feed.py [--what designer] [--limit 50] [--europe] [--all] [--force]
"""
import json
import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_here, "..", "..", "_common", "scripts"))
import httpfeed  # noqa: E402

BASE = "https://remotive.com"

UK_TOKENS = ("united kingdom", "uk", "u.k", "britain", "england", "scotland", "wales",
             "northern ireland", "great britain")
WORLDWIDE = ("worldwide", "anywhere", "global", "remote")
EUROPE_TOKENS = ("europe", "emea", "european", "eu ", " eu", "eea")


def _limit():
    if "--limit" in sys.argv:
        try:
            return max(1, min(200, int(sys.argv[sys.argv.index("--limit") + 1])))
        except (ValueError, IndexError):
            pass
    return 50


def _europe_enabled():
    return "--europe" in sys.argv


def search_url(what, where, page):
    """Page 1 only (no offset paging upstream — fact 1). `where` is folded into search."""
    if page != 1:
        return ""
    q = " ".join(t for t in [(what or "").strip(), (where or "").strip()] if t
                 and t.lower() != "london")  # 'London' as a remote-board keyword hurts recall
    return f"{BASE}/api/remote-jobs?" + httpfeed.urlencode(
        {k: v for k, v in (("search", q), ("limit", _limit())) if v})


def parse(text, ctx):
    try:
        payload = json.loads(text)
    except ValueError:
        return []
    jobs = payload.get("jobs")
    return [j for j in jobs if isinstance(j, dict)] if isinstance(jobs, list) else []


def eligibility(loc, europe=False):
    """Location label if UK-workable, else None. Mirrors himalayas' UK/worldwide logic."""
    low = (loc or "").lower()
    if not low:
        return "Remote"  # unspecified — treat as worldwide-remote; precheck's JD read decides
    if any(t in low for t in UK_TOKENS):
        return f"Remote ({loc.strip()})"
    if any(t in low for t in WORLDWIDE):
        return f"Remote ({loc.strip()})"
    if europe and any(t in low for t in EUROPE_TOKENS):
        return f"Remote ({loc.strip()})"
    return None


def normalize(raw, ctx):
    jid = str(raw.get("id") or "").strip()
    title = httpfeed.clean(raw.get("title"))
    url = (raw.get("url") or "").strip()
    if not jid or not title or not url:
        return None
    location = eligibility(raw.get("candidate_required_location"),
                           europe=ctx.get("europe", False))
    if not location:
        return None
    created = ""
    pd = raw.get("publication_date") or ""
    if pd:
        created = pd.split("T")[0]
    return {
        "id": jid,
        "url": url,
        "title": title,
        "company": httpfeed.clean(raw.get("company_name")),
        "location": location,
        "salary": httpfeed.clean(raw.get("salary")),
        "created": created,
        "ats_hint": "",
        "source": "remotive",
    }


BOARD = httpfeed.Board(
    board="remotive", name="Remotive", base=BASE,
    search_url=search_url, parse=parse, normalize=normalize,
    seen_pattern=r"remotive\.com/remote-jobs/[^/\"]+/[a-z0-9-]+-(\d+)",
    fetch="http", default_where="Remote",
    headers={"Accept": "application/json"},
    sparse=True,  # location filter removes most rows on a broad search — a thin page is normal
    apply_hint=("Iterate each .url (Remotive job page) → the employer's real apply link "
                "(often an external ATS or mailto:). JD is in the API row already."),
)

if __name__ == "__main__":
    _orig = normalize

    def _normalize_with_flag(raw, ctx):
        ctx["europe"] = _europe_enabled()
        return _orig(raw, ctx)

    BOARD.normalize = _normalize_with_flag
    sys.exit(httpfeed.main(BOARD))
