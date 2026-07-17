#!/usr/bin/env python3
"""feed_api.py — enumerate reed.co.uk postings via Reed's OFFICIAL JSON API.

A SEPARATE, CLEANER feed from the browser scraper in this same directory. `feed.py` drives
camofox against the reed.co.uk search HTML (bot-walled, slow, needs CFX_KEY); this one is a
plain authenticated HTTPS GET returning structured JSON — no browser, no login, runs
anywhere. Both exist on purpose: the API needs a key, the scraper does not.

⚠️ Do NOT touch `feed.py` when maintaining this. They share a directory, an id scheme and a
tracker — nothing else.

DEDUP CONTRACT (the part that matters): this feed emits the SAME bare numeric id and the
SAME `source: "reed"` as the scraper, and reuses the scraper's tolerant seen_pattern
`reed\\.co\\.uk/jobs/(?:[^/,\\s]+/)?([0-9]+)` — which matches both the bare tracker shape
(`…/jobs/<id>`) and the live slugged shape (`…/jobs/<slug>/<id>`). If these two feeds ever
disagree on the id, every posting sourced by one gets re-applied by the other.
Only the cooldown slug differs (`reedapi` vs `reed`) so the two sourcing paths can be
exhausted independently.

AUTH — quoting Reed's own docs (https://www.reed.co.uk/developers/jobseeker, verified
2026-07-17): "You will need to include your api key for all requests in a basic
authentication http header as the username, leaving the password empty."
So: `Authorization: Basic base64("<API_KEY>:")` — key as username, EMPTY password.

KEY — lives in `ats-credentials.csv`, NEVER in an env var (repo rule; grepping env for a
board key is a documented false-negative). Add this row:

    reed-api,<YOUR_API_KEY>,,2026-07-17

(`site` = `reed-api`, `email` column = the API key, `password` column = empty — mirrors the
`adzuna-api` row convention.) NOTE the existing `reed.co.uk` row is the *website login* used
by the browser feed's apply flow — it is NOT an API key and this feed ignores it.
Get a free key: https://www.reed.co.uk/developers/jobseeker → "Sign up for a reed.co.uk API
Key" (an in-page form; there is no standalone /developers/signup URL — that path 404s).

API (params confirmed against the docs page, 2026-07-17):
    GET https://www.reed.co.uk/api/1.0/search
        ?keywords=<terms>&locationName=<city>&distanceFromLocation=<miles>
        &resultsToTake=<n ≤100>&resultsToSkip=<n>            ← paging
    -> {"results":[…], "ambiguousLocations":[…], "totalResults":N}

⚠️ UNVERIFIED-LIVE: the per-row JSON *field names* below (jobId/jobTitle/employerName/…)
come from Reed's published docs, which list them in prose ("Job Id", "Employer Name") rather
than as a JSON sample. They could not be confirmed against a real response because no
`reed-api` key exists in ats-credentials.csv yet — every keyless call returns HTTP 401 with
an empty body. `normalize()` is therefore written defensively (camelCase first, PascalCase
fallback). The moment a key lands, run the live test in NOTES-api.md and tighten this.

Location sanity: `locationName` + `distanceFromLocation` filter server-side, so the feed
only emits roles within `--radius` miles of London by default. No title filtering — that is
precheck.py's job.

Usage:
    python3 feed_api.py [--what "ux designer"] [--where London] [--radius 10]
                        [--pages N] [--all] [--force]
"""
import base64
import json
import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_here, "..", "..", "_common", "scripts"))
import httpfeed  # noqa: E402

BASE = "https://www.reed.co.uk"
API = f"{BASE}/api/1.0/search"
PER_PAGE = 100          # documented maximum for resultsToTake

SIGNUP = "https://www.reed.co.uk/developers/jobseeker"
CSV_ROW = "reed-api,<YOUR_API_KEY>,,<today>"

MISSING_KEY = (
    "no Reed API key. Add this row to ats-credentials.csv:\n"
    f"    {CSV_ROW}\n"
    "  (site=`reed-api`, email column = the API key, password column = empty —\n"
    "   same convention as the `adzuna-api` row.)\n"
    f"  Get a free key: {SIGNUP} → \"Sign up for a reed.co.uk API Key\".\n"
    "  The existing `reed.co.uk` row is the WEBSITE LOGIN for the browser feed's apply\n"
    "  flow, not an API key — this feed cannot use it."
)


