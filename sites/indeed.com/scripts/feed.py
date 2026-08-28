#!/usr/bin/env python3
"""
feed.py — enumerate distinct job postings from an Indeed search results page.

Indeed is the reliable guest-browsable board (no login). Each result card carries a
stable **`data-jk`** (job key) on its title link — that's the id; the canonical URL
is `viewjob?jk=<jk>`. This returns a de-duplicated JSON list of
{id, url, title, company, location} so the apply loop can iterate real postings and
dedup by `jk` against `application-tracker.csv`.

Usage:
    CFX_KEY=... CFX_TAB=... python3 feed.py [--nav "<search url>"] [--pages N] [--location "<city>"] [--all]
    CFX_KEY=... CFX_TAB=... python3 feed.py hide <jk>

  --nav    navigate to this Indeed search URL first (e.g.
           "https://uk.indeed.com/jobs?q=UX+Designer&sort=date&fromage=7&remotejob=remote").
           Without it, enumerates whatever search page the tab is already on.
           **Location defaults to London** (Jane works London or fully-remote only —
           see SKILL.md §"Location / relocation"): the search URL's `l` param is set to
           London automatically unless it already carries an explicit `l=` (e.g.
           `l=Remote`, or a city you deliberately chose). Pass `--location "<city>"` to
           override the default for this run.
  --pages  follow "Next" up to N pages (default 1). Each page dismisses the modal first.
  --location  location to pin the search to (default "London"). Ignored if the --nav URL
              already sets `l=`.
  --all    include jobs already in application-tracker.csv (default: EXCLUDE them, so
           you only get FRESH candidates — mirrors welcometothejungle/scripts/feed.py).
  hide <jk>  click the card's "Not interested" control (JS click) so a COMPLETED or
             SKIPPED posting doesn't resurface in later searches this run. Must be run
             on the results tab with that card present. Do NOT hide `Blocked` postings.

**Dedup is now done IN CODE, not by the caller.** Every `jk` already present anywhere
in `application-tracker.csv` (any status) is filtered out before the JSON is printed —
this used to be a docstring instruction ("dedup by jk against the tracker") that the
calling agent had to do by hand every time, re-spending tokens re-reading the same
already-known postings on every search. Same fix, same reasoning as
welcometothejungle/scripts/feed.py's `load_seen_ids()`.

**The board+query cooldown is now enforced HERE too, automatically (not a soft caller
step):** when you pass `--nav <search url>`, feed.py reads the search term out of the
URL (`q=`) and, if that board+query was already confirmed dry, prints `[]` and exits
IMMEDIATELY — no navigate, no enumerate, no re-filter, zero browser cost. And when a
real pass turns up zero fresh candidates, feed.py auto-marks the cooldown itself. So a
fresh bot instance that just runs `feed.py --nav …` can no longer re-walk the same
declined feed — the check and the mark can't be forgotten because the caller no longer
does them. Pass `--force` (or `--all`) to bypass the gate and re-source deliberately.

Auto-dismisses Indeed's blocking email/job-alert modal (see dismiss_modal.py) before
reading, since it locks scroll and hides cards.
"""
import json
import os
import sys
import time
from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_here, "..", "..", "_common", "scripts"))
import cfx  # noqa: E402
import board_cooldown  # noqa: E402
from precheck import load_seen  # noqa: E402  (shared tracker-dedup, was duplicated per feed)
sys.path.insert(0, _here)
import dismiss_modal  # noqa: E402  (reuse the modal dismisser)

BOARD = "indeed"

BASE = "https://uk.indeed.com"

# Jane only works London or fully remote (see SKILL.md §"Location / relocation"), so
# every Indeed search is pinned to London by default. Indeed's location param is `l`.
DEFAULT_LOCATION = "London"

# application-tracker.csv lives at the skill root (…/scripts -> indeed.com -> sites -> root)
TRACKER = os.path.join(_here, "..", "..", "..", "application-tracker.csv")


