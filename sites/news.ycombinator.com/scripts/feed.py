#!/usr/bin/env python3
"""feed.py — enumerate on-profile roles from the monthly Hacker News "Who is hiring?"
thread via the public, keyless Algolia HN API (feature-roadmap P.3).

WHY. HN's monthly "Ask HN: Who is hiring?" thread is a small, fresh, high-signal pool of
startup roles the aggregators never carry — and it's reachable with NO key and NO browser
through the Algolia HN API. It is a DISCOVERY feed: each row points at the HN comment
permalink; applying means following the comment's own apply link / email (a human/model
step), so rows are sourced/saved, not headlessly submittable.

TWO-PHASE FETCH (both keyless HTTP, verified live 2026-07-17):
  1. Resolve the latest "Who is hiring?" story:
     GET https://hn.algolia.com/api/v1/search_by_date?tags=story,author_whoishiring&hitsPerPage=10
     -> pick the newest hit whose title contains "Who is hiring" (the account also posts
        "Who wants to be hired?" and "Freelancer?" threads — exclude those).
  2. Fetch that story's comment tree:
     GET https://hn.algolia.com/api/v1/items/<storyId>
     -> {children:[{id, author, text(HTML), children:[…]}, …]}. Each TOP-LEVEL child is one
        employer's posting.

FILTER (relevance + location, NOT a title-tier screen — precheck.py owns tiers):
  A top-level comment is kept only when its text mentions REMOTE or LONDON *and* contains an
  on-profile role keyword (design / UX / research / frontend / devops / support / content /
  service design / accessibility). HN postings are free text with no clean title field, so:
    - title  = the matched on-profile role phrase (what precheck screens on),
    - company = the text before the first '|' / 'is hiring' (HN's near-universal convention),
    - the headline first line is kept in `snippet` for context.
  This is deliberately conservative: a comment that doesn't clearly name an on-profile role
  in a remote/London context is dropped rather than guessed at.

Usage:
    python3 feed.py [--what design] [--all] [--force]
  --what further restricts the on-profile keyword set to those containing the term.
"""
import json
import os
import re
import sys

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_here, "..", "..", "_common", "scripts"))
import httpfeed  # noqa: E402

ALGOLIA = "https://hn.algolia.com/api/v1"

# On-profile role phrases (lowercase). First match wins for the row's `title`. Kept in sync
# in SPIRIT with target-roles.md families, but this is a relevance prefilter, not the tier
# screen (precheck.check_title re-screens the chosen title).
ROLE_KEYWORDS = [
    "product designer", "ux designer", "ui designer", "interaction designer",
    "service designer", "content designer", "visual designer", "brand designer",
    "design systems", "design engineer", "ux engineer", "ux researcher",
    "user researcher", "design researcher", "product design", "ux/ui", "ui/ux",
    "front-end", "frontend", "front end", "web developer", "creative technologist",
    "devops", "site reliability", "platform engineer", "it support", "service desk",
    "technical support", "content strategist", "accessibility", "growth",
    "designer", "researcher",  # broad catch-alls last
]
LOC_RE = re.compile(r"\b(remote|london)\b", re.I)


def search_url(what, where, page):
    """Phase 1 URL (page 1 only). The real work — resolving the story + fetching its
    comments — happens in parse(), which is allowed to fetch (board-specific)."""
    if page != 1:
        return ""
    return f"{ALGOLIA}/search_by_date?" + httpfeed.urlencode(
        {"tags": "story,author_whoishiring", "hitsPerPage": 10})


def _latest_hiring_story(text):
    try:
        hits = json.loads(text).get("hits") or []
    except ValueError:
        return None
    for h in hits:  # newest first (search_by_date)
        title = (h.get("title") or "").lower()
        if "who is hiring" in title and "wants to be hired" not in title:
            return h.get("objectID")
    return None


def parse(text, ctx):
    """Phase 1 response -> resolve story id -> phase 2 fetch its comment tree -> return the
    top-level comment dicts (raw rows)."""
    story_id = _latest_hiring_story(text)
    if not story_id:
        return []
    try:
        item = json.loads(httpfeed.http_get(f"{ALGOLIA}/items/{story_id}",
                                             {"Accept": "application/json"}))
    except (httpfeed.FetchError, ValueError):
        return []
    ctx["story_id"] = story_id
    return [c for c in (item.get("children") or []) if isinstance(c, dict) and c.get("text")]


def _match_role(text_l, restrict=""):
    for kw in ROLE_KEYWORDS:
        if restrict and restrict not in kw:
            continue
        if kw in text_l:
            return kw
    return ""


def _company(headline):
    """Best-effort employer name from the HN convention 'Company | role | loc | REMOTE'."""
    h = headline.strip()
    for sep in ("|", " - ", "—", "–", ":"):
        if sep in h:
            cand = h.split(sep, 1)[0].strip()
            if 1 < len(cand) <= 60:
                return cand
    m = re.split(r"\bis hiring\b", h, flags=re.I)
    if m and m[0].strip():
        return m[0].strip()[:60]
    return h[:40]


def normalize(raw, ctx):
    body = httpfeed.strip_html(raw.get("text"))
    if not body:
        return None
    low = body.lower()
    if not LOC_RE.search(low):
        return None
    # A broad sentinel query ("all"/"any"/"remote"/"") means "match ANY on-profile role";
    # a specific one ("design") narrows the keyword set. Keeps the searches.csv cooldown key
    # meaningful without over-restricting the whole thread to a single family.
    restrict = (ctx.get("what") or "").strip().lower()
    if restrict in ("", "all", "any", "remote", "on-profile"):
        restrict = ""
    role = _match_role(low, restrict)
    if not role:
        return None
    cid = str(raw.get("id") or "").strip()
    if not cid:
        return None
    headline = body.split("\n")[0][:200] if "\n" in body else body[:200]
    london = bool(re.search(r"\blondon\b", low))
    return {
        "id": cid,
        "url": f"https://news.ycombinator.com/item?id={cid}",
        # Title = the matched on-profile role (Title-cased) so precheck can tier-screen it.
        "title": role.title(),
        "company": _company(headline),
        "location": "London" if london else "Remote",
        "salary": "",
        "snippet": headline,
        "ats_hint": "external",
        "source": "hn",
    }


BOARD = httpfeed.Board(
    board="hn", name="HN Who is hiring", base="https://news.ycombinator.com",
    search_url=search_url, parse=parse, normalize=normalize,
    seen_pattern=r"news\.ycombinator\.com/item\?id=(\d+)",
    fetch="http", default_where="Remote",
    headers={"Accept": "application/json"},
    sparse=True,  # most comments are off-profile; a thin keep-set is normal, not the end
    apply_hint=("DISCOVERY only: each .url is the HN comment — follow its own apply link / "
                "email to apply (not headlessly submittable). Source/save; apply by hand."),
)

if __name__ == "__main__":
    sys.exit(httpfeed.main(BOARD))
