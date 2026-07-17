#!/usr/bin/env python3
"""feed.py — enumerate job postings from Design Week Jobs (designweek.co.uk/jobs).

Design Week is the UK design industry's trade title; its board is small (~19 live, ~6 London)
but high-quality and squarely on the applicant's primary lane (§14) — brand/graphic/digital/
UX studio roles, plus creative-sector recruiters (a1 people et al.) who place juniors. Worth a
pass precisely because it is small: a full sweep costs one request.

NOT a Madgex board (unlike jobs.theguardian.com — the same-pattern guess does not apply here).
Design Week runs **WP Job Manager**, the same plugin as MBW and Dezeen Jobs. The listing page
is JS-gated ("JavaScript must be enabled in order to view listings"), but the plugin's AJAX
endpoint is plain JSON over HTTP — no browser, no key, no login. Verified live 2026-07-17:

    https://www.designweek.co.uk/jm-ajax/get_listings/?search_keywords=&per_page=100&page=1
    -> {"found_jobs":bool, "max_num_pages":int, "html":"<li class=\"post-<ID> job_listing…"}

  **Why jm-ajax and not the RSS `job_feed`** (which MBW's feed uses): Design Week's RSS
  ignores/breaks `search_keywords` — `designer`, `brand` and `zzzznonsense` ALL return 0 items
  while the unfiltered feed returns 19. jm-ajax filters correctly on the same install
  (`designer` -> 11, `brand` -> 4, `zzzznonsense` -> found_jobs:false). So keyword search is
  only trustworthy through jm-ajax. `search_location` works on both (`London` -> 6).

The JSON's `html` holds the cards; selectors verified live against that payload:
  card     li[class*="post-<ID> job_listing"]   (ID = WP post id)
  link     a[href="https://www.designweek.co.uk/job/<slug>/"]
  title    h3          company  .company strong
  meta     li.location / li.salary / li.job-type / li.date > time[datetime]

**id is the URL slug, not the post id** — the tracker stores the URL, and the URL carries no
numeric id (`/job/a1-people-london-full-time-interior-design-consultant/`), so keying on the
post id would make seen-dedup silently never match.

Apply is off-site by EMAIL, no Design Week account: the JD's `.application_details` reads
"To apply for this job email your CV and cover letter to <address>", and the address is
Cloudflare email-obfuscated (`a.job_application_email` + `span.__cf_email__[data-cfemail]`,
hex-XOR encoded) — jd.py must decode `data-cfemail` rather than expect a `mailto:` href.

Usage:
    python3 feed.py [--what designer] [--where London] [--pages N] [--all] [--force]
"""
import json
import os
import re
import sys

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_here, "..", "..", "_common", "scripts"))
import httpfeed  # noqa: E402

BASE = "https://www.designweek.co.uk"
PER_PAGE = 100

# Boundary is the NEXT card, not `</li>` — the card contains nested <li> meta rows, so a
# non-greedy `.*?</li>` truncates it at li.job-type and silently drops location/salary/date.
CARD_RE = (r'(?is)<li class="post-\d+[^"]*\bjob_listing\b.*?'
           r'(?=<li class="post-\d+[^"]*\bjob_listing\b|</ul>|\Z)')


def search_url(what, where, page):
    return f"{BASE}/jm-ajax/get_listings/?" + httpfeed.urlencode({
        "search_keywords": what or "", "search_location": where or "",
        "per_page": PER_PAGE, "orderby": "featured", "order": "DESC", "page": page,
    })


def parse(text, ctx):
    """Pure: the jm-ajax JSON envelope -> raw card chunks from its `html` field."""
    try:
        d = json.loads(text)
    except ValueError:
        return []
    if not d.get("found_jobs"):
        return []
    return [{"html": c} for c in httpfeed.cards(d.get("html") or "", CARD_RE)]


def normalize(raw, ctx):
    """Pure: one card -> the shared posting shape."""
    body = raw.get("html") or ""
    m = re.search(r'(?is)href="(https?://[^"]*?/job/([a-z0-9-]+)/?)"', body)
    if not m:
        return None
    url, slug = m.group(1), m.group(2)
    title = httpfeed.first(body, r'(?is)<h3[^>]*>(.*?)</h3>')
    if not title:
        return None
    salary = httpfeed.first(body, r'(?is)<li class="salary">(.*?)</li>')
    if salary.lower() in ("competitive", "undisclosed", "doe", "n/a", "-"):
        salary = ""
    return {
        "id": slug,                      # tracker stores the slug URL — key on it
        "url": url.split("?")[0],
        "title": title,
        "company": httpfeed.first(body, r'(?is)<div class="company">\s*<strong>(.*?)</strong>'),
        "location": httpfeed.first(body, r'(?is)<li class="location">(.*?)</li>'),
        "salary": salary,
        "created": httpfeed.first(body, r'(?is)<time[^>]+datetime="([^"]+)"'),
        "contract": httpfeed.first(body, r'(?is)<li class="job-type[^"]*">(.*?)</li>'),
        "ats_hint": "email-apply",       # cf-obfuscated employer address on the JD
        "source": "designweek",
    }


BOARD = httpfeed.Board(
    board="designweek", name="Design Week Jobs", base=BASE,
    search_url=search_url, parse=parse, normalize=normalize,
    seen_pattern=r"designweek\.co\.uk/job/([a-z0-9-]+)",
    fetch="http", per_page=PER_PAGE, default_where="",
    headers={"Accept": "application/json, text/javascript, */*; q=0.01",
             "X-Requested-With": "XMLHttpRequest", "Referer": f"{BASE}/jobs/"},
    apply_hint=("Iterate each .url; apply is EMAIL to the employer — the address is "
                "cf-obfuscated (span.__cf_email__[data-cfemail]), decode it, no account."),
)

if __name__ == "__main__":
    sys.exit(httpfeed.main(BOARD))
