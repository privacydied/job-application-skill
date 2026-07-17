#!/usr/bin/env python3
"""feed.py — enumerate job postings from Totaljobs (and StepStone-family siblings).

Totaljobs (totaljobs.com) is a large UK aggregator in the **StepStone family** — the same
"genesis" design system + stable `data-at` DOM hooks also power **CWJobs** (cwjobs.co.uk,
tech/IT — DevOps/cyber/support lanes), **Jobsite** (jobsite.co.uk) and **Milkround**
(milkround.com — early-careers/junior, unusually on-profile for a junior→mid search; same
`data-at`/`job-item` hooks confirmed via plain HTTP 200 on 2026-07-17). One adapter serves
all four: pass `--base https://www.cwjobs.co.uk` (or set TJ_BASE) to retarget. Distinct
employer inventory vs Indeed/Reed; guest-browsable (no login to search/view); server-
rendered (not Cloudflare-walled at the HTTP layer — verified 2026-07-16).

Cooldown board slug is derived from the site host (`totaljobs` / `cwjobs` / `jobsite` /
`milkround`) so each sibling cools independently and loop-preflight.py's searches.csv
`board` column agrees with what the feed records in board-cooldown.csv.

Every result is `[data-at="job-item"]`; the canonical posting URL is
`https://www.totaljobs.com/job/<slug>/<company-slug>-job<ID>`. Selectors (verified against
live DOM 2026-07-17 — all stable `data-at` hooks):
  title    a[data-at=job-item-title]        (href + text)
  company  [data-at=job-item-company-name]
  salary   [data-at=job-item-salary-info]
  location [data-at=job-item-location]
  posted   [data-at=job-item-timeago]

Search URLs are PATH-based: `/jobs/<what>/in-<location>` (not `?keywords=`), so the cooldown
key is parsed from the path here — `_query_from_nav()` — and matches the searches.csv `query`
column after board_cooldown.norm() (hyphens→spaces→underscores both sides).

Returns a de-duplicated JSON list of {id, url, title, company, location, salary, ats_hint,
source} — same shape as the other feeds; pipe to precheck.py.

Usage:
    CFX_KEY=... CFX_TAB=... python3 feed.py [--nav "<totaljobs search url>"]
        [--what "<query>"] [--location "<city>"] [--base <site>] [--pages N] [--all] [--force]
  --nav       navigate to this search URL first. Without it, --what builds one.
  --what      search terms → builds `<base>/jobs/<what>/in-<location>`.
  --location  default London (Jane works London or fully-remote only).
  --base      site root (default https://www.totaljobs.com; TJ_BASE env override) — set to
              a sibling (cwjobs.co.uk / jobsite.co.uk) to source it with the same adapter.
  --pages     follow `?page=N` up to N pages (default 1).
  --all       include already-tracked postings + bypass the cooldown gate.
  --force     bypass the cooldown gate only.
"""
import json
import os
import re
import sys
import time
from urllib.parse import quote, urlparse

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_here, "..", "..", "_common", "scripts"))
import cfx  # noqa: E402
import board_cooldown  # noqa: E402
from precheck import load_seen  # noqa: E402

BOARD = "totaljobs"
BASE = os.environ.get("TJ_BASE", "https://www.totaljobs.com").rstrip("/")
DEFAULT_LOCATION = "London"
TRACKER = os.path.join(_here, "..", "..", "..", "application-tracker.csv")


def load_seen_ids(base=BASE):
    """Totaljobs posting ids already in application-tracker.csv (via the shared scan).
    Host-agnostic so a sibling base (cwjobs/jobsite) is de-duped against its own rows too."""
    return load_seen(r"/job/[^,\s]*?-job(\d{6,})", tracker=TRACKER)


def _board_from_base(base):
    """Cooldown board slug from the site host, so siblings cool independently and the
    slug matches the searches.csv `board` column (totaljobs|cwjobs|jobsite|milkround)."""
    host = urlparse(base).netloc or base
    for slug in ("cwjobs", "jobsite", "milkround"):
        if slug in host:
            return slug
    return BOARD


def _slug(text):
    """`"UX Designer"` -> `"ux-designer"` for the path-based search URL."""
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", (text or "").lower())).strip("-")


def _search_url(what, location=DEFAULT_LOCATION, base=BASE):
    loc = location or DEFAULT_LOCATION
    return f"{base}/jobs/{_slug(what)}/in-{_slug(loc)}"


def _query_from_nav(nav):
    """Extract the free-text query from a PATH-based Totaljobs search URL for the cooldown key.
    `/jobs/ux-designer/in-london` -> `ux designer`. Returns '' if not a /jobs/<what>/ path."""
    try:
        parts = [p for p in urlparse(nav).path.split("/") if p]
    except Exception:
        return ""
    if len(parts) >= 2 and parts[0] == "jobs":
        return parts[1].replace("-", " ").strip()
    return ""


