#!/usr/bin/env python3
"""feed.py — enumerate job postings from Reed.co.uk search results.

Reed is the largest UK aggregator, guest-browsable (no login to search/view), with light
anti-bot — distinct employer inventory vs Indeed, strong for BA/analyst/junior-design/
digital roles. Runs through camofox like the other scrapers.

Every result is an `article[data-qa=job-card]` carrying `data-id="job<ID>"`; the canonical
posting URL is `https://www.reed.co.uk/jobs/<slug>/<ID>`. Selectors below were verified
against Reed's live DOM (2026-07-15) — all stable `data-qa` hooks:
  title   a[data-qa=job-card-title]         (href + text)
  company [data-qa=job-posted-by]           ("<date> by <Company>")
  salary  [data-qa=job-metadata-salary]
  location[data-qa=job-metadata-location]
  easyApply badge  [data-qa^=badge-][data-qa*=easyApply]   → ats_hint "reed-easyapply"

Returns a de-duplicated JSON list of {id, url, title, company, location, salary, ats_hint,
source} — same shape as the other feeds; pipe to precheck.py.

Usage:
    CFX_KEY=... CFX_TAB=... python3 feed.py [--nav "<reed search url>"]
        [--what "<query>"] [--location "<city>"] [--pages N] [--all] [--force]
  --nav       navigate to this Reed search URL first. Without it, --what builds one.
  --what      search terms → builds `…/jobs?keywords=<q>&location=<loc>&sortby=DisplayDate`.
  --location  default London (Jane works London or fully-remote only).
  --pages     follow `&pageno=N` up to N pages (default 1).
  --all       include already-tracked postings + bypass the cooldown gate.
  --force     bypass the cooldown gate only.
"""
import json
import os
import re
import sys
import time
from urllib.parse import urlencode, urlparse, parse_qs

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_here, "..", "..", "_common", "scripts"))
import cfx  # noqa: E402
import board_cooldown  # noqa: E402
from precheck import load_seen  # noqa: E402

BOARD = "reed"
BASE = "https://www.reed.co.uk"
DEFAULT_LOCATION = "London"
TRACKER = os.path.join(_here, "..", "..", "..", "application-tracker.csv")


def load_seen_ids():
    """Reed posting ids already in application-tracker.csv (via the shared scan)."""
    return load_seen(r"reed\.co\.uk/jobs/[^/,\s]+/([0-9]+)", tracker=TRACKER)


def _search_url(what, location=DEFAULT_LOCATION):
    return f"{BASE}/jobs?" + urlencode(
        {"keywords": what, "location": location or DEFAULT_LOCATION, "sortby": "DisplayDate"})


def _job_id(data_id):
    """`data-id="job57081009"` → `57081009`."""
    return re.sub(r"^job", "", str(data_id or "")).strip()


def _company_from_posted_by(text):
    """`"2 July by Pharmica"` → `"Pharmica"`. Falls back to the whole string if no ' by '."""
    t = (text or "").replace("\n", " ").strip()
    m = re.search(r"\bby\s+(.+?)\s*$", t)
    return (m.group(1) if m else t).strip()


def _canonical_url(href):
    if not href:
        return ""
    href = href.split("?")[0].split("#")[0]
    return href if href.startswith("http") else BASE + href


ENUM = r"""
(() => {
  const out = [];
  for (const card of document.querySelectorAll('article[data-qa=job-card]')) {
    const a = card.querySelector('a[data-qa=job-card-title]');
    if (!a) continue;
    const q = s => { const e = card.querySelector(s); return e ? (e.textContent||'').replace(/\s+/g,' ').trim() : ''; };
    const easy = !!card.querySelector('[data-qa^=badge-][data-qa*=easyApply]');
    out.push({
      dataId: card.getAttribute('data-id') || '',
      href: a.getAttribute('href') || '',
      title: (a.textContent||'').replace(/\s+/g,' ').trim(),
      postedBy: q('[data-qa=job-posted-by]'),
      salary: q('[data-qa=job-metadata-salary]'),
      location: q('[data-qa=job-metadata-location]'),
      easyApply: easy,
    });
  }
  return out;
})()
"""


