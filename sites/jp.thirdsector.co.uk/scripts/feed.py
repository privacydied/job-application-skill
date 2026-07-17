#!/usr/bin/env python3
"""feed.py — enumerate job postings from Third Sector Jobs (jp.thirdsector.co.uk).

Third Sector's own charity-sector board — a sibling of CharityJob (sites/charityjob.co.uk/)
with distinct employer inventory, skewed to charity comms/digital/fundraising (family §14).
Small and slow-moving (~97 live postings across 5 pages), so it exhausts fast and is cheap
to sweep whole.

DOMAIN: `thirdsectorjobs.co.uk` is dead (connection timeout). The live board is
`jobs.thirdsector.co.uk`, which 301s to **jp.thirdsector.co.uk** — the canonical host used
here. It is NOT a Madgex board (no `Keywords=` param, no `.lister__item`): it is a
nopCommerce storefront repurposed as a job board, so listings are `div.product-item.job-box`
carrying `data-productid` — the stable id — and link to `/jobdetail/<id>/<slug>`.

Plain server-rendered HTML — no browser, no key, no login to search or view. Verified live
2026-07-17. Card shape (consistent across all 20 cards on a full page):
  title     h2.product-title > a[href="/jobdetail/<id>/<slug>"]
  ul.job-info-list > li > p  ×3, positionally [location, salary, hours]
  .description  teaser   .days-count  "9 days ago" / "5 days left"

LOCATION (important): `--where` is accepted but NOT sent to the board, because the board has
no working location filter to send it to. `?location=` is ignored (verified: `?q=digital`
and `?q=digital&location=london` both return the same 2 rows), and free text can't carry it
either (`?q=digital london` -> 0). The only location lever is a PATH browse
(`/jobs/london-(greater)?q=digital`), but the location taxonomy is employer free-text turned
into slugs and is hopelessly fragmented — London alone splits across ~30 slugs
(`london-(greater)` 12, `london-(central)` 8, `london` 5, `central-london` 5, `greater-london`,
`london-greater`, `city-of-london`, `wandsworth-london`, bare postcodes, even street
addresses). Any single slug silently drops most London roles, so the feed sweeps the whole
(tiny) inventory, emits the card's raw location text, and lets precheck.py screen
London/remote — which it does far more reliably.

COMPANY is empty: search cards carry no employer name (verified — no `EmployerName` in the
listing markup, and the card image alt is just the job title). The JD page has it, in both
JSON-LD and `.EmployerName`; jd.py surfaces it per-listing.

Usage:
    python3 feed.py [--what digital] [--where London] [--pages N] [--all] [--force]
    python3 feed.py --nav "https://jp.thirdsector.co.uk/jobs?q=digital"
"""
import html
import os
import re
import sys

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_here, "..", "..", "_common", "scripts"))
import httpfeed  # noqa: E402

BASE = "https://jp.thirdsector.co.uk"
PER_PAGE = 20


def _txt(s):
    """httpfeed.clean() + a full entity decode.

    This board emits HEX character entities — salaries arrive as `&#xA3;45,000`. clean()
    decodes the named entities and DECIMAL ones (`&#163;`) but not hex, so clean() alone
    leaks a literal "&#xA3;45,000" into the salary field (seen live). html.unescape covers
    every entity form; it runs after clean() has already stripped real tags.
    """
    return html.unescape(httpfeed.clean(s or "")).strip()

# One card: id from data-productid, body up to the next card / the pager / the footer.
CARD_RE = (r'(?is)<div class="product-item job-box[^"]*"\s+data-productid="(\d+)"'
           r'(.*?)(?=<div class="product-item job-box|<div class="pager|<div class="footer)')
LI_RE = r'(?is)<li>\s*<p>(.*?)</p>\s*</li>'


def search_url(what, where, page):
    # `where` is deliberately NOT sent — see the LOCATION note above.
    params = {"pagenumber": page}
    if what:
        params["q"] = what
    return f"{BASE}/jobs?" + httpfeed.urlencode(params)


def parse(text, ctx):
    """Pure: HTML -> raw card dicts."""
    return [{"pid": pid, "html": body} for pid, body in re.findall(CARD_RE, text)]


def normalize(raw, ctx):
    """Pure: one card -> the shared posting shape."""
    body = raw.get("html") or ""
    pid = raw.get("pid") or ""
    m = re.search(r'(?is)<h2 class="product-title">\s*<a\s+href="(/jobdetail/\d+/[^"]*)"[^>]*>(.*?)</a>',
                  body)
    if not (m and pid):
        return None
    href, title = m.group(1), _txt(m.group(2))
    if not title:
        return None
    # li[0]=location, li[1]=salary, li[2]=hours — positionally stable (all 20/20 cards on a
    # full page ship exactly these three).
    lis = [_txt(x) for x in re.findall(LI_RE, body)]
    return {
        "id": pid,
        "url": httpfeed.absolutise(href, BASE),
        "title": title,
        "company": "",                      # not in the card — see COMPANY note above
        "location": lis[0] if len(lis) > 0 else "",
        "salary": lis[1] if len(lis) > 1 else "",
        "created": _txt(httpfeed.first(body, r'(?is)<div class="days-count[^"]*">(.*?)</div>')),
        "ats_hint": "",                     # apply resolves per-listing ("Apply on website")
        "source": "thirdsector",
    }


BOARD = httpfeed.Board(
    board="thirdsector", name="Third Sector Jobs", base=BASE,
    search_url=search_url, parse=parse, normalize=normalize,
    seen_pattern=r"thirdsector\.co\.uk/jobdetail/(\d+)",
    fetch="http", per_page=PER_PAGE, default_where="London",
    apply_hint=("Iterate each .url; apply is off-site per employer "
                "('Apply on website'); some rows are the board's own 'Easy apply'."),
)

if __name__ == "__main__":
    sys.exit(httpfeed.main(BOARD))
