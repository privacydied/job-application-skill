#!/usr/bin/env python3
"""feed.py — enumerate job postings from LGjobs (UK local government).

The local-government slice of the **same Jobs Go Public / Jobiqo index** that
`sites/jobsgopublic.com/` sources. Same operator, same backend, same numeric job ids, same
URL slugs — LGjobs is a council-only *view*, not a separate board.

⛔ **LGjobs is a strict SUBSET of jobsgopublic.com — it contributes ZERO unique vacancies.**
Verified 2026-07-17: for `--what digital --where London`, all **42/42** LGjobs ids were
present in the full 271-row jobsgopublic set. Its value is precision, not reach: 42
council-only rows vs 271 mixed public-sector rows, so it is a cheaper, higher-signal pass
when you specifically want local government. Running BOTH boards for one query is pure
duplicated work — see NOTES.md.

Because the vacancy behind an LGjobs URL is the *same vacancy* as the jobsgopublic one, this
feed shares jobsgopublic's `seen_pattern` (it spans both hosts) and emits the same
`source:"jgp"` — applying via either host marks it seen for both, so the pair cannot produce
a duplicate application. This mirrors how `sites/reed.co.uk/` folds its scraper and API
feeds onto one tracker identity.

Parsing is identical to the jobsgopublic feed (Next.js `__NEXT_DATA__` located by row shape
via `deep_find`, `geo_location="<place>, UK"` as the only working geo param). That module is
the reference — read its docstring for the Jobiqo quirks.

Usage:
    python3 feed.py [--what "digital officer"] [--where London] [--pages N] [--all] [--force]
    python3 feed.py --nav "https://www.lgjobs.com/jobs?search=ux&geo_location=London,%20UK"
"""
import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_here, "..", "..", "_common", "scripts"))
# Sibling board on one engine: reuse the jobsgopublic parsers rather than fork 50 lines of
# Jobiqo quirks that would then drift out of sync when the platform changes.
sys.path.insert(0, os.path.join(_here, "..", "..", "jobsgopublic.com", "scripts"))
import httpfeed  # noqa: E402
import feed as jgp  # noqa: E402  (sites/jobsgopublic.com/scripts/feed.py)

BASE = "https://www.lgjobs.com"
PER_PAGE = 25


def search_url(what, where, page):
    q = {"search": what or ""}
    label = jgp.geo_label(where)
    if label:
        q["geo_location"] = label
    if page > 1:
        q["page"] = page
    return f"{BASE}/jobs?" + httpfeed.urlencode(q)


def parse(text, ctx):
    """Pure: same Jobiqo SSR shape as jobsgopublic."""
    return jgp.parse(text, ctx)


def normalize(raw, ctx):
    """Pure: jobsgopublic's mapping, re-hosted onto lgjobs.com URLs.

    `source` stays "jgp": same operator, same index, same vacancy, ONE tracker identity.
    """
    n = jgp.normalize(raw, ctx)
    if not n:
        return None
    n["url"] = n["url"].replace(jgp.BASE, BASE)
    return n


BOARD = httpfeed.Board(
    board="lgjobs", name="LGjobs", base=BASE,
    search_url=search_url, parse=parse, normalize=normalize,
    # Same both-host pattern as jobsgopublic — the ids are literally the same ids.
    seen_pattern=jgp.BOARD.seen_pattern,
    fetch="http", per_page=PER_PAGE, default_where="London",
    apply_hint=("Iterate each .url; apply is the council's own ATS (applicationWorkflow="
                "external). NOTE: every row here also exists on Jobs Go Public (jgp)."),
)

if __name__ == "__main__":
    sys.exit(httpfeed.main(BOARD))
