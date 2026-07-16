#!/usr/bin/env python3
"""
feed.py — enumerate distinct vacancies from a Civil Service Jobs search results page.

CSJ (civilservicejobs.service.gov.uk) is the GOV.UK central vacancy board. Its front
end is session-driven: every link carries a **base64 `SID`** encoding the request
params + a server signature (`reqsig`) — SIDs are ONE-SHOT and session-bound (a card
href used twice, or fetch()ed then navigated, returns "Cannot view job"). The stable,
session-independent id is the vacancy code inside the SID (`joblist_view_vac=NNNNNNN`),
and the STABLE canonical URL (found in the detail page's share links, verified to
navigate directly) is:

    https://www.civilservicejobs.service.gov.uk/csr/jobs.cgi?jcode=<vacid>

That jcode URL is what goes in the tracker and what the loop navigates per posting
(works with `jd.py --nav`). Never log or dedup on an index.cgi?SID=… URL.

Returns a de-duplicated JSON list of
{id, url, title, company (=department), location, salary, grade?, closes, ref,
 eligibility} — same consumption shape as the other feeds; pipe it to precheck.py.

Usage:
    CFX_KEY=... CFX_TAB=... python3 feed.py [--nav "<search SID url>"] [--pages N | --all-pages] [--all] [--force]

  --nav    navigate to this CSJ search URL first (the saved-search SID URL in
           searches.csv row `csj`). Without it, enumerates whatever CSJ results page
           the tab is already on. If CSJ answers "Cannot view job" / a generic page,
           the search-context SID has EXPIRED (reqsig is timestamped) — regenerate it:
           open civilservicejobs.service.gov.uk, run the search (London, radius 10mi),
           and paste the resulting index.cgi?SID=… URL into searches.csv.
  --pages  follow "next »" up to N pages (default 2; 25 cards/page).
  --all-pages  follow "next »" to the END of the result set (a London radius-10
           search is ~17 pages), capped at SAFETY_CAP. USE THIS for a real source
           pass — a fixed low --pages was silently missing on-profile roles buried
           past page 2/4. Per-page progress is logged to stderr; enumeration is all
           in-process, so all 17 pages are still ONE model turn.
  --all    include jobs already in application-tracker.csv (default: exclude — you
           only get FRESH candidates) and bypass the cooldown gate.
  --force  bypass the board+query cooldown gate (deliberate re-source).

**ALTCHA gate (auto-solved, sanctioned):** CSJ fronts fresh sessions with an ALTCHA
"I'm not a robot" checkbox — an open-source PROOF-OF-WORK widget (altcha.org), not
reCAPTCHA/Turnstile/hCaptcha: ticking it runs a deterministic client-side computation,
no puzzle, no human judgment. The user granted a STANDING, CSJ-ONLY exception
(2026-07-13) to auto-tick it and click Continue, alongside the existing reCAPTCHA-v2
exception. This does NOT extend to any other CAPTCHA on CSJ or ALTCHA on other sites
without asking. Handled automatically here (and worth reusing via `solve_altcha()`
for the apply flow).

**No hide/dismiss:** CSJ result cards have no "not interested" control, so there is
nothing to click for SKILL.md step 10 — dedup relies entirely on the tracker (this is
the documented "board offers no dismiss control" case; jcode-dedup here makes it safe).

The board+query cooldown is enforced here like the other feeds (BOARD="csj", fixed
QUERY key — the saved search context isn't keyword-parameterized, same pattern as
WTTJ's "home"). Zero fresh candidates on a real pass auto-marks a 12h cooldown.
"""
import base64
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

BOARD = "csj"
# The saved search context is not keyword-parameterized (the SID encodes it), so the
# cooldown key is a fixed slug — same pattern as WTTJ's "home". Keep in sync with the
# `query` column of the `csj` row in searches.csv (loop-preflight.py matches on it).
QUERY = "london-search"

