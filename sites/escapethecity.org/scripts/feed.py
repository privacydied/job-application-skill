#!/usr/bin/env python3
"""feed.py — enumerate job postings from Escape the City (escapethecity.org).

The purpose-driven board: London-centric charity/social-enterprise/B-Corp roles, heavy on
the "one-person digital team" family (§14) — digital officer, content, comms, campaigns.
Under-competed vs the aggregators because the inventory is curated and small (~2.5k live).

Sourcing is the site's OWN Algolia index, queried directly — no browser, no login. The
public search key + app id ship in the page bundle (`/js/main/app.js` → `{algolia:{app_id,
app_key}}`), which is what a search-only Algolia key is designed for: it is the same
credential the site's JS hands to every anonymous visitor. Verified live 2026-07-17:

    GET https://6e1nsxntth-dsn.algolia.net/1/indexes/listings-live?query=...&page=N
        X-Algolia-Application-Id: 6E1NSXNTTH
        X-Algolia-API-Key: d4ceccfb371537bb6eab4cebd7f33f98

Two live indexes exist — `listings-live` (relevance, used here) and `listings-live-latest`
(recency). Listing pages are `/opportunity/<slug>`; `<slug>` is the stable id in the tracker.

LOCATION (important): `--where` is folded into the Algolia free-text `query`, NOT a facet
filter. The `Regions` facet looks like the obvious lever but is a sparse legacy field — only
~214 of 2476 live rows carry it, and `facetFilters=[["Regions:London"]]` + `query=digital`
returns **0** while `query="digital London"` returns 40 real London rows (verified). The
searchable `location-txt` attribute is what actually carries location, so free text is the
only lever that works. precheck.py does the real London/remote screening.

Usage:
    python3 feed.py [--what digital] [--where London] [--pages N] [--all] [--force]
    python3 feed.py --nav "https://www.escapethecity.org/search/jobs?query=digital"
"""
import json
import os
import re
import sys
from datetime import datetime, timezone

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_here, "..", "..", "_common", "scripts"))
import httpfeed  # noqa: E402

BASE = "https://www.escapethecity.org"
APP_ID = "6E1NSXNTTH"
API_KEY = "d4ceccfb371537bb6eab4cebd7f33f98"
INDEX = "listings-live"
ALGOLIA = f"https://{APP_ID.lower()}-dsn.algolia.net/1/indexes/{INDEX}"
PER_PAGE = 20

# Employer-entered salary-low values below this are not annual GBP (day rates, "160",
# thousands-shorthand) — 16 of 453 salaried rows in a 1000-row sample. Emitting them as
# "£160" would be actively misleading, so they're dropped rather than guessed at.
MIN_PLAUSIBLE_SALARY = 1000


def search_url(what, where, page):
    # `where` is part of the free-text query — see the LOCATION note above.
    query = " ".join(t for t in [(what or "").strip(), (where or "").strip()] if t)
    return ALGOLIA + "?" + httpfeed.urlencode({
        "query": query, "hitsPerPage": PER_PAGE, "page": max(0, page - 1),
    })


def parse(text, ctx):
    """Pure: Algolia JSON -> raw hit dicts."""
    try:
        return json.loads(text).get("hits") or []
    except (ValueError, AttributeError):
        return []


def _num(v):
    try:
        return float(v) if v else 0.0
    except (TypeError, ValueError):
        return 0.0


def _salary(raw):
    """`salary-low`/`salary-max` -> a display string, dropping employer-entered garbage.

    Both ends are independently unreliable: IDEO's live row is low=90000 max=100, which
    money() would render "£90,000–£100" (a max BELOW the min). So a max is only trusted
    when it is itself plausible AND >= low; otherwise just the low is shown.
    """
    low, high = _num(raw.get("salary-low")), _num(raw.get("salary-max"))
    if low < MIN_PLAUSIBLE_SALARY:
        return ""
    if high < MIN_PLAUSIBLE_SALARY or high < low:
        high = 0
    return httpfeed.money(low, high)


