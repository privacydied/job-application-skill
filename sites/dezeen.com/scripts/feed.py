#!/usr/bin/env python3
"""feed.py — enumerate job postings from Dezeen Jobs (architecture / interiors / design).

Dezeen is the biggest architecture-and-design title in the world and its board carries ~140
live roles at name studios. Relevant to the applicant's design lane (§14) mostly at the edges
— it is architecture/interiors-weighted, so the on-profile slice is the digital/graphic/
product/brand-design roles rather than the studio-architect bulk; precheck's title gate is
what makes this board worth sourcing rather than reading.

⚠️ **BROWSER-ONLY — this is the one board here that plain HTTP cannot reach.**
  - `https://www.dezeen.com/jobs/` **302s to `https://www.dezeenjobs.com/`** — a separate
    domain, which is where the board actually lives (BASE below is dezeenjobs.com).
  - Every dezeenjobs.com endpoint is behind a Cloudflare **managed challenge**: HTTP 403 with
    `Cf-Mitigated: challenge` + a "Just a moment…" interstitial. This is NOT a User-Agent or
    header problem — verified 403 on `/`, `/feed/`, `?feed=job_feed`, `/wp-json/wp/v2/job_listing`
    AND `/jm-ajax/get_listings/`, with full browser header sets (Sec-Fetch-*, Accept-CH,
    Accept-Language, --compressed). The challenge is a JS/TLS-fingerprint gate; curl/urllib
    cannot pass it, so `fetch="cfx"` is a real requirement, not a convenience.
  - A real browser clears the challenge automatically in ~5s and then every route works.

Like MBW and Design Week, Dezeen Jobs runs **WP Job Manager**, so the transport is the
plugin's AJAX endpoint — navigated to (not XHR'd) so camofox renders it:

    https://www.dezeenjobs.com/jm-ajax/get_listings/?search_location=&per_page=50&page=N
    -> {"found_jobs":bool,"max_num_pages":int,"html":"<li class=\"post-<ID> … job_listing…"}

Chrome renders a bare JSON response inside `<pre>`, so `cfx_get`'s `outerHTML` gives
`<html>…<body><pre>{…}</pre></body></html>`; `parse()` therefore unwraps `<pre>` + unescapes
before `json.loads`, and also accepts raw JSON in case a future fetch mode returns it directly.

  - Pagination is REAL here: `per_page=50` -> `max_num_pages:3` (~140 jobs), page 2 returns a
    distinct set. (The public `/page/2/` archive is a decoy — it returns page 1's 50 ids
    verbatim, so it must NOT be used for paging.)
  - `search_location` works (`London` -> 2 pages).
  - **`search_keywords` is BROKEN on this install — it returns HTTP 500 "critical error"**
    (both `designer` and a nonsense term). So `--what` is deliberately NOT sent upstream;
    sourcing is location-scoped only and precheck does the title filtering.

Selectors verified against the real rendered payload (2026-07-17):
  card     li[class*="post-<ID> … job_listing"]      (ID = WP post id, also the URL suffix)
  link     a[href="https://www.dezeenjobs.com/job/<slug>-<ID>/"]
  title    h1.entry-title > a          company  h1.entry-title's /company/ link ("… at <a>")
  location .location-tag-list links    salary   .salary-range ("Salary: €85,000 - €90,000")
  date     time.entry-date

Apply is off-site per studio on the JD; no Dezeen account is needed to read a listing.

Usage:
    CFX_KEY=… CFX_TAB=… python3 feed.py [--where London] [--pages N] [--all] [--force]
"""
import json
import os
import re
import sys

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_here, "..", "..", "_common", "scripts"))
import httpfeed  # noqa: E402

BASE = "https://www.dezeenjobs.com"
PER_PAGE = 50

# NB the `\s[^>]*` before `class=`: the RAW jm-ajax payload breaks the line between `<li` and
# `class="post-…"`, so a `<li class=` literal silently matches nothing. (A browser's DOM
# serializer normalises that whitespace away — i.e. the rendered page LOOKS single-line and
# hides the trap.) Boundary is the next card, not `</li>` — cards nest <li> meta rows.
_CARD = r'<li\s[^>]*class="post-\d+[^"]*\bjob_listing\b'
CARD_RE = rf'(?is){_CARD}.*?(?={_CARD}|</ul>|\Z)'


