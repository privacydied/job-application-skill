#!/usr/bin/env python3
"""feed.py — enumerate careerjet.co.uk postings via Careerjet's Job Search API **v4**.

Careerjet is a UK-facing aggregator indexing employer sites + other boards. Plain JSON over
HTTPS — no browser, no scraping. On-profile because `location` + `radius` filter
server-side, so the feed only emits London-area roles.

⚠️ STATUS: NEEDS-KEY. Complete and correct, but cannot run until a key exists.

═══ THE LEGACY PUBLIC API IS DEAD — DO NOT RESURRECT IT ═══
`http://public.api.careerjet.net/search?...&affid=<id>` (the historically "free partner id"
endpoint) NO LONGER WORKS FOR NEW USERS. Verified 2026-07-17, verbatim:

    HTTP 401
    {"error":"The legacy Job Search API is only accessible for authenticated legacy users.
      Please use the new API (v4) instead: https://www.careerjet.com/partners/api",
     "type":"ERROR"}

Reproduced identically WITH and WITHOUT an affid, and WITH and WITHOUT a Referer header, so
no generic/borrowed affid revives it. (Its other two errors are red herrings that look like
the real blocker: omitting user_ip/user_agent gives "missing param user_ip or user_agent",
and omitting a Referer gives an "Undeclared referrer" 403 — satisfy both and you still hit
the 401 above.) This feed therefore targets v4 only.

API v4 (endpoint verified ALIVE keyless, 2026-07-17):
    GET https://search.api.careerjet.net/v4/query
        ?keywords=&location=&locale_code=en_GB&page=<1-10>&page_size=<1-100>
        &sort=date&radius=<n>&user_ip=<ip>&user_agent=<ua>
Auth — confirmed live by the API's own keyless error message, verbatim:
    "You did not provide an API key. You need to provide your API key via HTTP Basic Auth
     as username value. The HTTP Basic Auth password needs to be empty."
i.e. `Authorization: Basic base64("<API_KEY>:")` — same scheme Reed uses.

`user_ip` and `user_agent` are REQUIRED on every request (they are meant to be the END
USER's; for an unattended agent there is no end user, so they default to this host's
outbound values — override with --user-ip if Careerjet ever objects).

KEY — lives in `ats-credentials.csv`, NEVER in an env var (repo rule; grepping env for a
board key is a documented false-negative). Add this row:

    careerjet-api,<YOUR_API_KEY>,,2026-07-17

(`site` = `careerjet-api`, `email` column = the key, `password` column = empty — mirrors the
`adzuna-api` row convention.)
Get a key: https://www.careerjet.com/partners/api — NOT self-serve. Per their docs, "Each
publisher website requires a unique API key, which you can obtain from your Publisher
account", so it needs a publisher registration (a website), not an instant free id.

⚠️ UNVERIFIED-LIVE: field names below come from Careerjet's published v4 docs, not from a
real response (no key to call with). They are more trustworthy than Reed's — the v4 docs
name JSON fields explicitly — but still confirm against a raw dump once a key lands.

Documented v4 response:
    {"type":"JOBS", "hits":N, "pages":N, "response_time":…, "message":…,
     "jobs":[{"title","company","date","description","locations","salary",
              "salary_currency_code","salary_min","salary_max","salary_type","site","url"}]}

Apply-path reality: `url` points to the careerjet.co.uk job page, which forwards off-site to
the originating board or the employer's ATS. Careerjet hosts no apply form and needs no
account.

Usage:
    python3 feed.py [--what "ux designer"] [--where London] [--radius 25]
                    [--pages N] [--user-ip <ip>] [--all] [--force]
"""
import base64
import json
import os
import re
import sys

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_here, "..", "..", "_common", "scripts"))
import httpfeed  # noqa: E402

BASE = "https://www.careerjet.co.uk"
API = "https://search.api.careerjet.net/v4/query"
PER_PAGE = 100          # documented max page_size
MAX_PAGE = 10           # documented max page

SIGNUP = "https://www.careerjet.com/partners/api"
CSV_ROW = "careerjet-api,<YOUR_API_KEY>,,<today>"