def load_seen_jks():
    """Indeed jk ids already in application-tracker.csv (any status), via the shared
    `precheck.load_seen` (csv-quoting-proof regex scan). NB `jk` isn't always stable per
    posting (repost / ephemeral id) — a re-served posting under a NEW jk can slip through;
    see NOTES for the title+company glance mitigation."""
    return load_seen(r"[?&]jk=([A-Za-z0-9]+)", tracker=TRACKER)


def _ensure_location(url, location=DEFAULT_LOCATION):
    """Return `url` with Indeed's `l` (location) query param set to `location`.
    Only fills it when absent — an explicit `l=` already in the URL (e.g. `l=Remote`
    or another city the caller deliberately chose) is left untouched. Also drops the
    stale `vjk`/`jk` single-job params so we get a real results list, not a detail view."""
    parts = urlparse(url)
    params = [(k, v) for (k, v) in parse_qsl(parts.query, keep_blank_values=True)
              if k not in ("vjk", "jk")]
    keys = {k.lower() for (k, _) in params}
    if "l" not in keys:
        params.append(("l", location))
    return urlunparse(parts._replace(query=urlencode(params)))

ENUM = r"""
(() => {
  const out = new Map();
  for (const card of document.querySelectorAll('div.job_seen_beacon, td.resultContent, li')) {
    const a = card.querySelector('a.jcs-JobTitle, h2.jobTitle a, a[data-jk]');
    if (!a) continue;
    const jk = a.getAttribute('data-jk') || (a.id || '').replace(/^job_/, '');
    if (!jk || out.has(jk)) continue;
    const txt = s => { const e = card.querySelector(s); return e ? e.textContent.replace(/\s+/g, ' ').trim() : ''; };
    out.set(jk, {
      id: jk,
      url: 'https://uk.indeed.com/viewjob?jk=' + jk,
      title: (a.textContent || '').replace(/\s+/g, ' ').trim(),
      company: txt('[data-testid=company-name], .companyName, span.companyName'),
      location: txt('[data-testid=text-location], .companyLocation'),
    });
  }
  return [...out.values()];
})()
"""


def _enum_page(pool):
    try:
        dismiss_modal.main()  # clear the email/job-alert modal first
    except SystemExit:
        pass
    except Exception:
        pass
    rows = cfx.evaluate(ENUM)
    if isinstance(rows, list):
        for r in rows:
            if r.get("id") and r["id"] not in pool:
                pool[r["id"]] = r


def _next_page():
    href = cfx.evaluate("(()=>{const a=document.querySelector('a[data-testid=pagination-page-next]');return a?a.href:'';})()")
    if isinstance(href, str) and href:
        cfx.navigate(href)
        time.sleep(4)
        return True
    return False


def hide_job(jk):
    """Click the 'Not interested' control on the card for `jk` (JS click, per NOTES).
    Verifies the card is gone. Must be on the results tab with the card present."""
    res = cfx.evaluate(f"""
    (() => {{
      const jk = {json.dumps(jk)};
      const anchor = document.querySelector('[data-jk="' + jk + '"]');
      if (!anchor) return 'CARD_NOT_FOUND';
      const card = anchor.closest('div.job_seen_beacon, li.cardOutline, div.cardOutline, li') || anchor.parentElement;
      // the "Not interested" control is an ICON button — its label is in aria-label,
      // NOT textContent (which is empty). Match either.
      const isNI = b => /not interested/i.test(b.textContent || '') || /not interested/i.test(b.getAttribute('aria-label') || '');
      let btn = card && [...card.querySelectorAll('button,[role=button]')].find(isNI);
      if (!btn) return 'NO_HIDE_BUTTON';
      btn.click();
      return 'CLICKED';
    }})()
    """)
    if res != "CLICKED":
        print(f"hide {jk}: {res}")
        return 1
    time.sleep(1.0)
    # Indeed keeps the data-jk node but COLLAPSES the card content on dismiss — so
    # "hidden" = node gone OR its card is now (near-)empty.
    gone = cfx.evaluate(f"""(()=>{{const a=document.querySelector('[data-jk="{jk}"]');
      if(!a)return true;const c=a.closest('div.job_seen_beacon,li')||a.parentElement;
      return (c.innerText||'').replace(/\\s+/g,'').length < 5;}})()""")
    print(f"hide {jk}: {'HIDDEN' if gone else 'clicked (still visible — re-check)'}")
    return 0 if gone else 1


