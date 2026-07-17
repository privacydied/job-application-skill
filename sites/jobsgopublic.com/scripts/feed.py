#!/usr/bin/env python3
"""feed.py — enumerate job postings from Jobs Go Public (UK councils, housing, charities).

The public-sector-employer board. Relevant because it is where London boroughs, housing
associations and charities post the "one-person digital team" family (§14) plus IT/AV
support (§13): digital officer, applications analyst, GIS officer, service desk, web
content. Council/housing employers under-advertise on LinkedIn/Indeed, so this is genuinely
additive rather than a re-run of the aggregators.

Platform is **Jobiqo** (Next.js front end over a Drupal/Apollo GraphQL backend at
backend.jobsgopublic.jobiqo.com). The SSR page embeds the whole result set in
`__NEXT_DATA__`, so no browser and no GraphQL POST is needed — a plain GET of
`/jobs?search=…&geo_location=…` carries the jobs. The job array is located with
`deep_find` (the Apollo path is `props.pageProps.data.jobs.pages`, but that path is a
build-artifact and moves; matching on row shape does not).

⚠️ `geo_location` is the ONLY geo param that filters, and it needs the Google-Places-style
`"<place>, UK"` label — bare `geo_location=London` returns 0. `lat`/`lon`/`radius`/
`locality`/`locationType`/`country` are accepted and then IGNORED (verified: a London label
with Manchester coordinates still returns the London set, and radius=1 == radius=200). So
the feed sends the label only; see NOTES.md.

Apply is off-site per employer: every row observed carries `applicationWorkflow:"external"`,
i.e. JGP hands off to the council's/association's own ATS. `ats_hint` records that hand-off
but not which ATS — that only resolves on the JD page (jd.py surfaces it).

Usage:
    python3 feed.py [--what "digital officer"] [--where London] [--pages N] [--all] [--force]
    python3 feed.py --nav "https://www.jobsgopublic.com/jobs?search=ux&geo_location=London,%20UK"
"""
import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_here, "..", "..", "_common", "scripts"))
import httpfeed  # noqa: E402

BASE = "https://www.jobsgopublic.com"
PER_PAGE = 25

# deep_find's `limit` counts every node it pops — scalars included, not just dicts — and the
# SSR blob is ~570KB, so the 5000 default runs out ~before the job rows and silently yields
# ZERO. Generous cap: the walk still terminates naturally (~2.5k dicts).
WALK_LIMIT = 200_000


def geo_label(where):
    """'London' -> 'London, UK' — the label Jobiqo's geo filter demands. Already-suffixed
    input is passed through so a --nav-derived value is not double-suffixed."""
    w = (where or "").strip().rstrip(",")
    if not w:
        return ""
    return w if w.lower().endswith((", uk", ", united kingdom")) else f"{w}, UK"


def search_url(what, where, page):
    q = {"search": what or ""}
    label = geo_label(where)
    if label:
        q["geo_location"] = label
    if page > 1:
        q["page"] = page
    return f"{BASE}/jobs?" + httpfeed.urlencode(q)


def _is_job(d):
    """A Jobiqo job row: __typename Job + the fields normalize actually needs."""
    return (d.get("__typename") == "Job" and d.get("id") is not None
            and "title" in d and "url" in d)


def parse(text, ctx):
    """Pure: SSR HTML -> raw Jobiqo job rows, located by shape not by path."""
    rows, seen = [], set()
    for d in httpfeed.deep_find(httpfeed.next_data(text), _is_job, limit=WALK_LIMIT):
        if d["id"] not in seen:
            seen.add(d["id"])
            rows.append(d)
    return rows


def _salary(raw):
    """salaryRangeFree -> '£34,206–£35,931' (+ unit when not annual)."""
    s = raw.get("salaryRangeFree") or {}
    sym = {"GBP": "£", "USD": "$", "EUR": "€"}.get((s.get("currencyCode") or "GBP").upper(), "£")
    out = httpfeed.money(s.get("minSalary"), s.get("maxSalary"), cur=sym)
    unit = (s.get("salaryUnit") or "").upper()
    if out and unit and unit != "YEAR":
        out += f" per {unit.lower()}"
    return out


def normalize(raw, ctx):
    """Pure: one Jobiqo row -> the shared posting shape. Unit-tested in tests/test_core.py."""
    jid = str(raw.get("id") or "").strip()
    title = httpfeed.clean(raw.get("title"))
    if not jid or not title:
        return None
    path = httpfeed.jsonpath(raw, "url", "path") or raw.get("urlNoPrefix") or ""
    # `address` is a LIST — multi-site public-sector roles genuinely list every location, and
    # the geo filter can match any one of them, so keep them all (capped) rather than [0].
    addrs = [httpfeed.clean(a) for a in (raw.get("address") or []) if a]
    location = " / ".join(addrs[:3]) + (f" +{len(addrs) - 3} more" if len(addrs) > 3 else "")
    return {
        "id": jid,
        "url": httpfeed.absolutise(path, BASE) if path else f"{BASE}/job/{jid}",
        "title": title,
        "company": httpfeed.clean(raw.get("organization")
                                  or httpfeed.jsonpath(raw, "organizationProfile", "name")),
        "location": location,
        "salary": _salary(raw),
        "created": (raw.get("published") or "")[:10],
        # Every row observed is "external" = JGP hands off to the employer's own ATS. WHICH
        # ATS is only on the JD page, so this records the hand-off, not the destination.
        "ats_hint": "external" if raw.get("applicationWorkflow") == "external" else "",
        "source": "jgp",
    }


BOARD = httpfeed.Board(
    board="jgp", name="Jobs Go Public", base=BASE,
    search_url=search_url, parse=parse, normalize=normalize,
    # ⚠️ Deliberately spans BOTH hosts: lgjobs.com is a filtered VIEW of this same Jobiqo
    # index and reuses the SAME numeric ids/slugs (proven: 42/42 lgjobs ids for
    # "digital London" are jgp ids). One shared pattern = applying via either host marks the
    # vacancy seen for both feeds, so the pair cannot produce a duplicate application.
    seen_pattern=r"(?:jobsgopublic|lgjobs)\.com/job/(?:[^/,\s]*-)?(\d+)",
    fetch="http", per_page=PER_PAGE, default_where="London",
    apply_hint=("Iterate each .url; apply is the employer's own ATS (every row is "
                "applicationWorkflow=external) — the JD page names it."),
)

if __name__ == "__main__":
    sys.exit(httpfeed.main(BOARD))
