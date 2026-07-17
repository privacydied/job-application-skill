#!/usr/bin/env python3
"""feed.py — enumerate job postings from CV-Library (cv-library.co.uk).

A major UK agency board with strong design/BA/digital inventory (distinct from Reed/Indeed;
Adzuna's design "Apply" links often redirect here). Listing pages are JS-rendered + bot-walled
to plain curl, so this sources through camofox.

Each result is a card carrying stable `data-qa` hooks (verified live 2026-07-17):
  title    a[data-qa^=job-title-link]        (href `/job/<ID>/<slug>` + text)
  company  [data-qa^=company-name-link]
  location [data-qa^=job-card-location]
  salary   [data-qa^=job-card-salary]
  Easy Apply badge → ats_hint "cvlibrary-easyapply" (on-site apply is ACCOUNT + chooser-gated —
  see sites/cv-library.co.uk/../references/cv-library-apply-notes.md; sourcing only here).

Search URLs are SEO path-based: `/<role-slug>-jobs-in-<location>` — the cooldown key is parsed
from that path and matches searches.csv `query` after board_cooldown.norm().

Returns the shared posting shape; pipe to precheck.py.

Usage:
    CFX_KEY=... CFX_TAB=... python3 feed.py [--nav "<cv-library search url>"]
        [--what "<query>"] [--location "<city>"] [--pages N] [--all] [--force]
"""
import json
import os
import re
import sys
import time
from urllib.parse import urlparse

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_here, "..", "..", "_common", "scripts"))
import cfx  # noqa: E402
import board_cooldown  # noqa: E402
from precheck import load_seen  # noqa: E402

BOARD = "cvlibrary"
BASE = "https://www.cv-library.co.uk"
DEFAULT_LOCATION = "London"
TRACKER = os.path.join(_here, "..", "..", "..", "application-tracker.csv")


def load_seen_ids():
    return load_seen(r"cv-library\.co\.uk/job/(\d{6,})", tracker=TRACKER)


def _slug(text):
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", (text or "").lower())).strip("-")


def _search_url(what, location=DEFAULT_LOCATION):
    return f"{BASE}/{_slug(what)}-jobs-in-{_slug(location or DEFAULT_LOCATION)}"


def _query_from_nav(nav):
    """`/ux-designer-jobs-in-london` -> `ux designer` for the cooldown key."""
    try:
        path = urlparse(nav).path
    except Exception:
        return ""
    m = re.match(r"/(.+?)-jobs-in-", path)
    return m.group(1).replace("-", " ").strip() if m else ""


def _job_id(href):
    """`/job/225344741/ux-designer` -> `225344741`."""
    m = re.search(r"/job/(\d{6,})", href or "")
    return m.group(1) if m else ""


def _canonical_url(href):
    if not href:
        return ""
    href = href.split("?")[0].split("#")[0]
    return href if href.startswith("http") else BASE + href


ENUM = r"""
(() => {
  const out = [];
  const seen = new Set();
  for (const a of document.querySelectorAll('a[data-qa^="job-title-link"]')) {
    const href = a.getAttribute('href') || '';
    const idm = href.match(/\/job\/(\d{6,})/);
    if (!idm || seen.has(idm[1])) continue;
    seen.add(idm[1]);
    // card = nearest ancestor that holds the OUTER fields (location+salary) so the whole
    // card is captured — company sits in a smaller inner container, so don't break on it.
    let card = a;
    for (let i = 0; i < 7; i++) {
      if (card.querySelector('[data-qa^="job-card-location"]') &&
          card.querySelector('[data-qa^="job-card-salary"]')) break;
      if (!card.parentElement) break;
      card = card.parentElement;
    }
    const q = s => { const e = card.querySelector(s); return e ? (e.textContent||'').replace(/\s+/g,' ').trim() : ''; };
    out.push({
      href,
      title: (a.textContent||'').replace(/\s+/g,' ').trim(),
      company: q('[data-qa^="company-name-link"]'),
      location: q('[data-qa^="job-card-location"]'),
      salary: q('[data-qa^="job-card-salary"]'),
      easyApply: !!card.querySelector('[data-qa*="easy-apply" i], [class*="easyApply" i]') ||
                 /easy apply/i.test(card.textContent||''),
    });
  }
  return out;
})()
"""


def _normalize(raw):
    """Map one ENUM row to the shared posting shape. Pure — unit-tested."""
    jid = _job_id(raw.get("href"))
    if not jid:
        return None
    return {
        "id": jid,
        "url": _canonical_url(raw.get("href")),
        "title": (raw.get("title") or "").strip(),
        "company": (raw.get("company") or "").strip(),
        "location": (raw.get("location") or "").strip(),
        "salary": (raw.get("salary") or "").strip(),
        "ats_hint": "cvlibrary-easyapply" if raw.get("easyApply") else "",
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

    query = board_cooldown.query_from_url(nav) or _query_from_nav(nav) or what or ""
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
            page_url = nav if p == 0 else (nav + ("&" if "?" in nav else "?") + f"page={p + 1}")
            cfx.navigate(page_url)
            time.sleep(5)
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
        print(f"\n{len(jobs)} FRESH CV-Library jobs ({filtered} already tracked, filtered). "
              f"Iterate each .url; 'cvlibrary-easyapply' rows apply on-site (account-gated).", file=sys.stderr)
    else:
        marked = ""
        if track and all_jobs:
            hrs = board_cooldown.adaptive_hours(BOARD, query)
            until = board_cooldown.mark(BOARD, query, hrs)
            marked = f" Auto-marked {BOARD}/{query!r} cooldown until {until} ({hrs:.0f}h)."
        print(f"\nEXHAUSTED: all {len(all_jobs)} CV-Library results for {query!r} already "
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
