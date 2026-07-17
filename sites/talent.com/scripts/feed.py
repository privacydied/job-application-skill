#!/usr/bin/env python3
"""feed.py — enumerate job postings from uk.talent.com (large UK aggregator).

Talent.com aggregates employer feeds + agency listings; its coverage overlaps Adzuna but
is not identical (it carries a lot of Hays/Robert Half/agency stock plus direct employers
like LexisNexis, CloserStill, hedgehog lab). Server-rendered HTML — no key, no login, no
browser needed. On-profile because `l=London` filters server-side, so the feed only ever
emits London-area roles for a London-or-remote applicant.

SOURCING — HTML cards, not JSON-LD. Read this before "improving" the parser:
  - The search page ships exactly ONE `application/ld+json` blob, and it is an `ItemList`
    of bare `{"url": "https://uk.talent.com/view?id=…"}` entries — **no JobPosting objects,
    no titles, no companies**. `httpfeed.ld_json()` therefore cannot source this board on
    its own; it would yield ids and nothing else.
  - There is NO public JSON API. `uk.talent.com/api/jobs` and `/jobs/api` both return the
    SPA's HTML shell with HTTP 200 (the router treats "api" as a locale — note `lang="api"`),
    and `api.talent.com/v2/*` returns 403 {"message":"Missing Authentication Token"}.
  - So the real source is the card markup, anchored on the STABLE data attributes:
    `<div data-job-id=… data-new-id="<id>" data-testid="jobcard-container-<id>">`.
    `data-new-id` is the same id used by `/view?id=<id>` and is what the tracker stores.
  - Everything else is CSS-module hashed (`JobCard_title__X32Qk`) — the hash suffix changes
    on redeploy, so every selector here matches `JobCard_<part>__\\w+`, never a literal hash.
  - Salary sits in an unlabelled chip whose class is fully hashed (`sc-fcd630a4-10`), mixed
    in with "Full-time"/"Temporary" chips, so it is matched on its `£` text instead.

PAGING: `p=<n>` — verified. `page=` and `start=` are silently IGNORED (they return page 1
unchanged), which is exactly the kind of fake-pagination bug that looks like it works.

Apply-path reality (measured — it is NOT a plain redirect):
  - `/view?id=<id>` is a Talent.com-HOSTED JD page. It returns HTTP 200 with NO server-side
    redirect (`num_redirects:0`), so do not expect `--location` to hand you the employer.
  - Its "Apply" control is an anchor to `/redirect?id=<id>&pid=<hash>&action=f-link` — a
    Talent.com interstitial that performs the off-site hop. That hop is CLIENT-SIDE: curling
    `/redirect` also returns 200 with no `Location`, so the final ATS destination is only
    resolvable in a browser, and the `pid` is minted into the page at render time.
  - Talent.com hosts no apply form and needs no account, so nothing lives in
    ats-credentials.csv for it.

Usage:
    python3 feed.py [--what "ux designer"] [--where London] [--pages N] [--all] [--force]
    python3 feed.py --nav "https://uk.talent.com/jobs?k=ux+designer&l=London"
"""
import os
import re
import sys

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_here, "..", "..", "_common", "scripts"))
import httpfeed  # noqa: E402

BASE = "https://uk.talent.com"
PER_PAGE = 20

# Card = the container div carrying data-new-id, up to the end of its <article>.
CARD_RE = re.compile(r'(?is)<div[^>]+data-new-id="(\d+)"[^>]*>(.*?)</article>')


def search_url(what, where, page):
    params = {"k": what or "", "l": where or "London"}
    if page > 1:
        params["p"] = page          # verified paging param — NOT `page`/`start`.
    return f"{BASE}/jobs?" + httpfeed.urlencode(params)


def parse(text, ctx):
    """Pure: HTML -> raw card dicts."""
    return [{"id": cid, "html": body} for cid, body in CARD_RE.findall(text or "")]


def normalize(raw, ctx):
    """Pure: one card -> the shared posting shape. Selectors tolerate CSS-module rehashing."""
    cid = (raw.get("id") or "").strip()
    body = raw.get("html") or ""
    title = httpfeed.first(body, r'class="JobCard_title__\w+"[^>]*>(.*?)</h2>')
    if not cid or not title:
        return None
    # Salary chip: the only chip whose text starts with a currency symbol.
    salary = httpfeed.first(body, r'>\s*(£[^<]{1,40})\s*</span>')
    return {
        "id": cid,
        "url": f"{BASE}/view?id={cid}",
        "title": title,
        "company": httpfeed.first(body, r'class="JobCard_company__\w+"[^>]*>(.*?)</span>'),
        "location": httpfeed.first(body, r'class="JobCard_location__\w+"[^>]*>(.*?)</span>'),
        "salary": salary,
        "created": httpfeed.first(body, r'<time[^>]+dateTime="(\d{4}-\d{2}-\d{2})'),
        "ats_hint": "",       # resolves on the /view redirect target
        "source": "talent",
    }


BOARD = httpfeed.Board(
    board="talent", name="talent.com", base=BASE,
    search_url=search_url, parse=parse, normalize=normalize,
    seen_pattern=r"talent\.com/view\?id=(\d+)",
    fetch="http", per_page=PER_PAGE, default_where="London",
    query_from_nav=lambda nav: httpfeed.query_param(nav, "k", "keywords", "q"),
    apply_hint=("Iterate each .url; /view?id= is a Talent-hosted JD page (no server-side "
                "redirect) whose Apply anchor is /redirect?id=…&pid=… — the hop off-site is "
                "client-side, so apply needs the browser. No Talent account."),
)

if __name__ == "__main__":
    sys.exit(httpfeed.main(BOARD))