def search_url(what, where, page):
    # `search_keywords` 500s on this install — never send it. precheck filters titles.
    return f"{BASE}/jm-ajax/get_listings/?" + httpfeed.urlencode({
        "search_location": where or "", "per_page": PER_PAGE,
        "orderby": "featured", "order": "DESC", "page": page,
    })


def _envelope(text):
    """The jm-ajax JSON, whether served raw or rendered by Chrome inside <pre>."""
    t = (text or "").strip()
    try:
        return json.loads(t)
    except ValueError:
        pass
    m = re.search(r'(?is)<pre[^>]*>(.*?)</pre>', t)
    if not m:
        return {}
    raw = re.sub(r'<[^>]+>', '', m.group(1))
    raw = (raw.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
              .replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " "))
    try:
        return json.loads(raw)
    except ValueError:
        return {}


def parse(text, ctx):
    """Pure: rendered jm-ajax response -> raw card chunks."""
    d = _envelope(text)
    if not d.get("found_jobs"):
        return []
    return [{"html": c} for c in httpfeed.cards(d.get("html") or "", CARD_RE)]


def normalize(raw, ctx):
    """Pure: one card -> the shared posting shape."""
    body = raw.get("html") or ""
    m = re.search(r'(?is)href="(https?://[^"]*?/job/([a-z0-9-]*?(\d+))/?)"', body)
    if not m:
        return None
    url, jid = m.group(1), m.group(3)
    title_block = httpfeed.first(body, r'(?is)<h1 class="entry-title"[^>]*>(.*?)</h1>') or ""
    title = httpfeed.first(body, r'(?is)<h1 class="entry-title"[^>]*>\s*<a[^>]*>(.*?)</a>')
    if not title:
        return None
    # "<title a> … at <a href="/company/<slug>">Company</a>" — company is the /company/ link.
    company = httpfeed.first(body, r'(?is)<h1 class="entry-title".*?href="[^"]*/company/[^"]*"[^>]*>(.*?)</a>')
    # NB raw re.search, NOT httpfeed.first(): first() runs clean(), which strips the very <a>
    # tags this needs to walk — a cleaned block yields zero locations.
    lblock = re.search(r'(?is)<div class="tag-list location-tag-list"[^>]*>(.*?)</div>', body)
    locs = re.findall(r'(?is)<a[^>]+href="[^"]*/location/[^"]*"[^>]*>(.*?)</a>',
                      lblock.group(1) if lblock else body)
    salary = httpfeed.first(body, r'(?is)<div class="salary-range"[^>]*>(.*?)</div>')
    salary = re.sub(r'(?i)^\s*salary:\s*', '', salary).strip()
    if salary.lower() in ("competitive", "undisclosed", "doe", "n/a", "-"):
        salary = ""
    return {
        "id": jid,
        "url": url.split("?")[0],
        "title": title,
        "company": company or httpfeed.clean(title_block.split(" at ")[-1]),
        "location": ", ".join(httpfeed.clean(x) for x in locs if httpfeed.clean(x)),
        "salary": salary,
        "created": httpfeed.first(body, r'(?is)<time class="entry-date"[^>]*>(.*?)</time>'),
        "ats_hint": "",                  # resolves per-studio on the JD
        "source": "dezeen",
    }


BOARD = httpfeed.Board(
    board="dezeen", name="Dezeen Jobs", base=BASE,
    search_url=search_url, parse=parse, normalize=normalize,
    seen_pattern=r"dezeenjobs\.com/job/[a-z0-9-]*?(\d+)",
    fetch="cfx",                 # Cloudflare managed challenge — HTTP cannot pass. See docstring.
    per_page=PER_PAGE, default_where="", render_wait=8,   # ~5s for the CF challenge to clear
    apply_hint=("Iterate each .url; apply is off-site per studio on the JD (no Dezeen "
                "account). Board is browser-only — Cloudflare challenges plain HTTP."),
)

if __name__ == "__main__":
    sys.exit(httpfeed.main(BOARD))
