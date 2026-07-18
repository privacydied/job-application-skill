#!/usr/bin/env python3
"""feed.py — enumerate vacancies from the applicationtrack.com (VacancyFiller) job board.

ONE adapter serves both UK intelligence-agency tenants (see sites/applicationtrack.com/NOTES.md):
  MI5  (Security Service)  — appcentre-a18, board `.../appcentre-a18/candidate/jobboard/vacancy/1`
  MI6  (SIS)               — appcentre-2,   board `.../appcentre-2/brand-2/candidate/jobboard/vacancy/2`
The org (company/source) is inferred from the `appcentre-<id>` in the nav URL.

Applying is ACCOUNT-gated (sign in per tenant) and filled from the applicant's legitimate
profile with the applicant watching via noVNC + giving the final go before submit — same as
any other application (see NOTES.md "Applying"). `ats_hint` is `applicationtrack` (login gate).

The board is a server-rendered `<table>` (bot-walled to plain curl → sourced via camofox).
Each `<tr>` with an `a[href*="/opp/<ref>-<slug>/"]` link carries cells: Title | Location |
Department | Closing Date (verified live 2026-07-17). Ref (the numeric id) comes from the href.

Usage:
    CFX_KEY=... CFX_TAB=... python3 feed.py [--tenant mi5|mi6] [--nav "<board url>"]
        [--depts "Technology Roles,Cyber,Engineering"] [--all] [--force]
  --tenant   mi5 | mi6 (default mi6) — builds the board URL if --nav is omitted.
  --nav      full job-board URL (overrides --tenant; org inferred from its appcentre).
  --depts    comma list — keep only these Departments (default: all; screen downstream).
"""
import json
import os
import re
import sys
import time

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_here, "..", "..", "_common", "scripts"))
import cfx  # noqa: E402
import board_cooldown  # noqa: E402
from precheck import load_seen  # noqa: E402

BASE = "https://recruitmentservices.applicationtrack.com"
TRACKER = os.path.join(_here, "..", "..", "..", "application-tracker.csv")

TENANTS = {
    "mi5": {"board": f"{BASE}/vx/lang-en-GB/mobile-0/appcentre-a18/candidate/jobboard/vacancy/1",
            "appcentre": "appcentre-a18", "company": "MI5 (Security Service)", "source": "mi5"},
    "mi6": {"board": f"{BASE}/vx/lang-en-GB/mobile-0/appcentre-2/brand-2/candidate/jobboard/vacancy/2",
            "appcentre": "appcentre-2", "company": "MI6 (SIS)", "source": "mi6"},
}


def _org_from_url(url):
    """Infer (company, source) from the appcentre in the board URL. Defaults to a generic label."""
    for t in TENANTS.values():
        if t["appcentre"] in (url or ""):
            return t["company"], t["source"]
    m = re.search(r"appcentre-([a-z0-9]+)", url or "")
    tag = m.group(1) if m else "unknown"
    return f"applicationtrack/{tag}", f"applicationtrack-{tag}"


def load_seen_ids():
    return load_seen(r"applicationtrack\.com/[^,\s]*?/opp/(\d+)-", tracker=TRACKER)


def _ref(href):
    """`.../opp/3793-Technical-Risk-Adviser-Ref-3793/en-GB` -> `3793`."""
    m = re.search(r"/opp/(\d+)-", href or "")
    return m.group(1) if m else ""


def _canonical_url(href):
    if not href:
        return ""
    href = href.split("#")[0]
    if href.startswith("http"):
        return href.split("?")[0]
    return BASE + href.split("?")[0]


ENUM = r"""
(() => {
  const out = [];
  const seen = new Set();
  for (const a of document.querySelectorAll('a[href*="/opp/"]')) {
    const href = a.getAttribute('href') || '';
    const m = href.match(/\/opp\/(\d+)-/);
    if (!m || seen.has(m[1])) continue;
    const title = (a.textContent || '').replace(/\s+/g, ' ').trim();
    if (!title || !/Ref\.?\s*\d/i.test(title)) continue;   // skip nav/non-vacancy opp links
    seen.add(m[1]);
    const row = a.closest('tr');
    const cells = row ? [...row.querySelectorAll('td,th')].map(c => (c.textContent||'').replace(/\s+/g,' ').trim()) : [];
    out.push({
      href, title,
      location: cells[1] || '',
      department: cells[2] || '',
      closing: cells[3] || '',
    });
  }
  return out;
})()
"""


def _normalize(raw, company, source):
    """Map one ENUM row to the shared posting shape (+ department/closing extras). Pure — unit-tested."""
    ref = _ref(raw.get("href"))
    if not ref:
        return None
    return {
        "id": ref,
        "url": _canonical_url(raw.get("href")),
        "title": (raw.get("title") or "").strip(),
        "company": company,
        "location": (raw.get("location") or "").strip(),
        "salary": "",  # not on the board; on the detail page
        "ats_hint": "applicationtrack",  # account-gated login (see NOTES "Applying")
        "source": source,
        "department": (raw.get("department") or "").strip(),
        "closing": (raw.get("closing") or "").strip(),
    }


def main():
    args = sys.argv[1:]

    def opt(name, default=None):
        return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else default

    nav = opt("--nav")
    tenant = (opt("--tenant", "mi6") or "mi6").lower()
    if not nav:
        if tenant not in TENANTS:
            print(f"ERROR: --tenant must be one of {list(TENANTS)} (or pass --nav)")
            return 2
        nav = TENANTS[tenant]["board"]
    company, source = _org_from_url(nav)
    depts = [d.strip().lower() for d in (opt("--depts", "") or "").split(",") if d.strip()]
    force = "--force" in args or "--all" in args

    # cooldown key = the org/source (one board per org)
    query = source
    if query and not force:
        rem = board_cooldown.remaining_hours(source, query)
        if rem > 0:
            print("[]")
            print(f"\nCOOLDOWN: {source}/{query!r} confirmed exhausted ({rem:.1f}h remaining). "
                  f"--force to override.", file=sys.stderr)
            return 1

    try:
        cfx.navigate(nav)
        time.sleep(5)
        rows = cfx.evaluate(ENUM)
    except cfx.CfxError as e:
        print(f"ERROR nav: {e}")
        return 2

    pool = {}
    if isinstance(rows, list):
        for r in rows:
            n = _normalize(r, company, source)
            if not n:
                continue
            if depts and n["department"].lower() not in depts:
                continue
            pool[n["id"]] = n

    all_jobs = list(pool.values())
    if "--all" in args:
        jobs = all_jobs
    else:
        seen = load_seen_ids()
        jobs = [j for j in all_jobs if j["id"] not in seen]
    filtered = len(all_jobs) - len(jobs)

    track = "--all" not in args
    if track:
        board_cooldown.record_yield(source, query, len(jobs))
    print(json.dumps(jobs, ensure_ascii=False, indent=2))
    if jobs:
        print(f"\n{len(jobs)} FRESH {company} vacancies ({filtered} already tracked). "
              f"Apply is account-gated; filled from the profile with noVNC oversight "
              f"(see sites/applicationtrack.com/NOTES.md).", file=sys.stderr)
    else:
        marked = ""
        if track and all_jobs:
            hrs = board_cooldown.adaptive_hours(source, query)
            until = board_cooldown.mark(source, query, hrs)
            marked = f" Auto-marked {source} cooldown until {until} ({hrs:.0f}h)."
        print(f"\nEXHAUSTED: all {len(all_jobs)} {company} vacancies already tracked.{marked}", file=sys.stderr)
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
