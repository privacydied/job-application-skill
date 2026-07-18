#!/usr/bin/env python3
"""
feed.py — enumerate distinct job postings from a LinkedIn Jobs search results page.

WHY THIS EXISTS: LinkedIn was the one board in this skill with NO feed script at
all — every prior sourcing pass was an ad-hoc JS snippet typed fresh into `cfx.sh
eval` each time, with the calling agent manually eyeballing the returned list
against application-tracker.csv to figure out what was already known. That's slow,
token-expensive (the same overlapping ~20-card result set gets re-read and
re-compared by an LLM every single search), and error-prone in exactly the way that
caused a real duplicate application on Indeed (see sites/indeed.com/NOTES.md's
"CRITICAL (RESOLVED)" note) before that board got the same fix. This gives LinkedIn
the same structural fix: enumerate in the browser, dedup against the FULL tracker in
Python code, return only genuinely fresh candidates.

Each result card's numeric job id is on `data-job-id` / `data-occludable-job-id`; the
canonical URL is `https://www.linkedin.com/jobs/view/<id>`.

Usage:
    CFX_KEY=... CFX_TAB=... python3 feed.py --nav "<search url>" [--scrolls N] [--all]
    CFX_KEY=... CFX_TAB=... python3 feed.py hide <id>

  --nav      navigate to this LinkedIn Jobs search URL first (e.g.
             "https://www.linkedin.com/jobs/search/?keywords=UX%20Designer&location=London%2C%20England%2C%20United%20Kingdom&f_TPR=r604800&sortBy=DD").
             Without it, enumerates whatever search page the tab is already on.
  --scrolls  how many times to scroll the results pane to load more virtualised
             cards before enumerating (default 4). LinkedIn's list is virtualised —
             cards past the fold don't exist in the DOM until scrolled into view.
  --all      include jobs already in application-tracker.csv (default: EXCLUDE them,
             so you only get FRESH candidates — mirrors the WTTJ/Indeed feed scripts).
  hide <id>  click the card's "Dismiss <title> job" control so a COMPLETED or SKIPPED
             posting doesn't resurface in later searches (LinkedIn's own "We won't
             show you this job again"). Must be run on a results/search page with that
             card present — a job-DETAIL page has no dismiss control (go back to
             search results first). Do NOT hide `Blocked` postings — they're retryable.

**Dedup is done IN CODE.** Every numeric id already present anywhere in
application-tracker.csv (in a `/jobs/view/<id>` URL, any status) is filtered out
before the JSON is printed. If the result is `[]`, the search is genuinely exhausted
for that query — don't re-run it; mark it with
`sites/_common/scripts/board-cooldown.sh mark linkedin "<query>"` instead.

**Note on result quality, not just quantity:** LinkedIn interleaves promoted/
sponsored cards for completely unrelated roles (Senior Marketing Manager,
Solutions Architect, Co-Founder/CTO…) into the same card selector as real search
hits — confirmed live 2026-07-13. Tracker-dedup filters out already-known ids, but
it does NOT filter off-profile titles — that's still the caller's job (SKILL.md's
cheap pre-filter, loop-prompt.md §2). Don't assume every id this returns is
worth opening.
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
import check_title  # noqa: E402

BOARD = "linkedin"

# application-tracker.csv lives at the skill root (…/scripts -> linkedin -> sites -> root)
TRACKER = os.path.join(_here, "..", "..", "..", "application-tracker.csv")


def load_seen_ids():
    """Numeric LinkedIn job ids already in application-tracker.csv (any status).
    Parsed by regex over raw lines (not the csv module) so a malformed/quoted row
    can't blow this up. Mirrors welcometothejungle/scripts/feed.py's
    load_seen_ids() and indeed.com/scripts/feed.py's load_seen_jks() — same bug
    class (agent-side manual dedup missing already-tracked rows), same fix."""
    seen = set()
    try:
        with open(TRACKER, encoding="utf-8", errors="replace") as f:
            for line in f:
                for m in re.findall(r"linkedin\.com/jobs/view/(\d+)", line):
                    seen.add(m)
    except FileNotFoundError:
        pass
    return seen


ENUM = r"""
(() => {
  const out = new Map();
  for (const c of document.querySelectorAll('div.job-card-container[data-job-id], li[data-occludable-job-id]')) {
    const id = c.getAttribute('data-job-id') || c.getAttribute('data-occludable-job-id');
    if (!id || out.has(id)) continue;
    const a = c.querySelector('a.job-card-container__link, a.job-card-list__title, a[href*="/jobs/view/"]');
    const txt = s => { const e = c.querySelector(s); return e ? e.textContent.replace(/\s+/g,' ').trim() : ''; };
    out.set(id, {
      id,
      url: 'https://www.linkedin.com/jobs/view/' + id,
      title: (a ? a.textContent : '').replace(/\s+/g, ' ').trim(),
      company: txt('.job-card-container__primary-description, .artdeco-entity-lockup__subtitle'),
    });
  }
  return [...out.values()];
})()
"""


def _scroll_results(times):
    for _ in range(times):
        cfx.human_pause()
        try:
            cfx.post(f"/tabs/{cfx._tab()}/scroll",
                     {"userId": cfx._uid(), "direction": "down", "amount": 600})
        except cfx.CfxError:
            pass  # scrolling is best-effort enumeration aid, not load-bearing
        time.sleep(0.6)


def hide_job(job_id):
    """Click the card's 'Dismiss <title> job' button (verified working pattern,
    2026-07-13 — same LinkedIn UI action used manually all session). Must be run
    on a search-results/feed page where the card is rendered; job-detail pages
    don't have this control.

    LinkedIn's results list is virtualised: a card scrolled off-screen exists as a
    DOM node (data-job-id present) but its interactive children — including the
    Dismiss button — aren't rendered until it's scrolled near/into the viewport,
    and rendering isn't instant even after scrollIntoView (confirmed live
    2026-07-13: `[...card.querySelectorAll('button')]` returned `[]` immediately
    after scrollIntoView, then the real button a couple seconds later). So this
    scrolls the card into view itself first, then retries the button lookup a
    few times with a short wait between, instead of failing NO_DISMISS_BUTTON on
    the first miss."""
    res = None
    for attempt in range(4):
        res = cfx.evaluate(r"""
        (() => {
          const jid = %s;
          const card = document.querySelector('div.job-card-container[data-job-id="' + jid + '"], li[data-occludable-job-id="' + jid + '"]');
          if (!card) return 'CARD_NOT_FOUND';
          card.scrollIntoView({block: 'center'});
          const btn = [...card.querySelectorAll('button')].find(b => /^dismiss /i.test(b.getAttribute('aria-label') || ''));
          if (!btn) return 'NO_DISMISS_BUTTON';
          btn.click();
          return 'CLICKED';
        })()
        """ % json.dumps(job_id))
        if res == "CLICKED" or res == "CARD_NOT_FOUND":
            break
        time.sleep(1.0)  # give the virtualised card a moment to render its controls
    if res != "CLICKED":
        print(f"hide {job_id}: {res}")
        return 1
    time.sleep(1.5)
    confirmed = cfx.evaluate(r"""
    (() => {
      const jid = %s;
      const card = document.querySelector('div.job-card-container[data-job-id="' + jid + '"], li[data-occludable-job-id="' + jid + '"]');
      return card ? /won.t show you this job again/i.test(card.innerText || '') : true;
    })()
    """ % json.dumps(job_id))
    print(f"hide {job_id}: {'HIDDEN' if confirmed else 'clicked (unconfirmed — re-check)'}")
    return 0 if confirmed else 1


def hide_batch(job_ids, nav_url=None):
    """Dismiss MANY cards in ONE results-page visit (Tier-1 batch dismissals): navigate
    once (or reuse the current results page), then hide each id in-place. One visit
    instead of one nav per posting. `CARD_NOT_FOUND` for an id whose card isn't on this
    page is EXPECTED (virtualised/personalised results) and non-fatal — it's already
    tracker-deduped, so it can never be re-applied regardless. Returns 0 always (best-
    effort housekeeping); prints a per-id result line."""
    if nav_url:
        try:
            cfx.navigate(nav_url)
            time.sleep(3)
        except cfx.CfxError as e:
            print(f"hide-batch nav ERROR: {e}")
    hidden = other = 0
    for jid in job_ids:
        try:
            rc = hide_job(jid)
            if rc == 0:
                hidden += 1
            else:
                other += 1
        except cfx.CfxError as e:
            print(f"hide {jid}: ERROR {e}")
            other += 1
    print(f"hide-batch: {hidden} hidden, {other} unconfirmed/not-found of {len(job_ids)}",
          file=sys.stderr)
    return 0


def main():
    args = sys.argv[1:]
    if args and args[0] == "hide" and len(args) == 2:
        try:
            return hide_job(args[1])
        except cfx.CfxError as e:
            print(f"ERROR: {e}")
            return 2
    if args and args[0] == "hide-batch" and len(args) >= 2:
        # feed.py hide-batch <id1,id2,...|id1 id2 ...> [--nav <results url>]
        nav = args[args.index("--nav") + 1] if "--nav" in args and args.index("--nav") + 1 < len(args) else None
        raw = [a for a in args[1:] if not a.startswith("--") and a != nav]
        ids = [i for chunk in raw for i in chunk.split(",") if i.strip()]
        return hide_batch(ids, nav)

    scrolls = 4
    if "--scrolls" in args:
        try:
            scrolls = int(args[args.index("--scrolls") + 1])
        except (ValueError, IndexError):
            pass

    force = "--force" in args
    if "--nav" in args:
        try:
            url = args[args.index("--nav") + 1]
        except IndexError:
            print("ERROR nav: --nav needs a URL")
            return 2
        # COOLDOWN GATE — bail before any browser cost if this board+query is still dry
        # (LinkedIn's search term is the `keywords=` param). See board_cooldown.py.
        query = board_cooldown.query_from_url(url)
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
            print(f"[feed] searching LinkedIn: {url}", file=sys.stderr)
            cfx.navigate(url)
            time.sleep(3)
        except cfx.CfxError as e:
            print(f"ERROR nav: {e}")
            return 2

    try:
        _scroll_results(scrolls)
        rows = cfx.evaluate(ENUM)
    except cfx.CfxError as e:
        print(f"ERROR: {e}")
        return 2

    all_jobs = rows if isinstance(rows, list) else []
    if "--all" in args:
        jobs = all_jobs
    else:
        seen = load_seen_ids()
        jobs = [j for j in all_jobs if j["id"] not in seen]
    filtered = len(all_jobs) - len(jobs)

    # Annotate every job that has a real (non-blank) title with a deterministic
    # eligibility verdict against the FULL target-roles.md tier list — see
    # check_title.py's docstring for why this exists (a real gap: on-profile Tier
    # B/C postings like "Service Designer"/"UX Writer" were silently never logged
    # because the cheap title pre-filter was pure prose recall of ~90 titles across
    # 12 tiers, which in practice defaulted to only the ~7 literal search-query
    # phrases). Blank-title cards (the LinkedIn "Hire Feed" virtualization quirk)
    # still need opening individually — nothing to check_title against yet.
    for j in jobs:
        if j.get("title"):
            j["eligibility"] = check_title.check_title(j["title"])

    # Record this pass's fresh-count for adaptive cooldowns / preflight ordering
    # (both paths; skip a raw --all dump which isn't a real cooldown-keyed pass).
    query = board_cooldown.query_from_url(args[args.index("--nav") + 1]) if "--nav" in args else ""
    track = bool(query) and "--all" not in args
    if track:
        board_cooldown.record_yield(BOARD, query, len(jobs))

    print(json.dumps(jobs, ensure_ascii=False, indent=2))
    if jobs:
        print(f"\n{len(jobs)} FRESH jobs ({filtered} already in application-tracker.csv "
              f"filtered out). Screen titles before opening — this list still includes "
              f"off-profile promoted cards. Iterate each .url directly.", file=sys.stderr)
    else:
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