def _api_key():
    """The key from ats-credentials.csv row `reed-api` (email column). Never env."""
    key, _unused_password = httpfeed.creds_row("reed-api")
    return (key or "").strip()


def _needs():
    return None if _api_key() else MISSING_KEY


def _auth_header():
    """Basic auth, key as username + EMPTY password (per Reed's docs)."""
    key = _api_key()
    if not key:
        return {}
    token = base64.b64encode(f"{key}:".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}", "Accept": "application/json"}


def _radius():
    args = sys.argv
    if "--radius" in args:
        i = args.index("--radius")
        if i + 1 < len(args):
            try:
                return max(0, int(args[i + 1]))
            except ValueError:
                pass
    return 10


def search_url(what, where, page):
    return f"{API}?" + httpfeed.urlencode({
        "keywords": what or "",
        "locationName": where or "London",
        "distanceFromLocation": _radius(),
        "resultsToTake": PER_PAGE,
        "resultsToSkip": (page - 1) * PER_PAGE,
    })


def parse(text, ctx):
    """Pure: API JSON -> raw result rows."""
    try:
        payload = json.loads(text)
    except ValueError:
        return []
    results = payload.get("results") if isinstance(payload, dict) else None
    return [r for r in results if isinstance(r, dict)] if isinstance(results, list) else []


def _pick(row, *names):
    """First present key among `names` — tolerates camelCase vs PascalCase, since the live
    response casing is unconfirmed (see UNVERIFIED-LIVE in the docstring)."""
    for n in names:
        if row.get(n) not in (None, ""):
            return row[n]
        alt = n[0].upper() + n[1:]
        if row.get(alt) not in (None, ""):
            return row[alt]
    return ""


def _date(value):
    """Reed dates are dd/mm/yyyy -> yyyy-mm-dd. Passes through anything else untouched."""
    s = str(value or "").strip()
    parts = s.split("/")
    if len(parts) == 3 and len(parts[2]) == 4:
        d, m, y = parts
        return f"{y}-{m.zfill(2)}-{d.zfill(2)}"
    return s[:10]


def normalize(raw, ctx):
    """Pure: one API row -> the shared posting shape."""
    jid = str(_pick(raw, "jobId", "id") or "").strip()
    title = httpfeed.clean(_pick(raw, "jobTitle", "title"))
    if not jid or not title:
        return None
    url = str(_pick(raw, "jobUrl", "url") or "").strip()
    if url.startswith("http://"):
        url = "https://" + url[len("http://"):]
    cur = str(_pick(raw, "currency") or "GBP").upper()
    symbol = {"GBP": "£", "USD": "$", "EUR": "€"}.get(cur, "£")
    return {
        "id": jid,
        # Bare-id fallback matches the scraper's tolerant seen_pattern either way.
        "url": url or f"{BASE}/jobs/{jid}",
        "title": title,
        "company": httpfeed.clean(_pick(raw, "employerName", "employerProfileName")),
        "location": httpfeed.clean(_pick(raw, "locationName")),
        "salary": httpfeed.money(_pick(raw, "minimumSalary"), _pick(raw, "maximumSalary"),
                                 cur=symbol),
        "created": _date(_pick(raw, "date", "datePosted")),
        "ats_hint": "",     # easyApply is not exposed by the search API — only the JD page
        "source": "reed",   # SAME as the scraper: same site, same apply flow, one tracker
    }


BOARD = httpfeed.Board(
    board="reedapi", name="Reed API", base=BASE,
    search_url=search_url, parse=parse, normalize=normalize,
    # Identical to the scraper's: bare tracker ids AND live slugged URLs must fold together.
    seen_pattern=r"reed\.co\.uk/jobs/(?:[^/,\s]+/)?([0-9]+)",
    fetch="http", per_page=PER_PAGE, default_where="London",
    headers=_auth_header(),
    needs=_needs,
    apply_hint=("Iterate each .url; apply is reed.co.uk on-site (Easy Apply) or an external "
                "ATS — the search API does not expose which, so the JD page decides."),
)

if __name__ == "__main__":
    sys.exit(httpfeed.main(BOARD))