def main():
    args = sys.argv[1:]
    if args and args[0] == "hide" and len(args) == 2:
        try:
            return hide_job(args[1])
        except cfx.CfxError as e:
            print(f"ERROR: {e}")
            return 2
    pages = 1
    if "--pages" in args:
        try:
            pages = int(args[args.index("--pages") + 1])
        except (ValueError, IndexError):
            pass
    location = DEFAULT_LOCATION
    if "--location" in args:
        try:
            location = args[args.index("--location") + 1]
        except IndexError:
            pass
    force = "--force" in args
    if "--nav" in args:
        try:
            raw_nav = args[args.index("--nav") + 1]
        except IndexError:
            print("ERROR nav: --nav needs a URL")
            return 2
        # COOLDOWN GATE — before paying any browser cost, bail if this board+query was
        # already confirmed dry. This is the whole point: a fresh instance that just runs
        # `feed.py --nav <search>` gets the skip automatically, instead of re-navigating,
        # re-enumerating and re-filtering the same already-declined postings. --force or
        # --all bypasses it (deliberate re-source / debugging).
        query = board_cooldown.query_from_url(raw_nav)
        if query and not force and "--all" not in args:
            rem = board_cooldown.remaining_hours(BOARD, query)
            if rem > 0:
                print("[]")
                print(f"\nCOOLDOWN: {BOARD}/{query!r} was already confirmed exhausted "
                      f"({rem:.1f}h remaining). Skipped WITHOUT re-fetching — no new "
                      f"candidates to expect. Try a different query or board, or pass "
                      f"--force to re-source anyway.", file=sys.stderr)
                return 1
        try:
            url = _ensure_location(raw_nav, location)
            print(f"[feed] searching Indeed in location={location!r}: {url}", file=sys.stderr)
            cfx.navigate(url)
            time.sleep(5)
        except cfx.CfxError as e:
            print(f"ERROR nav: {e}")
            return 2

    pool = {}
    try:
        for p in range(max(1, pages)):
            _enum_page(pool)
            if p + 1 < pages and not _next_page():
                break
    except cfx.CfxError as e:
        print(f"ERROR: {e}")
        return 2

    all_jobs = list(pool.values())
    if "--all" in args:
        jobs = all_jobs
    else:
        seen = load_seen_jks()
        jobs = [j for j in all_jobs if j["id"] not in seen]
    filtered = len(all_jobs) - len(jobs)
    # Record this pass's fresh-count (both paths) for adaptive cooldowns / ordering.
    query = board_cooldown.query_from_url(args[args.index("--nav") + 1]) if "--nav" in args else ""
    track = bool(query) and "--all" not in args
    if track:
        board_cooldown.record_yield(BOARD, query, len(jobs))
    print(json.dumps(jobs, ensure_ascii=False, indent=2))
    if jobs:
        print(f"\n{len(jobs)} FRESH jobs ({filtered} already in application-tracker.csv "
              f"filtered out). Iterate each .url directly.", file=sys.stderr)
    else:
        # AUTO-MARK an ADAPTIVE cooldown so the next firing skips this combo WITHOUT
        # re-fetching — and a persistently-dry combo escalates instead of polling 12h.
        marked = ""
        if track:
            hrs = board_cooldown.adaptive_hours(BOARD, query)
            until = board_cooldown.mark(BOARD, query, hrs)
            marked = f" Auto-marked {BOARD}/{query!r} on cooldown until {until} ({hrs:.0f}h, adaptive)."
        print(f"\nEXHAUSTED: all {len(all_jobs)} jobs on this results page are already in "
              f"application-tracker.csv.{marked} Do NOT re-run this query — try a "
              f"different one or another board.", file=sys.stderr)
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