STABLE_URL = "https://www.civilservicejobs.service.gov.uk/csr/jobs.cgi?jcode={}"

# Hard ceiling on --all-pages so a pagination bug can never loop forever. A London
# radius-10 search is ~17 pages; 40 leaves generous headroom.
SAFETY_CAP = 40

TRACKER = os.path.join(_here, "..", "..", "..", "application-tracker.csv")


def load_seen_ids():
    """CSJ vacancy ids already in application-tracker.csv — the stable
    `jobs.cgi?jcode=<id>` URLs this feed logs (+ any `joblist_view_vac=<id>` that leaked
    into a row) — via the shared `precheck.load_seen` (csv-quoting-proof regex scan)."""
    return load_seen(r"(?:jcode=|joblist_view_vac=)(\d+)", tracker=TRACKER)


def _title():
    t = cfx.evaluate("document.title")
    return t if isinstance(t, str) else ""


def solve_altcha(timeout_s=25.0):
    """If the ALTCHA 'Quick check needed' interstitial is up, solve it (tick the
    checkbox -> proof-of-work runs -> click Continue) and wait for the real page.
    Returns True if the gate was present and cleared, False if no gate. Raises
    CfxError text via normal cfx paths on hard failure. Sanctioned CSJ-only
    auto-solve — see module docstring."""
    has_gate = cfx.evaluate(
        "!!document.querySelector('input[type=checkbox][id^=altcha]')")
    if not has_gate:
        return False
    print("[feed] ALTCHA gate — auto-solving (sanctioned, CSJ-only)", file=sys.stderr)
    cfx.click_selector("input[type=checkbox][id^=altcha]")
    checked = cfx.poll(
        "(()=>{const c=document.querySelector('input[type=checkbox][id^=altcha]');"
        "return c ? c.checked : false;})()",
        predicate=lambda r: r is True, timeout=timeout_s, interval=0.5)
    if checked is not True:
        print("[feed] ALTCHA checkbox never verified — treat as a hard stop "
              "(message the user, VNC), do not retry in a loop.", file=sys.stderr)
        return False
    # Continue submits the interstitial form; the URL does NOT change (same-URL POST),
    # so wait on the TITLE changing away from the gate, not on navigation.
    cfx.evaluate("(()=>{const b=[...document.querySelectorAll('button,input[type=submit]')]"
                 ".find(x=>/continue/i.test(x.innerText||x.value||'')); if(b)b.click();})()")
    cfx.poll("document.title", predicate=lambda t: isinstance(t, str)
             and "quick check" not in t.lower(), timeout=20.0, interval=0.5)
    time.sleep(1.0)
    return True


ENUM = r"""
(() => {
  const out = [];
  for (const card of document.querySelectorAll('li.search-results-job-box')) {
    const a = card.querySelector('h3.search-results-job-box-title a, h3 a');
    if (!a) continue;
    let vac = '';
    try {
      const sid = (a.href.split('SID=')[1] || '').split('&')[0];
      const decoded = atob(sid.replace(/=+$/,'') + '='.repeat((4 - sid.length % 4) % 4));
      vac = (decoded.match(/joblist_view_vac=(\d+)/) || [,''])[1];
    } catch (e) {}
    const txt = s => { const e = card.querySelector(s); if (!e) return '';
      // field divs start with an sr-only <h4> label ("Department") or a "Label :" prefix
      return e.innerText.replace(/^\s*(Department|Location|Salary|Closes|Reference|Distance)\s*:?\s*/i, '')
              .replace(/\s+/g, ' ').trim(); };
    const title = (a.innerText || '').replace(/\s+/g, ' ').trim();
    // Grade is the REAL Civil Service seniority signal (EO/HEO/SEO = junior→mid,
    // G7/G6/SCS = senior) but CSJ cards don't expose it as a field — harvest any
    // grade token the title/salary line carries (e.g. "(SEO)", "G7", "Grade 6").
    // Empty when the title names no grade; precheck then falls back to the pay band.
    const gm = (title + ' ' + txt('.search-results-job-box-salary'))
      .match(/\b(SCS\s?\d?|Grade\s?[67]|G[67]|SEO|HEO|EO|AO|AA)\b/i);
    out.push({
      id: vac,
      title: title,
      company: txt('.search-results-job-box-department'),
      location: txt('.search-results-job-box-location'),
      salary: txt('.search-results-job-box-salary'),
      grade: gm ? gm[1].toUpperCase().replace(/\s+/g, '') : '',
      closes: txt('.search-results-job-box-closingdate'),
      ref: txt('.search-results-job-box-refcode'),
    });
  }
  return out;
})()
"""


