#!/usr/bin/env python3
"""
feed.py — enumerate vacancies from GOV.UK's new "Work Hub / Find a job" service
(jobs.service.gov.uk). Added 2026-08-28 (a genuinely new board — not the same site as
Civil Service Jobs / civilservicejobs.service.gov.uk, though it DOES also carry Civil
Service vacancies as a subset — see the dedup note below).

WHAT THE SITE IS. A GOV.UK-branded ("Work Hub", nav item "Find a job") experimental
job-search aggregator at `www.jobs.service.gov.uk`, built on Next.js. It blends public
and private sector postings from many sources — Civil Service, NHS-adjacent, and a large
volume of ordinary UK employer/agency ads (retail, construction, recruitment agencies,
etc.) — NOT just government jobs, despite the GOV.UK branding. Akamai fronts it and
returns HTTP 403 to a plain `curl`/non-browser UA — sourcing MUST go through camofox
(no keyless HTTP path like ats-direct/Adzuna).

SEARCH. `https://www.jobs.service.gov.uk/jobs/search?keywords=<kw>&locationId=<id>&location=<text>`
  - `keywords` may be blank (returns the whole board, thousands of results — use a
    keyword). No boolean OR observed; treat like CSJ (single term per query).
  - `location`/`locationId` — `locationId=N17GP&location=N1+7GP%2C+Greater+London%2C+London%2C+England`
    is a London postcode-anchored 10-mile-radius search (verified live). A bare city name
    may also work but wasn't tested; the postcode form is what's wired into DEFAULT_LOC
    below and known to work.
  - Pagination: append `&pageNumber=N` (1-indexed). The site 200s past the last page with
    an empty results list rather than 404ing (unlike Hackney) — enumeration just stops
    when a page yields zero NEW cards.

CARDS. Clean, stable `data-testid` attributes (verified 2026-08-28, no scraping fragility
observed): `div[data-testid^="searchResultCard-"]` (the id suffix IS the job id) wraps
`a[data-testid^="jobTitle-"]` (href `/jobs/<24-hex-id>`), `p[data-testid="searchResultCardEmployer"]`
(two `<span>`s: company, " - location"), `p[data-testid="searchResultsCardTags"]` (job-type
tags: Permanent/Full time/etc.), and `p[data-testid="searchResultCardJobDescription"]` (a
short JD snippet — enough for a first-pass title/desc screen without opening the posting).

APPLY FLOW — read `sites/jobs.service.gov.uk/NOTES.md` before driving any candidate.
Two shapes, and you don't know which until you open `/jobs/<id>/apply`:
  1. EXTERNAL REDIRECT — "Continue to the employer's website" button. No GOV.UK login
     needed; lands on the employer's own careers page or a 3rd-party ATS (bespoke agency
     portals are common — additionalresourcescareers.net, contactrh.com, aplitrak.com,
     webrecru.it, salesforce-sites, etc. — none of the standard guest-drivable ATSes
     (Greenhouse/Ashby/Lever/SmartRecruiters/Workable) were seen in a first pass, but
     check `ats_router.classify()` on the redirect URL before assuming a bespoke driver
     is needed). DRIVE THIS PATH FIRST when both are available.
  2. IN-PLATFORM — a native multi-step GOV.UK Design System wizard hosted on
     jobs.service.gov.uk itself (Your details -> Upload a CV -> Cover message -> ...).
     Submitting past the cover-message step requires **GOV.UK One Login**
     (`/auth/sign-in`), which mandates a **mobile phone number for SMS/call
     verification** on top of email+password. Credentials exist (ats-credentials.csv row
     `jobs.service.gov.uk (GOV.UK One Login)`), so this is a standard SKILL.md LOGIN-WALL
     hard stop (stop at the OTP prompt, message the user, wait for the code), NOT an
     account-creation hard stop — see sites/jobs.service.gov.uk/NOTES.md for the full
     recipe (the session persists across postings once established).

DEDUP WARNING — Civil Service overlap. Some Work Hub postings ARE Civil Service vacancies
(verified live: "No10 Digital Business Analyst", Cabinet Office, Company="Government
Recruitment Service" here == the same jcode=2010459 vacancy already sourced by
`sites/civilservicejobs/scripts/feed.py`). Cross-board dedup by URL alone will NOT catch
this (different domain/id entirely) — cross-check by (Company, Role) against the tracker
before driving a Work Hub row that smells like Civil Service (SEO/HEO/EO grades, "Digital"
in a Cabinet Office/DfT/HMT/etc. title), same discipline as the CSJ<->applicationtrack
cross-post note in SKILL.md.

Returns a de-duplicated JSON list of {id, url, title, company, location, tags,
description, eligibility} — same shape as the other feeds; pipe it to precheck.py.

Usage:
    CFX_KEY=... CFX_TAB=... python3 feed.py [--what "<query>"] [--where "<postcode>, <text>"]
                    [--location-id <id>] [--nav "<jobs.service.gov.uk search url>"]
                    [--pages N] [--all] [--force]
  --what         search keyword (default: none — the board's whole-London feed; prefer a
                 keyword, the unfiltered feed is thousands of rows).
  --where        the `location` query param text (default: "London" — a bare city name is
                 enough, no postcode needed; "London, England" with the comma+country
                 suffix returns ZERO results, verified live, don't use that form; pass a
                 real postcode via --where for a tighter radius, sourced at call time,
                 never hardcoded here — see the PII note by DEFAULT_LOCATION_TEXT below).
  --location-id  the `locationId` param (default: none — only needed for postcode-radius
                 search, see --where).
  --nav          a jobs.service.gov.uk search URL directly (overrides --what/--where).
  --pages        pages to enumerate (default 3; each page is ~10 cards).
  --all          include already-tracked postings + bypass the cooldown gate.
  --force        bypass the cooldown gate only.

Cooldown key is the `--what` keyword (board `govukjobs`) — keep new keywords added to
searches.csv in sync with this board name.
"""
import json
import os
import re
import sys
import time
from urllib.parse import quote

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_here, "..", "..", "_common", "scripts"))
import cfx  # noqa: E402
import board_cooldown  # noqa: E402
from precheck import load_seen  # noqa: E402
try:
    import check_title  # noqa: E402
