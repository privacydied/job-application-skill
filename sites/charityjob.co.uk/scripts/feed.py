#!/usr/bin/env python3
"""feed.py — enumerate job postings from CharityJob (charityjob.co.uk).

The biggest UK charity/third-sector board — the dedicated source for the charity
digital/web/comms lane (family #14). Listing pages are JS-rendered and bot-walled to plain
curl, so this sources through camofox. No board account needed to search/view.

Each result is `article.job-card-wrapper` with a title link `/jobs/<charity>/<role>/<ID>`
(ID = the numeric tail). Selectors verified against live DOM (2026-07-17):
  title   a[href*="/jobs/.../<id>"]   (link text)
  org     .organisation              ("<Charity>, <Location> (<mode>)" — split on first comma)
  posted  .posted-item

Free-text search is the `?Keywords=` query param: `/jobs/?Keywords=<terms>`; category browses
like `/digital-jobs` also work. Returns the shared posting shape; pipe to precheck.py.

Usage:
    CFX_KEY=... CFX_TAB=... python3 feed.py [--nav "<charityjob search url>"]
        [--what "<query>"] [--pages N] [--all] [--force]
"""
import json
import os
import re
import sys
import time
from urllib.parse import urlparse, urlencode, parse_qs

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_here, "..", "..", "_common", "scripts"))
import cfx  # noqa: E402
import board_cooldown  # noqa: E402
from precheck import load_seen  # noqa: E402

BOARD = "charityjob"
BASE = "https://www.charityjob.co.uk"
TRACKER = os.path.join(_here, "..", "..", "..", "application-tracker.csv")


def load_seen_ids():
    return load_seen(r"charityjob\.co\.uk/jobs/[^,\s]+?/(\d{5,})", tracker=TRACKER)


def _search_url(what):
    return f"{BASE}/jobs/?" + urlencode({"Keywords": what})


def _query_from_nav(nav):
    """Keywords param (case-insensitive), else a `/<cat>-jobs` browse path → `<cat>`."""
    try:
        pr = urlparse(nav)
        for k, v in parse_qs(pr.query).items():
            if k.lower() == "keywords" and v:
                return v[0].replace("+", " ").strip()
        m = re.match(r"/([a-z0-9-]+)-jobs/?$", pr.path)
        if m:
            return m.group(1).replace("-", " ")
    except Exception:
        return ""
    return ""


def _job_id(href):
    """`/jobs/anna-freud/website-and-digital-marketing-officer/1076288` -> `1076288`."""
    m = re.search(r"/jobs/[^/]+/[^/]+/(\d{5,})", href or "")
    return m.group(1) if m else ""


def _canonical_url(href):
    if not href:
        return ""
    href = href.strip().split("?")[0].split("#")[0]
    return href if href.startswith("http") else BASE + href


def _split_org(text):
    """`"Anna Freud, London (Hybrid)"` -> ("Anna Freud", "London (Hybrid)")."""
    t = (text or "").replace("\n", " ").strip()
    if "," in t:
        c, loc = t.split(",", 1)
        return c.strip(), loc.strip()
    return t, ""


ENUM = r"""
(() => {
  const out = [];
  const seen = new Set();
  for (const card of document.querySelectorAll('article.job-card-wrapper')) {
    const a = [...card.querySelectorAll('a[href]')].find(x => /\/jobs\/[^/]+\/[^/]+\/\d{5,}/.test(x.getAttribute('href')||''));
    if (!a) continue;
    const href = (a.getAttribute('href') || '').trim();
    const idm = href.match(/\/jobs\/[^/]+\/[^/]+\/(\d{5,})/);
    if (!idm || seen.has(idm[1])) continue;
    seen.add(idm[1]);
    const q = s => { const e = card.querySelector(s); return e ? (e.textContent||'').replace(/\s+/g,' ').trim() : ''; };
    out.push({
      href,
      title: (a.textContent||'').replace(/\s+/g,' ').trim(),
      org: q('.organisation'),
      salary: q('[class*=salary i]'),
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
    company, location = _split_org(raw.get("org"))
    return {
        "id": jid,
        "url": _canonical_url(raw.get("href")),
        "title": (raw.get("title") or "").strip(),
        "company": company,
        "location": location,
        "salary": (raw.get("salary") or "").strip(),
        "ats_hint": "",  # apply resolves per-listing (charity's own ATS or on-site)
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
    try:
        pages = max(1, int(opt("--pages", "1")))
    except ValueError:
        pages = 1
    force = "--force" in args or "--all" in args

    if not nav:
        if not what:
            print("ERROR: pass --nav <url> or --what \"<terms>\"")
            return 2
        nav = _search_url(what)

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
            page_url = nav if p == 0 else (nav + ("&" if "?" in nav else "?") + f"Page={p + 1}")
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
        print(f"\n{len(jobs)} FRESH CharityJob jobs ({filtered} already tracked, filtered). "
              f"Iterate each .url; apply resolves per-listing (charity ATS or on-site).", file=sys.stderr)
    else:
        marked = ""
        if track and all_jobs:
            hrs = board_cooldown.adaptive_hours(BOARD, query)
            until = board_cooldown.mark(BOARD, query, hrs)
            marked = f" Auto-marked {BOARD}/{query!r} cooldown until {until} ({hrs:.0f}h)."
        print(f"\nEXHAUSTED: all {len(all_jobs)} CharityJob results for {query!r} already "
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
