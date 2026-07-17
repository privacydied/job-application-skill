#!/usr/bin/env python3
"""feed.py — enumerate job postings from Music Business Worldwide Jobs (MBW).

The music industry's main job board, and the applicant's **standout lane**: he is half of a
West London alt-hip-hop duo and has shipped music-tech products, so a design/product/digital
role at a label, publisher or distributor is the one place his two differentiators compound
instead of competing. Inventory is the industry itself — Spotify, Kobalt, BMG, Believe, The
Orchard, Live Nation, Nettwerk, Three Six Zero — and it appears on NO aggregator in this
repo. Small (~47 live, ~16 London), so a full pass is cheap and nothing is missed.

MBW runs **WP Job Manager**, which ships a structured RSS `job_feed` — used here in
preference to scraping the Avada/Fusion HTML soup on the listing page. No browser, no key,
no login. Verified live 2026-07-17:

    https://www.musicbusinessworldwide.com/jobs?feed=job_feed&posts_per_page=100

  - **`posts_per_page` is the page-size lever that actually works** — the feed defaults to
    WP's 10-item RSS cap, and `posts_per_rss`/`showposts` are BOTH ignored (10, 10);
    `posts_per_page=100` returns the whole board (47). That one param is why this feed needs
    no pagination at all: `search_url` returns None for page>1.
  - `search_keywords` and `search_location` are honoured server-side (`marketing` -> 33,
    `designer` -> 4, `zzzznonsense` -> 0, `search_location=London` -> 16).

Each `<item>` carries the `job_listing:` namespace — company/location/salary/type as real
XML fields, no selector guessing:
    <title>, <link>https://www.musicbusinessworldwide.com/jobs/job/<ID>/</link>, <pubDate>,
    <job_listing:company>, <job_listing:location>, <job_listing:salary>,
    <job_listing:job_type>, <job_listing:job_category>

Apply is **on-site** (no employer hop) but is NOT a plain form: the JD's Apply button opens
an Avada off-canvas panel holding a Gravity Form (id 14) whose fields are LinkedIn, Email*,
**One-Time Password***, First/Last Name*, Phone, CV upload, privacy checkbox*. The OTP is
emailed — so applying requires live mailbox access, not just a filled form. Flagged as
`ats_hint="mbw-gform-otp"` so the apply stage knows to expect the email round-trip.

Usage:
    python3 feed.py [--what "marketing"] [--where London] [--all] [--force]
"""
import os
import re
import sys

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_here, "..", "..", "_common", "scripts"))
import httpfeed  # noqa: E402

BASE = "https://www.musicbusinessworldwide.com"


def search_url(what, where, page):
    # posts_per_page=100 covers the whole board in one GET — no pagination needed.
    if page > 1:
        return None
    return f"{BASE}/jobs?" + httpfeed.urlencode({
        "feed": "job_feed", "posts_per_page": 100,
        "search_keywords": what or "", "search_location": where or "",
    })


def parse(text, ctx):
    """Pure: RSS XML -> raw <item> chunks."""
    return [{"xml": x} for x in httpfeed.cards(text, r"(?is)<item>(.*?)</item>")]


def _tag(xml, name):
    """Text of an RSS element, CDATA-unwrapped and cleaned."""
    m = re.search(rf'(?is)<{name}[^>]*>(.*?)</{name}>', xml or "")
    if not m:
        return ""
    v = m.group(1).strip()
    c = re.match(r'(?is)^\s*<!\[CDATA\[(.*?)\]\]>\s*$', v)
    return httpfeed.clean(c.group(1) if c else v)


def normalize(raw, ctx):
    """Pure: one RSS item -> the shared posting shape."""
    xml = raw.get("xml") or ""
    link = _tag(xml, "link")
    m = re.search(r"/jobs/job/(\d+)", link)
    if not m:
        return None
    title = _tag(xml, "title")
    if not title:
        return None
    salary = _tag(xml, "job_listing:salary")
    if salary.lower() in ("competitive", "undisclosed", "doe", "n/a", "-"):
        salary = ""
    return {
        "id": m.group(1),
        "url": link.split("?")[0],
        "title": title,
        "company": _tag(xml, "job_listing:company"),
        "location": _tag(xml, "job_listing:location"),
        "salary": salary,
        "created": _tag(xml, "pubDate"),
        "contract": _tag(xml, "job_listing:job_type"),
        "category": _tag(xml, "job_listing:job_category"),
        "ats_hint": "mbw-gform-otp",   # on-site Gravity Form + emailed one-time password
        "source": "mbw",
    }


BOARD = httpfeed.Board(
    board="mbw", name="Music Business Worldwide", base=BASE,
    search_url=search_url, parse=parse, normalize=normalize,
    seen_pattern=r"musicbusinessworldwide\.com/jobs/job/(\d+)",
    fetch="http", default_where="",     # board-wide by default; precheck filters location
    headers={"Accept": "application/rss+xml,application/xml;q=0.9,*/*;q=0.8"},
    apply_hint=("Iterate each .url; apply is ON-SITE (Gravity Form in the JD's off-canvas "
                "panel) and needs an EMAILED one-time password — mailbox access required."),
)

if __name__ == "__main__":
    sys.exit(httpfeed.main(BOARD))