except Exception:
    check_title = None

BOARD = "govukjobs"
BASE = "https://www.jobs.service.gov.uk"
# PII GATE (SKILL.md §12): this file is TRACKED, so it must never carry the applicant's
# real postcode. A bare city name works fine as the `location` param on its own (verified
# live 2026-08-28 — "London" with no locationId returns real London-radius results, same
# card count as a postcode-anchored search) and is not personally identifying, so that's
# the tracked default. If a caller wants postcode-precision radius search, pass
# `--where`/`--location-id` explicitly at call time (e.g. sourced from the gitignored
# apply-defaults.json's "Postal" field) — never hardcode a real postcode in this file.
DEFAULT_LOCATION_ID = ""
DEFAULT_LOCATION_TEXT = "London"

TRACKER = os.path.join(_here, "..", "..", "..", "application-tracker.csv")


def load_seen_ids():
    """Job ids already in application-tracker.csv (matches the /jobs/<id> URL form).
    Does NOT catch the Civil-Service cross-post case (see module docstring) — that
    needs a live (Company, Role) check at drive time, not a sourcing-time id match."""
    return load_seen(r"jobs\.service\.gov\.uk/jobs/([a-f0-9]{20,})", tracker=TRACKER)


ENUM = r"""
(() => {
  const out = [];
  for (const card of document.querySelectorAll('div[data-testid^="searchResultCard-"]')) {
    const testid = card.getAttribute('data-testid') || '';
    const id = testid.replace('searchResultCard-', '');
    const a = card.querySelector('a[data-testid^="jobTitle-"]') || card.querySelector('a[href^="/jobs/"]');
    if (!a) continue;
    const emp = card.querySelector('[data-testid="searchResultCardEmployer"]');
    const spans = emp ? [...emp.querySelectorAll('span')] : [];
    const company = spans[0] ? spans[0].innerText.trim() : '';
    const locSpan = spans[1] ? spans[1].innerText.trim() : '';
    const location = locSpan.replace(/^-\s*/, '');
    const tags = [...card.querySelectorAll('[data-testid="searchResultsCardTags"] span')]
      .map(s => s.innerText.trim()).filter(Boolean);
    const descEl = card.querySelector('[data-testid="searchResultCardJobDescription"]');
    out.push({
      id,
      url: BASE_URL + '/jobs/' + id,
      title: (a.innerText || '').replace(/\s+/g, ' ').trim(),
      company, location, tags,
      description: descEl ? descEl.innerText.replace(/\s+/g, ' ').trim().slice(0, 300) : '',
    });
  }
  return out;
})()
""".replace("BASE_URL", "'%s'" % BASE)