def _enum_page(pool):
    """Enumerate the current results page into `pool` (keyed by vac id). Returns
    the number of cards SEEN on the page (not just new-to-pool) so the crawler can
    tell "ran off the end / landed on a gate" (0 cards) from "all dupes" (>0 cards,
    0 new)."""
    rows = cfx.evaluate(ENUM)
    if not isinstance(rows, list):
        return 0
    for r in rows:
        vid = r.get("id")
        if vid and vid not in pool:
            r["url"] = STABLE_URL.format(vid)
            pool[vid] = r
    return len(rows)


def _next_page(retries=1):
    """Follow the results pagination "next" control. Detection is deliberately
    tolerant: the label is "next »" today, but a stray entity / a separated » / an
    aria-label-only control would silently end the crawl early (this was a real
    "gives up at page 4 of 17" symptom). Match, in order: an anchor whose text
    starts with "next" (optionally trailed by »/›/>), then rel=next, then a
    title/aria-label of "next". A disabled/absent next (real last page) returns ''
    and ends the crawl cleanly.

    A transient camofox HTTP 500 on the pagination navigate used to raise and
    discard the whole pool (2026-07-14: lost 275 cards at page 12). We now retry
    a 500 once; if it still fails we return False (caller stops cleanly) and the
    cards gathered so far are still emitted — never thrown away."""
    href = cfx.evaluate(
        "(()=>{"
        "const links=[...document.querySelectorAll('a[href]')];"
        "const txt=x=>((x.innerText||x.textContent||'').replace(/\\s+/g,' ').trim());"
        "let a=links.find(x=>/^next\\s*(?:»|›|&raquo;|&rsaquo;|>)?$/i.test(txt(x)));"
        "if(!a) a=links.find(x=>/^next\\b/i.test(txt(x)) && txt(x).length<=12);"
        "if(!a) a=document.querySelector('a[rel=next][href]');"
        "if(!a) a=links.find(x=>/^next$/i.test((x.getAttribute('title')||x.getAttribute('aria-label')||'').trim()));"
        # a disabled 'next' is often a same-page anchor (#) or aria-disabled — reject it
        "if(a && (a.getAttribute('aria-disabled')==='true' || (a.getAttribute('href')||'').trim()==='#')) a=null;"
        "return a?a.href:'';"
        "})()")
    if not (isinstance(href, str) and href):
        return False
    attempt = 0
    while True:
        try:
            cfx.navigate(href)
            cfx.poll("document.readyState", predicate=lambda r: r == "complete", timeout=20.0)
            break
        except cfx.CfxError as e:
            # Retry a transient 5xx once (camofox server hiccup); give it a beat.
            if attempt < retries and "500" in str(e):
                print(f"[feed] pagination nav 500 (attempt {attempt+1}) — retrying once",
                      file=sys.stderr)
                time.sleep(3.0)
                attempt += 1
                continue
            print(f"[feed] pagination nav failed ({e}) — stopping cleanly, "
                  f"keeping cards already gathered.", file=sys.stderr)
            return False
    solve_altcha()  # pagination can land on the ALTCHA gate — clear it, then enum
    time.sleep(1.5)
    return True


