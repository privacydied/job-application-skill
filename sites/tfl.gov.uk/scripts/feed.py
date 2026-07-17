#!/usr/bin/env python3
"""feed.py — enumerate vacancies from Transport for London careers (TfL / GLA / OPDC).

One of the largest London-only public-sector tech employers, and squarely on-profile: TfL
runs a big in-house digital/data estate (§14 gov digital) plus infrastructure, networks and
OT/cyber (§13 DevOps/security). Every role is London by construction, so nothing here has to
be filtered for location. Under-competed relative to the aggregators — TfL does not syndicate
most of these.

⚠️ tfl.gov.uk/corporate/careers/ is a BROCHURE page, not a board — it holds no vacancies.
The real vacancy search is an **SAP SuccessFactors RMK (jobs2web)** site at
`london-gov.jobs2web.com/tfl/`, which this feed sources directly. (The page also still links
a legacy `tfl.taleo.net` careersection; the jobs2web host is the live one.) The site is
shared by three employers — **TfL, the GLA and OPDC** — hence company below.

Plain server-rendered HTML — no browser, no key, no login. Rows are
`li.job-tile.job-id-<ID>` carrying `data-url="/tfl/job/<slug>/<ID>/"`; ID is the stable
tracker id. Search: `/tfl/search/?q=…&locationsearch=…&startrow=N` (startrow is a 0-based
ROW offset, not a page number; 25/page).

⚠️ The tiles carry ONLY title/date/department — there is no salary and no location field on
the search page (the facets are dept + shift type; there is no location facet because the
whole board is London). Both live on the JD page instead (`Salary: £55,000 - £75,000`,
`Location: VSH / Hybrid`), so this feed emits salary="" and a constant London location rather
than inventing either. jd.py resolves the detail.

Apply is on-site and **account-gated**: the JD's "Apply now" goes to
`/talentcommunity/apply/<ID>/`, the SuccessFactors candidate flow, which needs an RMK
candidate profile.

Usage:
    python3 feed.py [--what digital] [--where London] [--pages N] [--all] [--force]
    python3 feed.py --nav "https://london-gov.jobs2web.com/tfl/search/?q=cyber"
"""
import os
import re
import sys

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_here, "..", "..", "_common", "scripts"))
import httpfeed  # noqa: E402

BASE = "https://london-gov.jobs2web.com"
PER_PAGE = 25

CARD_RE = r'(?is)<li class="job-tile job-id-(\d+).*?(?=<li class="job-tile|</ul>)'


def search_url(what, where, page):
    # `locationsearch` is accepted but pointless here — every TfL/GLA/OPDC site is London, and
    # the tiles carry no location to match on. Passed through only so an explicit --where is
    # honoured rather than silently dropped.
    q = {"q": what or "", "locationsearch": "" if (where or "").strip().lower() in
         ("", "london", "greater london") else where}
    if page > 1:
        q["startrow"] = (page - 1) * PER_PAGE      # ROW offset, not a page index.
    return f"{BASE}/tfl/search/?" + httpfeed.urlencode(q)


def parse(text, ctx):
    """Pure: HTML -> raw tile chunks keyed by job id."""
    return [{"job_id": jid, "html": body} for jid, body in
            ((m.group(1), m.group(0)) for m in re.finditer(CARD_RE, text))]


def normalize(raw, ctx):
    """Pure: one tile -> the shared posting shape. Unit-tested in tests/test_core.py.

    Each tile repeats its fields 3x (desktop/tablet/mobile blocks); every extractor below is
    a `first`-match, so the duplication is harmless.
    """
    body = raw.get("html") or ""
    jid = raw.get("job_id")
    title = httpfeed.first(body, r'(?is)class="jobTitle-link[^"]*"[^>]*>(.*?)</a>')
    href = httpfeed.first(body, r'(?is)data-url="([^"]+)"')
    if not jid or not title:
        return None
    return {
        "id": jid,
        "url": httpfeed.absolutise(href, BASE) if href else f"{BASE}/tfl/job/{jid}/",
        "title": title,
        # The site labels EVERY vacancy's own "Company:" field exactly this — the three
        # employers share one RMK instance and the tile does not say which one it is.
        "company": "TfL, GLA or OPDC",
        # Not on the tile; constant by construction (all three employers are London-only).
        "location": "London",
        "salary": "",      # JD-only — see module docstring.
        "created": httpfeed.first(body, r'(?is)class="section-field date[^"]*"[^>]*>.*?Date\s*</span>\s*(.*?)</div>')
                   or httpfeed.first(body, r'(?is)Date\s*</span>\s*([0-9]{1,2}\s+\w{3}\s+[0-9]{4})'),
        "ats_hint": "successfactors",   # RMK /talentcommunity/apply/<ID>/ — account-gated.
        "source": "tfl",
    }


BOARD = httpfeed.Board(
    board="tfl", name="TfL careers (TfL/GLA/OPDC)", base=BASE,
    search_url=search_url, parse=parse, normalize=normalize,
    seen_pattern=r"jobs2web\.com/tfl/job/(?:[^/,\s]*/)?(\d+)",
    fetch="http", per_page=PER_PAGE, default_where="London",
    apply_hint=("Iterate each .url; apply is SuccessFactors RMK "
                "(/talentcommunity/apply/<id>/) and needs an RMK candidate account."),
)

if __name__ == "__main__":
    sys.exit(httpfeed.main(BOARD))
