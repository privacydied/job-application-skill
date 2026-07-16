#!/usr/bin/env python3
"""
feed.py — enumerate vacancies from London Borough of Hackney's careers site.

Forked from the Civil Service Jobs feed PATTERN (enumerate → stable URLs → tracker
dedup → cooldown → eligibility), but the platform is much simpler: Hackney's
`recruitment.hackney.gov.uk` ("Find Yourself in Hackney") is a server-rendered
WordPress site — no login, no session SIDs, no CAPTCHA observed (2026-07-14), and
every vacancy has a STABLE canonical URL:

    https://recruitment.hackney.gov.uk/vacancy/<slug>/

Cards are `article` elements whose class list carries a WP post id (`post-24457`)
plus taxonomy slugs (`directorate-…`, `service-…`, `organisation-…` — note
`…-anonymous-apps`: Hackney runs ANONYMISED applications). Salary + closing date
sit in one bold line on the card ("£37,509 to £41,637 – Closing date: 2 August").
Applying happens OFF-SITE on Lumesse TalentLink (`emea3.recruitmentplatform.com`
`apply-app` links) — a new external ATS; see NOTES.md before first fill.

Returns a de-duplicated JSON list of
{id, url, title, company, location, salary, closes, directorate, service,
 eligibility} — same shape as the other feeds; pipe it to precheck.py. All jobs
are Hackney (London) borough roles, so `location` is fixed "Hackney, London"
(precheck's London rule keeps them; the JD states the working pattern).

Usage:
    CFX_KEY=... CFX_TAB=... python3 feed.py [--nav "<job-search url>"] [--pages N] [--all] [--force]

  --nav    navigate to this search URL first (default flow: the `hackney` row's nav
           in searches.csv — https://recruitment.hackney.gov.uk/job-search/; a
           `?directorate=…` filter URL also works). Without it, enumerates the
           results page the tab is already on.
  --pages  follow /job-search/page/N/ up to N pages (default 3; the site 404s past
           the last page, which just ends enumeration early).
  --all    include already-tracked vacancies and bypass the cooldown gate.
  --force  bypass the cooldown gate only.

Cooldown key is the fixed slug `all` (BOARD `hackney`) — council boards are small
(tens of postings) so the loop sources everything and lets precheck do the
screening; keep the key in sync with searches.csv's `hackney` row.
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
from precheck import load_seen  # noqa: E402  (shared tracker-dedup, was duplicated per feed)
try:
    import check_title  # noqa: E402
except Exception:
    check_title = None

BOARD = "hackney"
QUERY = "all"
BASE = "https://recruitment.hackney.gov.uk"

TRACKER = os.path.join(_here, "..", "..", "..", "application-tracker.csv")


def load_seen_slugs():
    """Vacancy slugs already in application-tracker.csv, via the shared
    `precheck.load_seen` (csv-quoting-proof regex scan; was duplicated per feed)."""
    return load_seen(r"recruitment\.hackney\.gov\.uk/vacancy/([a-z0-9-]+)", tracker=TRACKER)


ENUM = r"""
(() => {
  const out = [];
  for (const card of document.querySelectorAll('article[id^=post-], article.vacancy, article[class*=vacancy]')) {
    const a = card.querySelector('.entry-title a, h2 a');
    if (!a || !/\/vacancy\//.test(a.href)) continue;
    const cls = (card.getAttribute('class') || '') + ' ' + (card.id || '');
    const tax = p => { const m = cls.match(new RegExp(p + '-([a-z0-9-]+)')); return m ? m[1].replace(/-/g, ' ') : ''; };
    const bold = card.querySelector('p.font-weight-bold, .entry-header p');
    const line = bold ? bold.innerText.replace(/\s+/g, ' ').trim() : '';
    const salary = (line.match(/£[\d,]+(?:\s*to\s*£[\d,]+)?/) || [''])[0];
    const closes = (line.match(/Closing date:\s*(.+)$/i) || [, ''])[1];
    out.push({
      id: (cls.match(/post-(\d+)/) || [, ''])[1] || a.href,
      url: a.href.split('#')[0],
      title: (a.innerText || '').replace(/\s+/g, ' ').trim(),
      company: (tax('organisation') || 'hackney council').replace(/\banonymous apps\b/, '').trim()
               .replace(/\b\w/g, c => c.toUpperCase()),
      location: 'Hackney, London',
      salary, closes,
      directorate: tax('directorate'), service: tax('service'),
    });
  }
  return out;
})()
"""


def _slug(url):
    m = re.search(r"/vacancy/([a-z0-9-]+)", url or "")
    return m.group(1) if m else ""


def _enum_page(pool):
    rows = cfx.evaluate(ENUM)
    if isinstance(rows, list):
        for r in rows:
            key = _slug(r.get("url")) or r.get("id")
            if key and key not in pool:
                pool[key] = r


def _nav_ready(url):
    cfx.navigate(url)
    cfx.poll("document.readyState", predicate=lambda r: r == "complete", timeout=30.0)
    # Hackney fronts every page with a cookie-consent overlay that blocks Hermes's
    # snapshot-driven interaction (and later the apply click-through) — accept it
    # once per navigation. No-op when it's already been accepted / isn't present.
    if cfx.dismiss_cookie_banner():
        print("[feed] dismissed Hackney cookie-consent banner", file=sys.stderr)


def main():
    args = sys.argv[1:]
    pages = 3
    if "--pages" in args:
        try:
            pages = int(args[args.index("--pages") + 1])
        except (ValueError, IndexError):
            pass
    force = "--force" in args or "--all" in args

    nav = None
    if "--nav" in args:
        try:
            nav = args[args.index("--nav") + 1]
        except IndexError:
            print("ERROR nav: --nav needs a URL")
            return 2
    if nav and not force:
        rem = board_cooldown.remaining_hours(BOARD, QUERY)
        if rem > 0:
            print("[]")
            print(f"\nCOOLDOWN: {BOARD}/{QUERY!r} was already confirmed exhausted "
                  f"({rem:.1f}h remaining). Skipped WITHOUT re-fetching. Pass --force "
                  f"to re-source anyway.", file=sys.stderr)
            return 1

    pool = {}
    try:
        if nav:
            _nav_ready(nav)
        base_url = (cfx.current_url() or f"{BASE}/job-search/").split("?")[0].rstrip("/")
        base_url = re.sub(r"/page/\d+$", "", base_url)
        for p in range(1, max(1, pages) + 1):
            if p > 1:
                _nav_ready(f"{base_url}/page/{p}/")
                title = cfx.evaluate("document.title") or ""
                if "not found" in title.lower() or "nothing found" in title.lower():
                    break
            before = len(pool)
            _enum_page(pool)
            if p > 1 and len(pool) == before:  # past the last page (or a 404 template)
                break
            time.sleep(0.5)
    except cfx.CfxError as e:
        print(f"ERROR: {e}")
        return 2

    all_jobs = list(pool.values())
    if check_title is not None:
        for j in all_jobs:
            if j.get("title"):
                try:
                    j["eligibility"] = check_title.check_title(j["title"])
                except Exception:
                    pass

    if "--all" in args:
        jobs = all_jobs
    else:
        seen = load_seen_slugs()
        jobs = [j for j in all_jobs if _slug(j.get("url")) not in seen]
    filtered = len(all_jobs) - len(jobs)

    board_cooldown.record_yield(BOARD, QUERY, len(jobs))
    print(json.dumps(jobs, ensure_ascii=False, indent=2))
    if jobs:
        print(f"\n{len(jobs)} FRESH vacancies ({filtered} already in application-tracker.csv "
              f"filtered out). Iterate each .url (stable /vacancy/<slug>/) directly.",
              file=sys.stderr)
    else:
        marked = ""
        if all_jobs:
            hrs = board_cooldown.adaptive_hours(BOARD, QUERY)
            board_cooldown.mark(BOARD, QUERY, hours=hrs)
            marked = f" Marked {BOARD}/{QUERY} cooldown ({hrs:.0f}h, adaptive)."
        print(f"\nEXHAUSTED: all {len(all_jobs)} vacancies on the scanned pages are "
              f"already tracked.{marked}", file=sys.stderr)
    return 0 if jobs else 1


if __name__ == "__main__":
    try:
        import stagetimer  # _common/scripts is on sys.path; no-op unless STAGETIMER set
        _src = stagetimer.timed("source")
    except Exception:
        import contextlib
        _src = contextlib.nullcontext()
    with _src:
        sys.exit(main())
