#!/usr/bin/env python3
"""feed.py — enumerate job postings from The Dots via its JSON API (api.the-dots.com/v1).

The Dots is a UK creative/design network — high on-profile density for junior-mid design/
UX/UR. Job listings are LOGIN-GATED, but there's a clean JSON:API behind an OAuth2
password grant, so this feed needs no browser (like Adzuna). Endpoints verified live
2026-07-15:
  auth   POST /v1/oauth/token   {client_id:"1", client_secret:"", grant_type:"password",
                                 username, password}  → {access_token}
  search POST /v1/search/jobs/query?include=organisation-page,level,job-type,professions,
                                    location&page=N   body {"data":{"filters":[],"order":"latest"}}
The API rejects non-browser requests (403), so browser-like headers are required.

Credentials come from ats-credentials.csv (row `the-dots.com`).

Keyword search: the API takes a top-level `data.query` (with `order:"relevance"`); without
it the feed pulls the LATEST jobs (`order:"latest"`) and lets precheck screen downstream.

Returns a de-duplicated JSON list of {id, url, title, company, location, salary, remote,
apply_url, source}; pipe to precheck.py.

Usage:
    python3 feed.py [--what "<query>"] [--nav "<the-dots search url>"] [--pages N] [--all] [--force]
  --what   keyword search (e.g. "UX Designer"). Omit → latest jobs feed.
  --nav    a the-dots.com search URL; its `q`/`query` param becomes --what (so pipeline.FEEDS
           can pass a searches.csv `nav` uniformly).
  --pages  API pages (24 jobs each; default 2).
  --all    include already-tracked postings + bypass cooldown.
  --force  bypass the cooldown gate only.
"""
import csv
import json
import os
import sys
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_here, "..", "..", "_common", "scripts"))
import board_cooldown  # noqa: E402
from precheck import load_seen  # noqa: E402

BOARD = "thedots"
API = "https://api.the-dots.com/v1"
SITE = "https://the-dots.com"
ROOT = os.path.join(_here, "..", "..", "..")
TRACKER = os.path.join(ROOT, "application-tracker.csv")
CREDS = os.path.join(ROOT, "ats-credentials.csv")
INCLUDE = "organisation-page,level,job-type,professions,location"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/122 Safari/537.36",
    "Origin": SITE, "Referer": SITE + "/", "Accept": "application/json",
    "Content-Type": "application/json",
}


def load_seen_ids():
    """The Dots posting ids already in application-tracker.csv (slug ends in -<id>)."""
    return load_seen(r"the-dots\.com/jobs/[a-z0-9-]*?([0-9]+)\b", tracker=TRACKER)