def _normalize(raw):
    """Map one ENUM row to the shared posting shape. Pure — unit-tested."""
    jid = _job_id(raw.get("dataId"))
    if not jid:
        return None
    return {
        "id": jid,
        "url": _canonical_url(raw.get("href")),
        "title": (raw.get("title") or "").strip(),
        "company": _company_from_posted_by(raw.get("postedBy")),
        "location": (raw.get("location") or "").strip(),
        "salary": (raw.get("salary") or "").strip(),
        "ats_hint": "reed-easyapply" if raw.get("easyApply") else "",
        "source": BOARD,
    }


def _enum_page(pool):
    rows = cfx.evaluate(ENUM)
    if isinstance(rows, list):
        for r in rows:
            n = _normalize(r)
            if n and n["id"] not in pool:
                pool[n["id"]] = n


def main():
    args = sys.argv[1:]

    def opt(name, default=None):
        return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else default

    nav = opt("--nav")
    what = opt("--what")
    location = opt("--location", DEFAULT_LOCATION)
    try:
        pages = max(1, int(opt("--pages", "1")))
    except ValueError:
        pages = 1
    force = "--force" in args or "--all" in args

    if not nav:
        if not what:
            print("ERROR: pass --nav <url> or --what \"<terms>\"")
            return 2
        nav = _search_url(what, location)

    # Cooldown key from the search query (keywords/q), same as the other feeds.
    query = board_cooldown.query_from_url(nav) or what or ""
    if query and not force:
        rem = board_cooldown.remaining_hours(BOARD, query)
        if rem > 0:
            print("[]")
            print(f"\nCOOLDOWN: {BOARD}/{query!r} confirmed exhausted ({rem:.1f}h remaining). "
                  f"Skipped WITHOUT re-fetching. --force to override.", file=sys.stderr)
            return 1

    pool = {}
    try:
        for p in range(pages):
            page_url = nav if p == 0 else (nav + ("&" if "?" in nav else "?") + f"pageno={p + 1}")
            cfx.navigate(page_url)
            time.sleep(4)
            before = len(pool)
            _enum_page(pool)
            if p > 0 and len(pool) == before:
                break
    except cfx.CfxError as e:
        print(f"ERROR nav: {e}")
        return 2

    all_jobs = list(pool.values())
    if "--all" in args:
        jobs = all_jobs
    else:
        seen = load_seen_ids()
        jobs = [j for j in all_jobs if j["id"] not in seen]
    filtered = len(all_jobs) - len(jobs)

    track = bool(query) and "--all" not in args
    if track:
        board_cooldown.record_yield(BOARD, query, len(jobs))
    print(json.dumps(jobs, ensure_ascii=False, indent=2))
    if jobs:
        print(f"\n{len(jobs)} FRESH Reed jobs ({filtered} already tracked, filtered). "
              f"Iterate each .url; 'reed-easyapply' rows apply on-site.", file=sys.stderr)
    else:
        marked = ""
        if track and all_jobs:
            hrs = board_cooldown.adaptive_hours(BOARD, query)
            until = board_cooldown.mark(BOARD, query, hrs)
            marked = f" Auto-marked {BOARD}/{query!r} cooldown until {until} ({hrs:.0f}h)."
        print(f"\nEXHAUSTED: all {len(all_jobs)} Reed results for {query!r} already "
              f"tracked.{marked}", file=sys.stderr)
    return 0 if jobs else 1


if __name__ == "__main__":
    try:
        import stagetimer
        _src = stagetimer.timed("source")
    except Exception:
        import contextlib
        _src = contextlib.nullcontext()
    with _src:
        sys.exit(main())