def main():
    args = sys.argv[1:]
    pages = 2
    if "--pages" in args:
        try:
            pages = int(args[args.index("--pages") + 1])
        except (ValueError, IndexError):
            pass
    all_pages = "--all-pages" in args
    force = "--force" in args or "--all" in args

    if "--nav" in args:
        try:
            raw_nav = args[args.index("--nav") + 1]
        except IndexError:
            print("ERROR nav: --nav needs a URL")
            return 2
        if not force:
            rem = board_cooldown.remaining_hours(BOARD, QUERY)
            if rem > 0:
                print("[]")
                print(f"\nCOOLDOWN: {BOARD}/{QUERY!r} was already confirmed exhausted "
                      f"({rem:.1f}h remaining). Skipped WITHOUT re-fetching. Pass "
                      f"--force to re-source anyway.", file=sys.stderr)
                return 1
        try:
            cfx.navigate(raw_nav)
            cfx.poll("document.readyState", predicate=lambda r: r == "complete", timeout=30.0)
        except cfx.CfxError as e:
            print(f"ERROR nav: {e}")
            return 2

    pool = {}
    try:
        solve_altcha()
        title = _title()
        if not re.search(r"\d+\s+Search results", title, re.I):
            print("[]")
            print(f"\nERROR: not on a CSJ results page (title={title!r}). If this says "
                  f"'Cannot view job'/'Civil Service Jobs' generically, the search-context "
                  f"SID in searches.csv has EXPIRED — regenerate it (see module docstring) "
                  f"and update the csj row's nav URL.", file=sys.stderr)
            return 2

        # --all-pages: follow "next" to the end of the result set (a CSJ London
        # search is ~17 pages); a fixed --pages N still bounds it. SAFETY_CAP stops
        # a pathological loop even in --all-pages mode.
        max_pages = SAFETY_CAP if all_pages else max(1, pages)
        empty_streak = 0
        p = 0
        while p < max_pages:
            seen_on_page = _enum_page(pool)
            print(f"[feed] page {p+1}/{'all' if all_pages else max_pages}: "
                  f"{seen_on_page} card(s) on page, {len(pool)} unique so far",
                  file=sys.stderr)
            p += 1
            # A page with zero cards means we've run off the end OR landed on a gate
            # / bounce that didn't clear — don't keep paging into the void.
            if seen_on_page == 0:
                empty_streak += 1
                if empty_streak >= 2:
                    print("[feed] two empty pages — stopping (end of results or an "
                          "uncleared gate).", file=sys.stderr)
                    break
            else:
                empty_streak = 0
            if p >= max_pages:
                break
            if not _next_page():
                print(f"[feed] no 'next' control after page {p} — end of results.",
                      file=sys.stderr)
                break
        if all_pages and p >= SAFETY_CAP:
            print(f"[feed] hit SAFETY_CAP ({SAFETY_CAP} pages) — stopping; raise it in "
                  f"feed.py if a search legitimately runs longer.", file=sys.stderr)
    except cfx.CfxError as e:
        # 2026-07-14: a transient camofox HTTP 500 mid-crawl used to be re-raised
        # here and DISCARD every card gathered so far. Now we emit what we have
        # (partial is infinitely better than nothing) and warn loudly.
        print(f"[feed] ERROR mid-crawl ({e}) — emitting {len(pool)} cards gathered so "
              f"far rather than discarding them. Re-run with --force to top up.",
              file=sys.stderr)
        if not pool:
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
        jobs = [j for j in all_jobs if j["id"] not in seen]
    filtered = len(all_jobs) - len(jobs)

    board_cooldown.record_yield(BOARD, QUERY, len(jobs))
    print(json.dumps(jobs, ensure_ascii=False, indent=2))
    if jobs:
        print(f"\n{len(jobs)} FRESH vacancies ({filtered} already in application-tracker.csv "
              f"filtered out). Iterate each .url (stable jobs.cgi?jcode=…) directly — "
              f"never an index.cgi?SID=… link.", file=sys.stderr)
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
