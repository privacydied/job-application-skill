#!/usr/bin/env python3
"""feed.py — enumerate job postings from CyberSecurityJobsite.com (UK security niche).

The specialist UK cyber board. Relevant because the whole inventory is the security lane
(§14 devops/soc family): SOC analyst, security analyst, IT security, GRC. Small — ~87 live
jobs board-wide — but *every* posting is on-topic, so the junior SOC/security-analyst rows
surface here without fighting an aggregator's noise. Under-competed vs LinkedIn/Indeed.

A **Madgex** board (same platform as jobs.theguardian.com — `analytics.madgex.com` /
`madgexjb.com` assets). Unlike Guardian, its listing pages are **NOT bot-walled** — plain
server-rendered HTML over curl, so this is a browser-free `fetch="http"` feed.

Parsing (verified live 2026-07-17):
  card      `<li class="lister__item cf" id="item-<ID>">` — the id IS the stable job id
  title     `h3.lister__header > a > span`
  href      `/job/<ID>/<slug>/`  ⚠️ the href attribute contains literal newlines/tabs
            inside its quotes — `httpfeed.clean()` collapses them.
  location  `li.lister__meta-item--location`
  salary    `li.lister__meta-item--salary`
  recruiter `li.lister__meta-item--recruiter`
  posted    `li.job-actions__action.pipe`  ("10 days ago")

Search is the `?Keywords=` query param; `?page=N` paginates at 20/page (verified: pages 1-3
return 20 cards each, zero id overlap). There is **no working location filter** — `Location=`
and `radialtown=` are accepted but change nothing, so `--where` is ignored here by design and
precheck.py does the London/remote screening.

Apply is Madgex's on-page form at `/apply/<ID>/<slug>` — JS-rendered (no <form> in the static
HTML), so applying needs a browser even though sourcing does not. See NOTES.md.

Usage:
    python3 feed.py [--what "soc analyst"] [--pages N] [--all] [--force]
    python3 feed.py --nav "https://www.cybersecurityjobsite.com/jobs/?Keywords=soc+analyst"
"""
import os
import re
import sys

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_here, "..", "..", "_common", "scripts"))
import httpfeed  # noqa: E402

BASE = "https://www.cybersecurityjobsite.com"
PER_PAGE = 20

# Each card runs to the next card, or to the end of the listing on the last one. Fields are
# pulled with `first()` (leftmost match) so the final chunk's trailing page furniture can't
# shadow the card's own values.
CARD_RE = (r'(?is)<li class="lister__item[^"]*"\s+id="item-(\d+)"(.*?)'
           r'(?=<li class="lister__item|</body>)')


def search_url(what, where, page):
    q = {"Keywords": what or ""}
    if page > 1:
        q["page"] = page
    return f"{BASE}/jobs/?" + httpfeed.urlencode(q)


def parse(text, ctx):
    """Pure: HTML -> raw card dicts."""
    return [{"item_id": i, "html": b} for i, b in re.findall(CARD_RE, text)]


def normalize(raw, ctx):
    """Pure: one card -> the shared posting shape."""
    body = raw.get("html") or ""
    jid = raw.get("item_id") or ""
    if not jid:
        return None
    title = httpfeed.first(body, r'(?is)lister__header"><a[^>]*>\s*<span>(.*?)</span>')
    if not title:
        return None
    href = httpfeed.first(body, r'(?is)lister__header"><a\s+href="([^"]+)"')
    salary = httpfeed.first(body, r'(?is)lister__meta-item--salary">(.*?)</li>')
    return {
        "id": jid,
        "url": httpfeed.absolutise(href, BASE) or f"{BASE}/job/{jid}/",
        "title": title,
        "company": httpfeed.first(body, r'(?is)lister__meta-item--recruiter">(.*?)</li>'),
        "location": httpfeed.first(body, r'(?is)lister__meta-item--location">(.*?)</li>'),
        "salary": "" if salary.lower() == "competitive" else salary,
        "created": httpfeed.first(body, r'(?is)<li class="job-actions__action pipe">(.*?)</li>'),
        "ats_hint": "madgex-direct",
        "source": "cybersecjobsite",
    }


BOARD = httpfeed.Board(
    board="cybersecjobsite", name="CyberSecurityJobsite", base=BASE,
    search_url=search_url, parse=parse, normalize=normalize,
    seen_pattern=r"cybersecurityjobsite\.com/job/(\d+)",
    fetch="http", per_page=PER_PAGE, default_where="",
    apply_hint=("Iterate each .url; apply is the Madgex on-page form at /apply/<id>/<slug> "
                "(JS-rendered → needs camofox). No location filter — precheck screens."),
)

if __name__ == "__main__":
    sys.exit(httpfeed.main(BOARD))