def _location(raw):
    """`location-txt` when set (844/1000 rows); else the remote mode ("Remote - 100%",
    "Hybrid - 60%"), which is the only location signal the other 156 carry."""
    loc = httpfeed.clean(raw.get("location-txt") or "")
    if loc:
        return loc
    modes = [m for m in (raw.get("option-remote") or []) if m]
    return httpfeed.clean(", ".join(modes))


def _created(raw):
    ts = raw.get("posted-date")
    if not isinstance(ts, (int, float)) or ts <= 0:
        return ""
    try:
        return datetime.fromtimestamp(ts / 1000, timezone.utc).strftime("%Y-%m-%d")
    except (ValueError, OSError, OverflowError):
        return ""


def normalize(raw, ctx):
    """Pure: one Algolia hit -> the shared posting shape."""
    slug = (raw.get("slug") or "").strip()
    title = httpfeed.clean(raw.get("job-title") or "")
    if not slug or not title:
        return None
    return {
        "id": slug,                       # matches /opportunity/<slug> in the tracker
        "url": f"{BASE}/opportunity/{slug}",
        "title": title,
        "company": httpfeed.clean(raw.get("org-name") or ""),
        "location": _location(raw),
        "salary": _salary(raw),
        "created": _created(raw),
        "ats_hint": "",                   # apply resolves per-listing (employer's own ATS)
        "source": "escapecity",
    }


def _query_from_nav(nav):
    """Cooldown key from a site search URL: `?query=` / `?q=`, else a `/search/<x>` path.

    `?query=` is the site SPA's real search param (app.js: `"query"==c && (this.search_params
    .searchTerm=...)`), not a guess.
    """
    q = httpfeed.query_param(nav, "query", "q", "keywords")
    if q:
        return q
    m = re.search(r"/search/([a-z0-9-]+)", nav or "")
    return m.group(1).replace("-", " ") if m else ""


def _rewrite_argv(argv):
    """Translate `--nav <escapethecity.org URL>` into `--what <query>`.

    ⚠️ Load-bearing. httpfeed.run() fetches a `--nav` URL **verbatim** for page 1, but this
    board's rows come from the Algolia API, not the site's HTML — so handing run() a site URL
    feeds a Vue SPA page to json.loads() and silently yields **0 jobs** (observed). pipeline.py
    passes `--nav` whenever the loop has one, so this path has to work. Translating the nav to
    the query it encodes lets search_url() rebuild the correct Algolia URL.

    An Algolia URL passed as --nav is left alone (it is already directly fetchable).
    """
    if "--nav" not in argv:
        return argv
    i = argv.index("--nav")
    if i + 1 >= len(argv):
        return argv
    nav = argv[i + 1]
    if "algolia.net" in nav:
        return argv
    out = argv[:i] + argv[i + 2:]
    q = _query_from_nav(nav)
    if q and "--what" not in out:
        out += ["--what", q]
    return out


BOARD = httpfeed.Board(
    board="escapecity", name="Escape the City", base=BASE,
    search_url=search_url, parse=parse, normalize=normalize,
    seen_pattern=r"escapethecity\.org/opportunity/([^/?\s,\"]+)",
    fetch="http", per_page=PER_PAGE, default_where="London",
    headers={"X-Algolia-Application-Id": APP_ID, "X-Algolia-API-Key": API_KEY,
             "Accept": "application/json"},
    query_from_nav=_query_from_nav,
    apply_hint=("Iterate each .url; apply is off-site per employer "
                "(Escape the City links out to the org's own ATS/careers page)."),
)

if __name__ == "__main__":
    # NB: not httpfeed.main(BOARD) — argv needs the --nav rewrite above before run() sees it.
    try:
        import stagetimer
        _src = stagetimer.timed("source")
    except Exception:
        import contextlib
        _src = contextlib.nullcontext()
    with _src:
        sys.exit(httpfeed.run(BOARD, _rewrite_argv(sys.argv[1:])))
