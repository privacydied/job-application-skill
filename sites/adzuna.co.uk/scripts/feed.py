#!/usr/bin/env python3
"""feed.py — enumerate job postings from Adzuna via its public JSON API.

Adzuna is a UK aggregator with a FREE JSON API (developer.adzuna.com) — so this feed
needs NO browser, no scraping, and no anti-bot handling: it's a plain HTTPS GET returning
structured JSON. That makes it the most reliable non-LinkedIn sourcing channel and a good
complement to Indeed (distinct employer coverage).

Setup (one-time, free): register at https://developer.adzuna.com → get an `app_id` +
`app_key`, then export them:
    export ADZUNA_APP_ID=...   ADZUNA_APP_KEY=...
(Store alongside the other run env; they are API keys, not the login in ats-credentials.csv,
which is for Adzuna's *apply* flow.)

Returns a de-duplicated JSON list of {id, url, title, company, location, salary, created,
source} — same shape as the other feeds; pipe it to precheck.py.

Usage:
    python3 feed.py [--what "<query>"] [--where "<city>"] [--nav "<adzuna search url>"]
                    [--max-days-old N] [--pages N] [--all] [--force]
  --what   the search term (LinkedIn-style OR-bundles work: `"UX Designer" OR "Product
           Designer"`). If omitted, taken from --nav's `q`/`what`/`keywords` param.
  --where  location (default London). Jane works London or fully-remote only.
  --nav    an adzuna.co.uk search URL; `q`/`what` → the query, `w`/`where` → location.
           Present so pipeline.FEEDS can pass a searches.csv `nav` uniformly.
  --max-days-old  only postings newer than N days (default 7).
  --pages  API pages to pull (50 results each; default 1).
  --all    include already-tracked postings + bypass the cooldown gate.
  --force  bypass the cooldown gate only.

Cooldown: keyed on the `what` query (board `adzuna`), same adaptive scheme as the other
feeds — a dry pass auto-marks a cooldown so a later run skips it without re-fetching.
"""
import json
import os
import sys
import time
from urllib.parse import urlencode, urlparse, parse_qs
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_here, "..", "..", "_common", "scripts"))
import board_cooldown  # noqa: E402
from precheck import load_seen  # noqa: E402

BOARD = "adzuna"
DEFAULT_LOCATION = "London"
API = "https://api.adzuna.com/v1/api/jobs/gb/search"
TRACKER = os.path.join(_here, "..", "..", "..", "application-tracker.csv")


def load_seen_ids():
    """Adzuna posting ids already in application-tracker.csv (via the shared, csv-quoting-proof
    scan). Matches both the /details/<id> URL and a bare id column."""
    return load_seen(r"adzuna\.co\.uk/details/([0-9]+)", tracker=TRACKER)