def _job_id(href):
    """`/job/ux-designer/triad-group-plc-job107681590` -> `107681590`."""
    m = re.search(r"-job(\d{6,})", href or "")
    return m.group(1) if m else ""


def _canonical_url(href, base=BASE):
    if not href:
        return ""
    href = href.split("?")[0].split("#")[0]
    return href if href.startswith("http") else base + href


ENUM = r"""
(() => {
  const out = [];
  for (const card of document.querySelectorAll('[data-at="job-item"]')) {
    const a = card.querySelector('a[data-at="job-item-title"]');
    if (!a) continue;
    const q = s => { const e = card.querySelector(s); return e ? (e.textContent||'').replace(/\s+/g,' ').trim() : ''; };
    out.push({
      href: a.getAttribute('href') || '',
      title: (a.textContent||'').replace(/\s+/g,' ').trim(),
      company: q('[data-at="job-item-company-name"]'),
      salary: q('[data-at="job-item-salary-info"]'),
      location: q('[data-at="job-item-location"]'),
      posted: q('[data-at="job-item-timeago"]'),
    });
  }
  return out;
})()
"""


def _normalize(raw, base=BASE):
    """Map one ENUM row to the shared posting shape. Pure — unit-tested."""
    jid = _job_id(raw.get("href"))
    if not jid:
        return None
    return {
        "id": jid,
        "url": _canonical_url(raw.get("href"), base),
        "title": (raw.get("title") or "").strip(),
        "company": (raw.get("company") or "").strip(),
        "location": (raw.get("location") or "").strip(),
        "salary": (raw.get("salary") or "").strip(),
        "ats_hint": "",  # Totaljobs "Apply" resolves per-listing (on-site quick-apply OR external ATS)
        "source": _board_from_base(base),
    }


def _enum_page(pool, base=BASE):
    rows = cfx.evaluate(ENUM)
    if isinstance(rows, list):
        for r in rows:
            n = _normalize(r, base)
            if n and n["id"] not in pool:
                pool[n["id"]] = n


def main():
    args = sys.argv[1:]

    def opt(name, default=None):
        return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else default

    base = (opt("--base") or BASE).rstrip("/")
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
        nav = _search_url(what, location, base)
    else:
        # Derive the site root from the nav host so a sibling (cwjobs/jobsite) resolves its own
        # relative hrefs correctly even when only --nav is passed (pipeline's path).
        pr = urlparse(nav)
        if pr.scheme and pr.netloc:
            base = f"{pr.scheme}://{pr.netloc}"

    board = _board_from_base(base)

    # Cooldown key: query param first (siblings may use it), else parse the /jobs/<what>/ path.
    query = board_cooldown.query_from_url(nav) or _query_from_nav(nav) or what or ""
    if query and not force:
        rem = board_cooldown.remaining_hours(board, query)
        if rem > 0:
            print("[]")
            print(f"\nCOOLDOWN: {board}/{query!r} confirmed exhausted ({rem:.1f}h remaining). "
                  f"Skipped WITHOUT re-fetching. --force to override.", file=sys.stderr)
            return 1

    pool = {}
    try:
        for p in range(pages):
            page_url = nav if p == 0 else (nav + ("&" if "?" in nav else "?") + f"page={p + 1}")
            cfx.navigate(page_url)
            time.sleep(4)
            before = len(pool)
            _enum_page(pool, base)
            if p > 0 and len(pool) == before:
                break
    except cfx.CfxError as e:
        print(f"ERROR nav: {e}")
        return 2

    all_jobs = list(pool.values())
    if "--all" in args:
        jobs = all_jobs
    else:
        seen = load_seen_ids(base)
        jobs = [j for j in all_jobs if j["id"] not in seen]
    filtered = len(all_jobs) - len(jobs)

    track = bool(query) and "--all" not in args
    if track:
        board_cooldown.record_yield(BOARD, query, len(jobs))
    print(json.dumps(jobs, ensure_ascii=False, indent=2))
    if jobs:
        print(f"\n{len(jobs)} FRESH Totaljobs jobs ({filtered} already tracked, filtered). "
              f"Iterate each .url; 'Apply' resolves per-listing (on-site or external ATS).", file=sys.stderr)
    else:
        marked = ""
        if track and all_jobs:
            hrs = board_cooldown.adaptive_hours(BOARD, query)
            until = board_cooldown.mark(BOARD, query, hrs)
            marked = f" Auto-marked {BOARD}/{query!r} cooldown until {until} ({hrs:.0f}h)."
        print(f"\nEXHAUSTED: all {len(all_jobs)} Totaljobs results for {query!r} already "
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
