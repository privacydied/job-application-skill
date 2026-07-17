#!/usr/bin/env python3
"""feed.py — enumerate job postings from NHS Jobs (jobs.nhs.uk).

The central NHS recruitment portal — the single biggest source for gov/health digital,
service-design, UX and IT-support roles (strong fit given NHS COVID-19 App experience).
Server-rendered with clean `data-test` hooks (curl-reachable, but sourced via camofox for
consistency). Applications either complete ON jobs.nhs.uk or hand off to a trust's **Trac**
(trac.jobs) system — see sites/jobs.nhs.uk/NOTES.md.

Each result carries `data-test="search-result-*"` hooks (verified live 2026-07-17):
  title    [data-test=search-result-job-title]   (a[href] `/candidate/jobadvert/<REF>` + text)
  location [data-test=search-result-location]     (firstChild = EMPLOYER, remainder = location)
  salary   [data-test=search-result-salary]       ("Salary: £X to £Y a year")
  jobType  [data-test=search-result-jobType]      ("Contract type: Permanent")
  closing  [data-test=search-result-closingDate]

REF is the trust/vacancy code, e.g. `C9289-SC-388`, `M0048-26-0366`. Search URLs:
`/candidate/search/results?keyword=<terms>&location=<loc>&distance=<miles>`.

Returns the shared posting shape; pipe to precheck.py.

Usage:
    CFX_KEY=... CFX_TAB=... python3 feed.py [--nav "<nhs search url>"]
        [--what "<query>"] [--location "<city>"] [--distance N] [--pages N] [--all] [--force]
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

BOARD = "nhs"
BASE = "https://www.jobs.nhs.uk"
DEFAULT_LOCATION = "London"
TRACKER = os.path.join(_here, "..", "..", "..", "application-tracker.csv")


def load_seen_ids():
    return load_seen(r"jobs\.nhs\.uk/candidate/jobadvert/([A-Za-z0-9-]+)", tracker=TRACKER)


def _search_url(what, location=DEFAULT_LOCATION, distance=10):
    return f"{BASE}/candidate/search/results?" + urlencode(
        {"keyword": what, "location": location or DEFAULT_LOCATION, "distance": distance})


def _query_from_nav(nav):
    """`keyword` param (case-insensitive) for the cooldown key."""
    try:
        for k, v in parse_qs(urlparse(nav).query).items():
            if k.lower() == "keyword" and v:
                return v[0].replace("+", " ").strip()
    except Exception:
        return ""
    return ""


def _job_ref(href):
    """`/candidate/jobadvert/C9289-SC-388?keyword=x` -> `C9289-SC-388`."""
    m = re.search(r"/candidate/jobadvert/([A-Za-z0-9][A-Za-z0-9-]+)", href or "")
    return m.group(1) if m else ""


def _canonical_url(href):
    if not href:
        return ""
    href = href.split("?")[0].split("#")[0]
    return href if href.startswith("http") else BASE + href


def _clean_salary(s):
    return re.sub(r"^\s*Salary:\s*", "", (s or "")).strip()


ENUM = r"""
(() => {
  const out = [];
  const seen = new Set();
  for (const t of document.querySelectorAll('[data-test="search-result-job-title"]')) {
    const a = t.matches('a') ? t : t.querySelector('a');
    const href = a ? (a.getAttribute('href') || '') : '';
    const m = href.match(/\/candidate\/jobadvert\/([A-Za-z0-9][A-Za-z0-9-]+)/);
    if (!m || seen.has(m[1])) continue;
    seen.add(m[1]);
    // card = nearest ancestor holding the location hook
    let card = t;
    for (let i = 0; i < 7; i++) {
      if (card.querySelector('[data-test="search-result-location"]')) break;
      if (!card.parentElement) break;
      card = card.parentElement;
    }
    const locEl = card.querySelector('[data-test="search-result-location"]');
    let employer = '', location = '';
    if (locEl) {
      const first = locEl.firstElementChild;
      employer = first ? (first.textContent||'').replace(/\s+/g,' ').trim() : '';
      const full = (locEl.textContent||'').replace(/\s+/g,' ').trim();
      location = employer && full.startsWith(employer) ? full.slice(employer.length).trim() : full;
    }
    const q = s => { const e = card.querySelector(s); return e ? (e.textContent||'').replace(/\s+/g,' ').trim() : ''; };
    out.push({
      href,
      title: (a ? a.textContent : t.textContent || '').replace(/\s+/g,' ').trim(),
      employer, location,
      salary: q('[data-test="search-result-salary"]'),
    });
  }
  return out;
})()
"""


def _normalize(raw):
    """Map one ENUM row to the shared posting shape. Pure — unit-tested."""
    ref = _job_ref(raw.get("href"))
    if not ref:
        return None
    return {
        "id": ref,
        "url": _canonical_url(raw.get("href")),
        "title": (raw.get("title") or "").strip(),
        "company": (raw.get("employer") or "").strip(),
        "location": (raw.get("location") or "").strip(),
        "salary": _clean_salary(raw.get("salary")),
        "ats_hint": "nhs-jobs",  # apply on jobs.nhs.uk OR hand-off to a trust's Trac — see NOTES
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
    distance = opt("--distance", "10")
    try:
        pages = max(1, int(opt("--pages", "1")))
    except ValueError:
        pages = 1
    force = "--force" in args or "--all" in args

    if not nav:
        if not what:
            print("ERROR: pass --nav <url> or --what \"<terms>\"")
            return 2
        nav = _search_url(what, location, distance)

    query = _query_from_nav(nav) or board_cooldown.query_from_url(nav) or what or ""
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
        print(f"\n{len(jobs)} FRESH NHS Jobs ({filtered} already tracked, filtered). "
              f"Iterate each .url; apply on jobs.nhs.uk or via the trust's Trac (see NOTES).", file=sys.stderr)
    else:
        marked = ""
        if track and all_jobs:
            hrs = board_cooldown.adaptive_hours(BOARD, query)
            until = board_cooldown.mark(BOARD, query, hrs)
            marked = f" Auto-marked {BOARD}/{query!r} cooldown until {until} ({hrs:.0f}h)."
        print(f"\nEXHAUSTED: all {len(all_jobs)} NHS results for {query!r} already "
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
