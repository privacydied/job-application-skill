#!/usr/bin/env python3
"""feed.py — enumerate uk.jooble.org postings via Jooble's partner JSON API.

Jooble is a large international aggregator; its UK index carries agency + direct-employer
listings that overlap Adzuna/Talent only partially. The API is a single POST returning
JSON — no browser, no scraping. On-profile because `location` filters server-side, so the
feed only emits London-area roles for a London-or-remote applicant.

⚠️ STATUS: NEEDS-KEY. This feed is complete and correct but CANNOT run until a key exists.

API (endpoint verified alive over plain HTTP, 2026-07-17):
    POST https://jooble.org/api/<KEY>
    Content-Type: application/json
    body: {"keywords": "...", "location": "...", "radius": "25", "page": "1"}

Verified auth behaviour — worth knowing, because the two failure modes look nothing alike:
  - A UUID-shaped but unregistered key reaches Jooble's ORIGIN and is rejected with
    HTTP 403 + the HTML body "Error 403 Access is available only for registered users"
    (`cf-cache-status: DYNAMIC` proves it passed through Cloudflare to the app). So the
    endpoint is ALIVE and plain urllib can reach it — no browser needed.
  - A MALFORMED (non-UUID) key instead trips Cloudflare's "Just a moment…" JS challenge.
    That is a routing artefact, NOT evidence the API is bot-walled. Do not "fix" it with a
    browser — fix the key.

KEY — lives in `ats-credentials.csv`, NEVER in an env var (repo rule; grepping env for a
board key is a documented false-negative). Add this row:

    jooble-api,<YOUR_API_KEY>,,2026-07-17

(`site` = `jooble-api`, `email` column = the key, `password` column = empty — mirrors the
`adzuna-api` row convention.)
Get a key: https://jooble.org/api/about — NOT self-serve like Adzuna. You submit a form
(name, position, email, **website**, phone) and Jooble issues the key to webmasters/portal
operators; there is no instant-download key page.

⚠️ UNVERIFIED-LIVE: the request/response field names below are Jooble's conventional
partner-API shape. They could NOT be confirmed, because (a) no key exists to make a real
call, and (b) Jooble publishes no public schema page — https://jooble.org/api/about
describes the product and the key-request form only, and the deeper /api/*documentation
paths 403. `parse()`/`normalize()` are therefore written defensively (multiple key
spellings, tolerant of missing fields). The moment a key lands, dump one raw response and
tighten this — do not assume these names are right.

Expected response (conventional shape):
    {"totalCount": N,
     "jobs": [{"title","location","snippet","salary","source","type","link","company",
               "updated","id"}]}

Apply-path reality: `link` points OFF-SITE — Jooble is an index, not an ATS. It sends you
to the originating board or the employer's own ATS, so there is no Jooble account to keep.
Expect a mix of destinations (including boards this repo already handles separately, so
cross-board duplicates are normal and precheck/tracker dedup does the work).

Usage:
    python3 feed.py [--what "ux designer"] [--where London] [--radius 25]
                    [--pages N] [--all] [--force]
"""
import json
import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_here, "..", "..", "_common", "scripts"))
import httpfeed  # noqa: E402

BASE = "https://uk.jooble.org"
API = "https://jooble.org/api"

SIGNUP = "https://jooble.org/api/about"
CSV_ROW = "jooble-api,<YOUR_API_KEY>,,<today>"

MISSING_KEY = (
    "no Jooble API key. Add this row to ats-credentials.csv:\n"
    f"    {CSV_ROW}\n"
    "  (site=`jooble-api`, email column = the key, password column = empty —\n"
    "   same convention as the `adzuna-api` row.)\n"
    f"  Get a key: {SIGNUP} — not self-serve: submit the form (name, position, email,\n"
    "  website, phone) and Jooble issues a key. Without it every call returns HTTP 403\n"
    "  \"Access is available only for registered users\"."
)


def _api_key():
    """The key from ats-credentials.csv row `jooble-api` (email column). Never env."""
    key, _unused_password = httpfeed.creds_row("jooble-api")
    return (key or "").strip()


def _needs():
    return None if _api_key() else MISSING_KEY


def _radius():
    args = sys.argv
    if "--radius" in args:
        i = args.index("--radius")
        if i + 1 < len(args):
            try:
                return str(max(0, int(args[i + 1])))
            except ValueError:
                pass
    return "25"


def search_url(what, where, page):
    """The key is part of the PATH, not a header or query param."""
    key = _api_key()
    return f"{API}/{key}" if key else ""


def body(what, where, page):
    """The whole query is the POST body. Jooble wants these as STRINGS, not ints."""
    return {
        "keywords": what or "",
        "location": where or "London",
        "radius": _radius(),
        "page": str(page),
    }


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


def _pick(row, *names):
    """First present key among `names`, tolerating casing drift — the live response shape
    is unconfirmed (see UNVERIFIED-LIVE in the docstring)."""
    for n in names:
        for variant in (n, n[0].upper() + n[1:]):
            if row.get(variant) not in (None, ""):
                return row[variant]
    return ""


def normalize(raw, ctx):
    """Pure: one API row -> the shared posting shape."""
    jid = str(_pick(raw, "id", "uid") or "").strip()
    title = httpfeed.clean(_pick(raw, "title"))
    link = str(_pick(raw, "link", "url") or "").strip()
    if not title or not (jid or link):
        return None
    return {
        "id": jid or link,            # fall back to the link when no id ships
        "url": link or f"{BASE}/away/{jid}",
        "title": title,
        "company": httpfeed.clean(_pick(raw, "company")),
        "location": httpfeed.clean(_pick(raw, "location")),
        # Jooble returns salary as free text ("£40,000 - £50,000 a year"), not min/max.
        "salary": httpfeed.clean(_pick(raw, "salary")),
        "created": str(_pick(raw, "updated") or "")[:10],
        "ats_hint": "",               # resolves on the off-site destination
        "source": "jooble",
    }


BOARD = httpfeed.Board(
    board="jooble", name="Jooble", base=BASE,
    search_url=search_url, parse=parse, normalize=normalize, body=body,
    seen_pattern=r"jooble\.org/(?:away|jdp)/([A-Za-z0-9_-]+)",
    fetch="http", default_where="London",
    headers={"Accept": "application/json"},
    needs=_needs,
    apply_hint=("Iterate each .url; Jooble is an index — the link hops off-site to the "
                "originating board or the employer's ATS (no Jooble account)."),
)

if __name__ == "__main__":
    sys.exit(httpfeed.main(BOARD))