def _creds():
    """(email, password) for the-dots.com from ats-credentials.csv, or (None, None)."""
    try:
        with open(CREDS, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if (row.get("site") or "").startswith("the-dots.com"):
                    return row.get("email"), row.get("password")
    except (FileNotFoundError, OSError):
        pass
    return None, None


def _req(url, method="GET", body=None, token=None, timeout=30):
    hdr = dict(HEADERS)
    if token:
        hdr["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    with urlopen(Request(url, data=data, headers=hdr, method=method), timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _token(email, password):
    d = _req(f"{API}/oauth/token", "POST", {
        "client_id": "1", "client_secret": "", "grant_type": "password",
        "scope": None, "username": email, "password": password})
    return d.get("access_token")


def _query_from_nav(nav):
    """Pull the keyword out of a the-dots.com search URL (`q`/`query`/`keyword`)."""
    if not nav:
        return ""
    from urllib.parse import urlparse, parse_qs
    qs = parse_qs(urlparse(nav).query)
    return next((qs[k][0] for k in ("q", "query", "keyword", "what") if qs.get(k)), "")


def _search_page(token, page, query=""):
    """POST the search. A keyword uses `data.query` + order 'relevance'; else the latest feed."""
    url = f"{API}/search/jobs/query?include={INCLUDE}&page={page}"
    if query:
        body = {"data": {"query": query, "filters": [], "order": "relevance"}}
    else:
        body = {"data": {"filters": [], "order": "latest"}}
    return _req(url, "POST", body, token=token)


def _parse(payload):
    """Pure: resolve JSON:API sideloaded org/location into the shared posting shape."""
    data = (payload or {}).get("data", []) or []
    idx = {(x.get("type"), x.get("id")): x for x in (payload or {}).get("included", []) or []}
    out = []
    for j in data:
        if not isinstance(j, dict):
            continue
        a = j.get("attributes", {}) or {}
        rel = j.get("relationships", {}) or {}

        def resolve(name):
            r = (rel.get(name) or {}).get("data")
            return idx.get((r.get("type"), r.get("id")), {}).get("attributes", {}) if isinstance(r, dict) else {}

        jid = str(j.get("id") or "").strip()
        if not jid:
            continue
        slug = a.get("slug") or jid
        loc = resolve("location")
        org = resolve("organisation-page")   # JSON:API type "pages"; name is under `title`
        amt = a.get("formattedAmount") or ""
        out.append({
            "id": jid,
            "url": f"{SITE}/jobs/{slug}",
            "title": (a.get("title") or "").strip(),
            "company": (org.get("title") or org.get("name") or "").strip(),
            "location": (loc.get("postalTownLong") or loc.get("name") or "").strip(),
            "salary": amt if (a.get("isAmountPublic") and amt not in ("", "0.00")) else "",
            "remote": bool(a.get("isRemote")),
            "apply_url": a.get("applicationWebsite") or a.get("applicationEmail") or "",
            "source": BOARD,
        })
    return out


def main():
    args = sys.argv[1:]

    def opt(name, default=None):
        return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else default

    try:
        pages = max(1, int(opt("--pages", "2")))
    except ValueError:
        pages = 2
    force = "--force" in args or "--all" in args
    query = opt("--what") or _query_from_nav(opt("--nav")) or ""
    cd_key = query or "latest"       # cooldown key: the keyword, or 'latest' for the feed

    if not force:
        rem = board_cooldown.remaining_hours(BOARD, cd_key)
        if rem > 0:
            print("[]")
            print(f"\nCOOLDOWN: {BOARD}/{cd_key!r} confirmed exhausted ({rem:.1f}h remaining). "
                  f"Skipped WITHOUT re-fetching. --force to override.", file=sys.stderr)
            return 1

    email, password = _creds()
    if not (email and password):
        print("ERROR: no the-dots.com row in ats-credentials.csv (site,email,password).")
        return 2
    try:
        token = _token(email, password)
    except (HTTPError, URLError, ValueError) as e:
        print(f"ERROR: The Dots auth failed: {e}")
        return 2
    if not token:
        print("ERROR: The Dots auth returned no access_token")
        return 2

    pool = {}
    for page in range(1, pages + 1):
        try:
            payload = _search_page(token, page, query)
        except (HTTPError, URLError, ValueError) as e:
            print(f"ERROR: The Dots search page {page}: {e}", file=sys.stderr)
            break
        rows = _parse(payload)
        for r in rows:
            pool.setdefault(r["id"], r)
        total_pages = (payload.get("meta", {}).get("pagination", {}) or {}).get("total_pages", page)
        if page >= total_pages or not rows:
            break
        time.sleep(1)

    all_jobs = list(pool.values())
    if "--all" in args:
        jobs = all_jobs
    else:
        seen = load_seen_ids()
        jobs = [j for j in all_jobs if j["id"] not in seen]
    filtered = len(all_jobs) - len(jobs)

    track = "--all" not in args
    if track:
        board_cooldown.record_yield(BOARD, cd_key, len(jobs))
    print(json.dumps(jobs, ensure_ascii=False, indent=2))
    if jobs:
        print(f"\n{len(jobs)} FRESH The Dots jobs ({filtered} already tracked, filtered). "
              f"Iterate each .url; apply hops off to .apply_url.", file=sys.stderr)
    else:
        marked = ""
        if track and all_jobs:
            hrs = board_cooldown.adaptive_hours(BOARD, cd_key)
            until = board_cooldown.mark(BOARD, cd_key, hrs)
            marked = f" Auto-marked {BOARD}/{cd_key} cooldown until {until} ({hrs:.0f}h)."
        print(f"\nEXHAUSTED: all {len(all_jobs)} scanned The Dots jobs already tracked.{marked}",
              file=sys.stderr)
    return 0 if jobs else 1


if __name__ == "__main__":
    try:
        import stagetimer
        _src = stagetimer.timed("source")
    except Exception:
        import contextlib
        _src = contextlib.nullcontext()
    with _src:
        sys.exit(main())
