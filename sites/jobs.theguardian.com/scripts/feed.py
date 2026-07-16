#!/usr/bin/env python3
"""feed.py — enumerate job postings from Guardian Jobs (jobs.theguardian.com).

Guardian Jobs is a **Madgex**-powered board — the UK board for creative / editorial /
charity / public-sector roles, with distinct employer inventory vs the aggregators and a
**direct on-page apply form** (name + email + CV upload + optional cover message; no
board account needed — see sites/jobs.theguardian.com/NOTES.md). Listing pages are
bot-walled to plain curl, so this feed sources through camofox like the JS boards.

Each result is a `.lister__item` card carrying `a[href^="/job/<ID>/<slug>/"]`. Selectors
verified against live DOM (2026-07-17):
  title    a[href*="/job/"]                    (href + text)
  recruiter[class*=recruiter] / [class*=company]
  salary   [class*=salary]
  location [class*=location]

Returns a de-duplicated JSON list of {id, url, title, company, location, salary, ats_hint,
source} — same shape as the other feeds; pipe to precheck.py.

Usage:
    CFX_KEY=... CFX_TAB=... python3 feed.py [--nav "<guardian search url>"]
        [--what "<query>"] [--pages N] [--all] [--force]
  --nav       navigate to this search URL first. Without it, --what builds one.
  --what      search terms → builds `/jobs/<what>/` (Madgex keyword-in-path search).
  --pages     follow `?page=N` up to N pages (default 1).
  --all       include already-tracked postings + bypass the cooldown gate.
  --force     bypass the cooldown gate only.
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

BOARD = "guardian"
BASE = "https://jobs.theguardian.com"
TRACKER = os.path.join(_here, "..", "..", "..", "application-tracker.csv")


def load_seen_ids():
    """Guardian posting ids already in application-tracker.csv (via the shared scan)."""
    return load_seen(r"jobs\.theguardian\.com/job/(\d{5,})", tracker=TRACKER)


def _slug(text):
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", (text or "").lower())).strip("-")


def _search_url(what):
    # Madgex free-text search is the `Keywords` query param (the `/jobs/<what>/` PATH is a
    # category browse, NOT keyword-filtered — verified live 2026-07-17).
    return f"{BASE}/jobs/?" + urlencode({"Keywords": what})


def _query_from_nav(nav):
    """Cooldown key from a Guardian search URL: the `Keywords` param (case-insensitive —
    board_cooldown.query_from_url only matches lowercase keys), else a `/jobs/<cat>/` browse
    path (`/jobs/design/` -> `design`)."""
    try:
        pr = urlparse(nav)
        qs = parse_qs(pr.query)
        for k, v in qs.items():
            if k.lower() == "keywords" and v:
                return v[0].replace("+", " ").strip()
        parts = [p for p in pr.path.split("/") if p]
    except Exception:
        return ""
    if len(parts) >= 2 and parts[0] == "jobs":
        return parts[1].replace("-", " ").strip()
    return ""


def _job_id(href):
    """`/job/10146125/digital-director/` -> `10146125`."""
    m = re.search(r"/job/(\d{5,})", href or "")
    return m.group(1) if m else ""


def _canonical_url(href):
    if not href:
        return ""
    href = href.strip().split("?")[0].split("#")[0]
    return href if href.startswith("http") else BASE + href


ENUM = r"""
(() => {
  const out = [];
  const seen = new Set();
  for (const card of document.querySelectorAll('.lister__item')) {
    const a = card.querySelector('a[href*="/job/"]');
    if (!a) continue;
    const href = (a.getAttribute('href') || '').trim();
    const idm = href.match(/\/job\/(\d{5,})/);
    if (!idm || seen.has(idm[1])) continue;
    seen.add(idm[1]);
    const q = s => { const e = card.querySelector(s); return e ? (e.textContent||'').replace(/\s+/g,' ').trim() : ''; };
    out.push({
      href,
      title: (a.textContent||'').replace(/\s+/g,' ').trim(),
      company: q('[class*=recruiter]') || q('[class*=company]'),
      salary: q('[class*=salary]'),
      location: q('[class*=location]'),
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
        "ats_hint": "guardian-direct",  # on-page apply form (name/email/CV) — see NOTES.md
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
        print(f"\n{len(jobs)} FRESH Guardian jobs ({filtered} already tracked, filtered). "
              f"Iterate each .url; 'guardian-direct' rows apply on-page (name/email/CV).", file=sys.stderr)
    else:
        marked = ""
        if track and all_jobs:
            hrs = board_cooldown.adaptive_hours(BOARD, query)
            until = board_cooldown.mark(BOARD, query, hrs)
            marked = f" Auto-marked {BOARD}/{query!r} cooldown until {until} ({hrs:.0f}h)."
        print(f"\nEXHAUSTED: all {len(all_jobs)} Guardian results for {query!r} already "
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
