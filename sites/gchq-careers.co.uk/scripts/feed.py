#!/usr/bin/env python3
"""feed.py — enumerate GCHQ vacancies (gchq-careers.co.uk).

Completes the UK intelligence-agency set alongside MI5 + MI6 (both already shipped on
applicationtrack.com). GCHQ is the SIGINT/cyber agency, so its inventory is the densest
public-sector match for the DevOps/Linux (§5) and cybersecurity (§6) families — plus
in-house design/UX. London is one of its sites (`Locations` id 1570).

⚠️ VETTING, NOT CLEARANCE: GCHQ roles require DV and sole UK nationality. He IS a British
citizen and vetting is a post-offer process, so these are ON-profile — "needs DV" is not a
disqualifier (SKILL.md's standing rule: clearance-required roles are on-profile).

SOURCING — the site is a React SPA over a private JSON API discovered in `/dist/bundle.js`:
    GET  /api/roles       -> [{id,name}]   (department facets)
    GET  /api/locations   -> [{id,name}]   (London = 1570)
    POST /api/search      {Q, Departments[], Locations[], Start, Max} -> {searchResult:[…]}

The two GETs are open, but **POST /api/search is Cloudflare-challenged** — plain curl gets
the "Just a moment..." interstitial. It answers normally from a real page context, so this
feed issues the POST *inside* camofox via an in-page `fetch()` (the tab already holds
Cloudflare clearance). That is why this feed needs CFX_KEY while most new feeds don't.

Apply is GCHQ's own portal behind a candidate account — sourcing is open, submission needs
that account. Same "agent fills, user watches via noVNC" model as MI5/MI6.

Usage:
    CFX_KEY=... python3 feed.py [--what "<terms>"] [--where London] [--max N] [--all] [--force]
    python3 feed.py --list-facets          # dump role/location ids
"""
import json
import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_here, "..", "..", "_common", "scripts"))
import board_cooldown  # noqa: E402
import httpfeed  # noqa: E402
from precheck import load_seen  # noqa: E402

BOARD = "gchq"
NAME = "GCHQ"
BASE = "https://www.gchq-careers.co.uk"
TRACKER = os.path.join(_here, "..", "..", "..", "application-tracker.csv")
SEEN_PATTERN = r"gchq-careers\.co\.uk/(?:job|vacancy)/[^,\s]*?(\d{4,})"


def facets(kind):
    """`roles` | `locations` -> [{id,name}]. These GETs are NOT Cloudflare-gated, so they
    work over plain HTTP with no browser."""
    try:
        return json.loads(httpfeed.http_get(f"{BASE}/api/{kind}",
                                            headers={"Accept": "application/json"}))
    except (httpfeed.FetchError, ValueError):
        return []


def location_ids(where):
    """Facet ids whose name matches `where` (substring, case-insensitive). Empty list =
    every location, which is what we want when the caller passes no filter."""
    if not where:
        return []
    w = where.strip().lower()
    return [f["id"] for f in facets("locations")
            if w in (f.get("name") or "").lower()]


SEARCH_JS = """
(async () => {
  const res = await fetch('/api/search', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(%s)
  });
  if (!res.ok) return {error: 'HTTP ' + res.status};
  return await res.json();
})()
"""


def search(q, loc_ids, start=0, max_n=100):
    """POST /api/search from inside the page (Cloudflare clearance lives in the tab)."""
    import cfx
    cfx.ensure_tab()
    if not (cfx.current_url() or "").startswith(BASE):
        cfx.navigate(f"{BASE}/jobs.html")
    payload = {"Q": q or "", "Departments": [], "Locations": loc_ids or [],
               "Start": start, "Max": max_n}
    out = cfx.evaluate(SEARCH_JS % json.dumps(payload), timeout=45)
    if isinstance(out, dict) and out.get("error"):
        raise RuntimeError(f"GCHQ /api/search: {out['error']}")
    return out or {}