def _creds():
    """API (app_id, app_key): env first, then the shared ats-credentials.csv row
    `adzuna-api` (email col = app_id, password col = app_key) so any agent picks it up
    without env setup."""
    aid, akey = os.environ.get("ADZUNA_APP_ID"), os.environ.get("ADZUNA_APP_KEY")
    if aid and akey:
        return aid, akey
    try:
        import csv
        creds = os.path.join(_here, "..", "..", "..", "ats-credentials.csv")
        with open(creds, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if (row.get("site") or "").startswith("adzuna-api"):
                    return row.get("email"), row.get("password")
    except (FileNotFoundError, OSError):
        pass
    return aid, akey


def _query_from_nav(nav):
    """Pull (what, where) out of an adzuna search URL. Accepts q/what/keywords and w/where."""
    if not nav:
        return "", ""
    qs = parse_qs(urlparse(nav).query)
    what = next((qs[k][0] for k in ("what", "q", "keywords", "query", "search") if qs.get(k)), "")
    where = next((qs[k][0] for k in ("where", "w", "location") if qs.get(k)), "")
    return what, where


def _api_url(what, where, page, max_days_old, app_id, app_key, per_page=50):
    params = {
        "app_id": app_id, "app_key": app_key,
        "results_per_page": per_page, "what": what, "where": where or DEFAULT_LOCATION,
        "max_days_old": max_days_old, "sort_by": "date", "content-type": "application/json",
    }
    return f"{API}/{page}?" + urlencode(params)


def _parse(payload):
    """Pure: map an Adzuna API response dict to the shared posting shape. Tolerates missing
    fields (company/location are nested objects; salary may be absent)."""
    out = []
    for r in (payload or {}).get("results", []) or []:
        if not isinstance(r, dict):
            continue
        jid = str(r.get("id") or "").strip()
        if not jid:
            continue
        comp = r.get("company") or {}
        loc = r.get("location") or {}
        smin, smax = r.get("salary_min"), r.get("salary_max")
        if smin and smax and smin != smax:
            salary = f"£{int(smin):,}–£{int(smax):,}"
        elif smin:
            salary = f"£{int(smin):,}"
        else:
            salary = ""
        out.append({
            "id": jid,
            "url": f"https://www.adzuna.co.uk/details/{jid}",
            "title": (r.get("title") or "").replace("\n", " ").strip(),
            "company": (comp.get("display_name") or "").strip() if isinstance(comp, dict) else "",
            "location": (loc.get("display_name") or "").strip() if isinstance(loc, dict) else "",
            "salary": salary,
            "created": (r.get("created") or "")[:10],
            "redirect_url": r.get("redirect_url") or "",
            "source": BOARD,
        })
    return out


def _fetch(url, timeout=30):
    req = Request(url, headers={"User-Agent": "job-apply/1.0", "Accept": "application/json"})
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    args = sys.argv[1:]

    def opt(name, default=None):
        return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else default

    nav = opt("--nav")
    what = opt("--what") or _query_from_nav(nav)[0]
    where = opt("--where") or _query_from_nav(nav)[1] or DEFAULT_LOCATION
    try:
        max_days_old = int(opt("--max-days-old", "7"))
    except ValueError:
        max_days_old = 7
    try:
        pages = max(1, int(opt("--pages", "1")))
    except ValueError:
        pages = 1
    force = "--force" in args or "--all" in args

    if not what:
        print("ERROR: no query — pass --what \"<terms>\" or --nav with a q= param")
        return 2

    # COOLDOWN GATE — bail before any network cost if this board+query was confirmed dry.
    if not force:
        rem = board_cooldown.remaining_hours(BOARD, what)
        if rem > 0:
            print("[]")
            print(f"\nCOOLDOWN: {BOARD}/{what!r} confirmed exhausted ({rem:.1f}h remaining). "
                  f"Skipped WITHOUT re-fetching. --force to override.", file=sys.stderr)
            return 1

    app_id, app_key = _creds()
    if not (app_id and app_key):
        print("ERROR: set ADZUNA_APP_ID and ADZUNA_APP_KEY (free at "
              "https://developer.adzuna.com) — see feed.py docstring.")
        return 2

    pool = {}
    for page in range(1, pages + 1):
        url = _api_url(what, where, page, max_days_old, app_id, app_key)
        try:
            payload = _fetch(url)
        except HTTPError as e:
            print(f"ERROR: Adzuna API HTTP {e.code} on page {page}", file=sys.stderr)
            break
        except (URLError, ValueError) as e:
            print(f"ERROR: Adzuna API {e} on page {page}", file=sys.stderr)
            break
        rows = _parse(payload)
        for r in rows:
            pool.setdefault(r["id"], r)
        if len(rows) < 50:      # last page
            break
        time.sleep(1)           # be polite to the API

    all_jobs = list(pool.values())
    if "--all" in args:
        jobs = all_jobs
    else:
        seen = load_seen_ids()
        jobs = [j for j in all_jobs if j["id"] not in seen]
    filtered = len(all_jobs) - len(jobs)

    track = "--all" not in args
    if track:
        board_cooldown.record_yield(BOARD, what, len(jobs))
    print(json.dumps(jobs, ensure_ascii=False, indent=2))
    if jobs:
        print(f"\n{len(jobs)} FRESH Adzuna jobs ({filtered} already tracked, filtered). "
              f"Iterate each .url (/details/<id>) — apply hops off to the real ATS.",
              file=sys.stderr)
    else:
        marked = ""
        if track and all_jobs:
            hrs = board_cooldown.adaptive_hours(BOARD, what)
            until = board_cooldown.mark(BOARD, what, hrs)
            marked = f" Auto-marked {BOARD}/{what!r} cooldown until {until} ({hrs:.0f}h)."
        print(f"\nEXHAUSTED: all {len(all_jobs)} Adzuna results for {what!r} already "
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