MISSING_KEY = (
    "no Careerjet API key. Add this row to ats-credentials.csv:\n"
    f"    {CSV_ROW}\n"
    "  (site=`careerjet-api`, email column = the key, password column = empty —\n"
    "   same convention as the `adzuna-api` row.)\n"
    f"  Get a key: {SIGNUP} — not self-serve: needs a Publisher account (a publisher\n"
    "  website), then the key comes from that account.\n"
    "  NOTE the old public.api.careerjet.net + free `affid` endpoint is DEAD for new\n"
    "  users (HTTP 401 'only accessible for authenticated legacy users') — v4 is the\n"
    "  only way in. Do not try to revive the affid route."
)

SALARY_PERIOD = {"Y": "year", "M": "month", "W": "week", "D": "day", "H": "hour"}


def _api_key():
    """The key from ats-credentials.csv row `careerjet-api` (email column). Never env."""
    key, _unused_password = httpfeed.creds_row("careerjet-api")
    return (key or "").strip()


def _needs():
    return None if _api_key() else MISSING_KEY


def _auth_header():
    key = _api_key()
    if not key:
        return {"Accept": "application/json"}
    token = base64.b64encode(f"{key}:".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}", "Accept": "application/json"}


def _opt(name, default):
    args = sys.argv
    if name in args:
        i = args.index(name)
        if i + 1 < len(args):
            return args[i + 1]
    return default


def search_url(what, where, page):
    if page > MAX_PAGE:          # v4 refuses page > 10; stop rather than 400.
        return ""
    return f"{API}?" + httpfeed.urlencode({
        "keywords": what or "",
        "location": where or "London",
        "locale_code": "en_GB",
        "sort": "date",
        "radius": _opt("--radius", "25"),
        "page": page,
        "page_size": PER_PAGE,
        # Required on every v4 call. No real end user exists for an unattended agent.
        "user_ip": _opt("--user-ip", "127.0.0.1"),
        "user_agent": httpfeed.UA,
    })


def parse(text, ctx):
    """Pure: API JSON -> raw job rows."""
    try:
        payload = json.loads(text)
    except ValueError:
        return []
    if not isinstance(payload, dict):
        return []
    jobs = payload.get("jobs")
    return [j for j in jobs if isinstance(j, dict)] if isinstance(jobs, list) else []


def _job_id(url):
    """Careerjet job URLs are `…/jobad/<hash>`; the hash is the stable id. Falls back to the
    whole URL so a shape change degrades to 'still dedups' rather than 'drops the row'."""
    m = re.search(r"/jobad/([A-Za-z0-9_-]+)", url or "")
    return m.group(1) if m else (url or "").strip()


def _salary(row):
    """v4 ships BOTH a pre-rendered `salary` string and numeric min/max. Prefer the string
    (already localised); fall back to composing the numbers."""
    text = httpfeed.clean(row.get("salary"))
    if text:
        return text
    cur = str(row.get("salary_currency_code") or "GBP").upper()
    symbol = {"GBP": "£", "USD": "$", "EUR": "€"}.get(cur, "£")
    out = httpfeed.money(row.get("salary_min"), row.get("salary_max"), cur=symbol)
    period = SALARY_PERIOD.get(str(row.get("salary_type") or "").upper())
    return f"{out} / {period}" if out and period and period != "year" else out


def normalize(raw, ctx):
    """Pure: one v4 row -> the shared posting shape."""
    url = str(raw.get("url") or "").strip()
    title = httpfeed.clean(raw.get("title"))
    jid = _job_id(url)
    if not title or not jid:
        return None
    return {
        "id": jid,
        "url": url,
        "title": title,
        "company": httpfeed.clean(raw.get("company")),
        "location": httpfeed.clean(raw.get("locations")),
        "salary": _salary(raw),
        "created": str(raw.get("date") or "")[:10],
        "ats_hint": "",     # resolves on the careerjet page's off-site forward
        "source": "careerjet",
    }


BOARD = httpfeed.Board(
    board="careerjet", name="Careerjet", base=BASE,
    search_url=search_url, parse=parse, normalize=normalize,
    seen_pattern=r"careerjet\.co\.uk/jobad/([A-Za-z0-9_-]+)",
    fetch="http", per_page=PER_PAGE, default_where="London",
    headers=_auth_header(),
    needs=_needs,
    apply_hint=("Iterate each .url; the careerjet page forwards off-site to the originating "
                "board or the employer's ATS (no Careerjet account)."),
)

if __name__ == "__main__":
    sys.exit(httpfeed.main(BOARD))