def normalize(row):
    """Pure: one searchResult row -> the shared posting shape. The API's field casing is
    inconsistent across deploys, so each field is probed through several spellings."""
    def pick(*names):
        for n in names:
            v = row.get(n)
            if v not in (None, ""):
                return v
        return ""
    jid = str(pick("id", "Id", "jobId", "JobId", "reference", "Reference") or "").strip()
    url = str(pick("url", "Url", "link", "Link", "jobUrl") or "").strip()
    if not jid and url:
        jid = url.rstrip("/").split("/")[-1]
    if not jid:
        return None
    title = httpfeed.clean(pick("title", "Title", "name", "Name", "jobTitle"))
    if not title:
        return None
    return {
        "id": jid,
        "url": httpfeed.absolutise(url, BASE) if url else f"{BASE}/job/{jid}",
        "title": title,
        "company": "GCHQ",
        "location": httpfeed.clean(pick("location", "Location", "locations", "Locations")),
        "salary": httpfeed.clean(pick("salary", "Salary", "salaryRange")),
        "created": str(pick("datePosted", "DatePosted", "publishedDate"))[:10],
        "ats_hint": "gchq-portal",
        "source": BOARD,
    }


def main():
    args = sys.argv[1:]

    def opt(name, default=None):
        return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else default

    if "--list-facets" in args:
        for kind in ("roles", "locations"):
            print(f"== {kind} ==")
            for f in facets(kind):
                print(f"  {f.get('id'):>6}  {f.get('name')}")
        return 0

    what = opt("--what") or ""
    where = opt("--where")
    where = "London" if where is None else where
    try:
        max_n = int(opt("--max", "100"))
    except ValueError:
        max_n = 100
    include_tracked = "--all" in args
    force = "--force" in args or include_tracked

    query = what or where or "all"
    if not force:
        rem = board_cooldown.remaining_hours(BOARD, query)
        if rem > 0:
            print("[]")
            print(f"\nCOOLDOWN: {BOARD}/{query!r} confirmed exhausted ({rem:.1f}h remaining). "
                  f"--force to override.", file=sys.stderr)
            return 1

    if not os.environ.get("CFX_KEY"):
        print("ERROR: GCHQ's /api/search is Cloudflare-gated — this feed needs camofox "
              "(set CFX_KEY). The /api/roles + /api/locations facets work over plain HTTP "
              "(--list-facets).", file=sys.stderr)
        return 2

    try:
        payload = search(what, location_ids(where), max_n=max_n)
    except Exception as e:
        print(f"ERROR: {NAME} search failed: {e}", file=sys.stderr)
        return 2

    rows = payload.get("searchResult") or payload.get("SearchResult") or []
    if isinstance(rows, dict):
        rows = rows.get("results") or rows.get("items") or []

    pool = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        n = normalize(r)
        if n:
            pool.setdefault(n["id"], n)

    all_jobs = list(pool.values())
    if include_tracked:
        jobs = all_jobs
    else:
        seen = load_seen(SEEN_PATTERN, tracker=TRACKER)
        jobs = [j for j in all_jobs if j["id"] not in seen]
    filtered = len(all_jobs) - len(jobs)

    track = not include_tracked
    if track:
        board_cooldown.record_yield(BOARD, query, len(jobs))

    print(json.dumps(jobs, ensure_ascii=False, indent=2))
    if jobs:
        print(f"\n{len(jobs)} FRESH {NAME} vacancies ({filtered} already tracked, filtered). "
              f"DV-vetting roles ARE on-profile (vetting is post-offer). Apply needs a GCHQ "
              f"candidate account — agent fills, user watches via noVNC (as MI5/MI6).",
              file=sys.stderr)
    else:
        marked = ""
        if track and all_jobs:
            hrs = board_cooldown.adaptive_hours(BOARD, query)
            until = board_cooldown.mark(BOARD, query, hrs)
            marked = f" Auto-marked {BOARD}/{query!r} cooldown until {until} ({hrs:.0f}h)."
        print(f"\nEXHAUSTED: all {len(all_jobs)} {NAME} results for {query!r} already "
              f"tracked.{marked}", file=sys.stderr)
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