def _id(url):
    m = re.search(r"/jobs/([a-f0-9]{20,})", url or "")
    return m.group(1) if m else ""


def _nav_page_url(nav, page):
    """Return nav's URL with pageNumber=<page> set (added or replaced), preserving
    every other query param (e.g. jobBase=REMOTE). Page 1 = nav unchanged (no
    pageNumber param, matching the site's own URL for page 1).
    BUG FIX (2026-08-28): the old caller only ever used `nav` for page 1 and fell
    back to the DEFAULT London-anchored _search_url() for every later page —
    silently dropping jobBase=REMOTE (or any other --nav-only param) from pages
    2+, so a "3-page REMOTE sweep" was actually 1 real remote page followed by 2
    regular London pages for the same keyword. Always paginate the NAV url when
    one was given."""
    from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
    parts = urlsplit(nav)
    q = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "pageNumber"]
    if page > 1:
        q.append(("pageNumber", str(page)))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(q), parts.fragment))


def _search_url(keywords, where, location_id, page):
    q = "keywords=%s&location=%s" % (quote(keywords or ""), quote(where or DEFAULT_LOCATION_TEXT))
    loc_id = location_id or DEFAULT_LOCATION_ID
    if loc_id:
        q += "&locationId=%s" % quote(loc_id)
    if page > 1:
        q += "&pageNumber=%d" % page
    return "%s/jobs/search?%s" % (BASE, q)


def _nav_ready(url):
    r = cfx.goto(url)
    if not r.get("ok"):
        print(f"[feed] WARN: {url} did not render cleanly ({r.get('attempts')} attempts)",
              file=sys.stderr)
    # Akamai/experimental-service cookie banner ("Cookies on Work Hub") — accept once.
    try:
        cfx.evaluate("""(() => {
            const b = [...document.querySelectorAll('button')].find(
              x => /accept analytics|reject analytics/i.test(x.innerText));
            if (b) { b.click(); return true; } return false;
        })()""")
    except cfx.CfxError:
        pass


def _enum_page(pool):
    rows = cfx.evaluate(ENUM)
    if isinstance(rows, list):
        for r in rows:
            key = _id(r.get("url"))
            if key and key not in pool:
                pool[key] = r


def main():
    args = sys.argv[1:]

    def opt(name, default=None):
        return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else default

    what = opt("--what", "")
    where = opt("--where", DEFAULT_LOCATION_TEXT)
    location_id = opt("--location-id", DEFAULT_LOCATION_ID)
    nav = opt("--nav")
    try:
        pages = int(opt("--pages", "3"))
    except ValueError:
        pages = 3
    force = "--force" in args or "--all" in args

    query_key = what or "(blank)"
    if not force:
        rem = board_cooldown.remaining_hours(BOARD, query_key)
        if rem > 0:
            print("[]")
            print(f"\nCOOLDOWN: {BOARD}/{query_key!r} was already confirmed exhausted "
                  f"({rem:.1f}h remaining). Skipped WITHOUT re-fetching. Pass --force "
                  f"to re-source anyway.", file=sys.stderr)
            return 1

    pool = {}
    try:
        for p in range(1, max(1, pages) + 1):
            url = _nav_page_url(nav, p) if nav else _search_url(what, where, location_id, p)
            _nav_ready(url)
            before = len(pool)
            _enum_page(pool)
            if len(pool) == before and p > 1:
                break  # ran off the end of the results
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
        seen = load_seen_ids()
        jobs = [j for j in all_jobs if _id(j.get("url")) not in seen]
    filtered = len(all_jobs) - len(jobs)

    board_cooldown.record_yield(BOARD, query_key, len(jobs))
    print(json.dumps(jobs, ensure_ascii=False, indent=2))
    if jobs:
        print(f"\n{len(jobs)} FRESH vacancies ({filtered} already in application-tracker.csv "
              f"filtered out). Open each .url + '/apply' — see NOTES.md for the two apply "
              f"shapes (external redirect vs GOV.UK One Login in-platform wall).",
              file=sys.stderr)
    else:
        marked = ""
        if all_jobs:
            hrs = board_cooldown.adaptive_hours(BOARD, query_key)
            board_cooldown.mark(BOARD, query_key, hours=hrs)
            marked = f" Marked {BOARD}/{query_key} cooldown ({hrs:.0f}h, adaptive)."
        print(f"\nEXHAUSTED: all {len(all_jobs)} vacancies on the scanned pages are "
              f"already tracked.{marked}", file=sys.stderr)
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
