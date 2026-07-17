#!/usr/bin/env python3
"""
pipeline.py — the WHOLE pre-apply phase in ONE model turn (Tier-1 speed lever).

WHY THIS EXISTS. The sourcing→screening funnel used to cost ~30 model round-trips per
firing: run preflight, then each feed, read its JSON into context, merge, precheck,
batch-screen, decide. Every feed's raw JSON (hundreds of cards) entered the model's
context just to be filtered by code anyway. This script runs that entire funnel as one
subprocess and returns to the model ONLY what needs a mind: the counts, the path to a
ready work-queue, and the `review` items whose location is genuinely ambiguous.

WHAT IT DOES (all in code, no model in the loop):
  1. search_plan.plan() — same verdict the checkpoint uses. Not WORK -> print verdict
     and exit with the matching code (nothing to source).
  2. For each clear search, in expected-yield order, run its board's feed.py (one tab,
     serialized — the documented camofox constraint). Feeds self-record yield + adaptive
     cooldown; pipeline just collects their card lists.
  3. merge_sources — union by canonical id, drop already-tracked.
  4. precheck — title/location/salary/dedup screen -> keep / review / drop.
  5. jd batch-screen every keep (and review) survivor (unless --no-screen), attaching a
     COMPACT jd payload (requirements + capped text + funnel/trap/location signals).
  6. Enrich each survivor with `family` (for per-family tailoring) and `ats_hint` +
     `apply_rank` (for success-ordered application), write them to queue.jsonl.
  7. Print a small JSON summary to STDOUT (counts, queue path, review items, errors);
     everything verbose goes to stderr.

USAGE (needs a live tab on the browser-driving path — CFX_KEY/CFX_TAB in env):
  CFX_KEY=… CFX_TAB=… python3 pipeline.py [--target N] [--no-screen]
      [--screen-limit N] [--force] [--boards linkedin,indeed] [-o queue.jsonl]

Exit codes: 0 WORK (queue written; may be empty) · 10 SLEEP · 11 HOLD · 12 DONE · 2 ERROR.
"""
import inspect
import json
import os
import subprocess
import sys
import time
from datetime import datetime

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _here)
import search_plan as sp        # noqa: E402
import board_cooldown as bc     # noqa: E402
import merge_sources            # noqa: E402
import precheck as pc           # noqa: E402
import fsutil                   # noqa: E402  (atomic + locked queue write, A.1)
import cfx                      # noqa: E402  (tab-death self-heal in run_feed)

_ROOT = sp._ROOT
QUEUE_DEFAULT = os.path.join(_ROOT, "queue.jsonl")

# board token (searches.csv) -> (feed dir under sites/, nav-arg builder)
FEEDS = {
    "linkedin": ("linkedin",           lambda nav: ["--nav", nav] if nav else []),
    "indeed":   ("indeed.com",         lambda nav: ["--nav", nav] if nav else []),
    "wttj":     ("welcometothejungle", lambda nav: []),
    # 2-arg builder: CSJ SIDs are one-shot + expiry-signed, so a parked nav dies. With a
    # blank nav the feed mints its own SID from --what, letting searches.csv carry one
    # row per family. Legacy --nav <SID> still honoured if a row supplies one.
    "csj":      ("civilservicejobs",   lambda nav, query: (["--nav", nav, "--all-pages"] if nav
                                                          else (["--what", query, "--all-pages"] if query
                                                                else ["--all-pages"]))),
    "hackney":  ("hackney",            lambda nav: ["--nav", nav] if nav else []),
    "adzuna":   ("adzuna.co.uk",       lambda nav: ["--nav", nav] if nav else []),
    "reed":     ("reed.co.uk",         lambda nav: (["--nav", nav, "--pages", "4"] if nav else ["--pages", "4"])),
    "thedots":  ("the-dots.com",       lambda nav: ["--nav", nav] if nav else []),
    "totaljobs":("totaljobs.com",      lambda nav: ["--nav", nav] if nav else []),
    "cwjobs":   ("totaljobs.com",      lambda nav: ["--nav", nav] if nav else []),  # StepStone sibling, same adapter (nav carries cwjobs.co.uk host)
    "guardian": ("jobs.theguardian.com", lambda nav: ["--nav", nav] if nav else []),
    "charityjob":("charityjob.co.uk",    lambda nav: ["--nav", nav] if nav else []),
    "escapecity":("escapethecity.org",   lambda nav: ["--nav", nav] if nav else []),  # purpose-driven board via its public Algolia index (browser-free)
    "thirdsector":("jp.thirdsector.co.uk", lambda nav: (["--nav", nav] if nav else ["--pages", "5"])),  # whole board is ~97 rows / 5 pages — sweep it all
    "cvlibrary":("cv-library.co.uk",     lambda nav: ["--nav", nav] if nav else []),
    "nhs":      ("jobs.nhs.uk",          lambda nav: ["--nav", nav] if nav else []),
    "mi5":      ("applicationtrack.com", lambda nav: ["--nav", nav] if nav else ["--tenant", "mi5"]),  # apply account-gated (noVNC oversight)
    "mi6":      ("applicationtrack.com", lambda nav: ["--nav", nav] if nav else ["--tenant", "mi6"]),  # apply account-gated (noVNC oversight)
    # ── IT / security / finance lanes ────────────────────────────────────────
    "jobserve": ("jobserve.com",         lambda nav: (["--nav", nav, "--pages", "3"] if nav else ["--pages", "3"])),  # huge UK IT inventory, contract-skewed
    "cybersecjobsite": ("cybersecurityjobsite.com", lambda nav: ["--nav", nav] if nav else []),  # niche cyber board (~87 live) — apply needs camofox
    "efinancial": ("efinancialcareers.co.uk", lambda nav: (["--nav", nav, "--pages", "3"] if nav else ["--pages", "3"])),  # 15/page, so sweep 3
    "hackajob": ("hackajob.com",         lambda nav: ["--nav", nav] if nav else []),  # ⚠️ DISCOVERY ONLY — rows are not applyable (profile-gated); see NOTES.md
    # ── design / creative / music lanes ──────────────────────────────────────
    # ⚠️ mbw/designweek/dezeen take NO --nav: their feeds consume an RSS/JSON endpoint, not the
    # human listing page, so handing them a searches.csv nav URL feeds HTML to a non-HTML parser
    # and silently yields 0 rows. They build their own URL from --what/--where; each board is
    # small enough that a full sweep is the correct pass anyway.
    "ifyoucould": ("ifyoucouldjobs.com", lambda nav: ["--nav", nav] if nav else []),  # It's Nice That's board — whole board is 1 page, no pagination
    "mbw":       ("musicbusinessworldwide.com", lambda nav: []),  # RSS job_feed; posts_per_page=100 = whole board in 1 GET
    "creativepool": ("creativepool.com", lambda nav: (["--nav", nav, "--pages", "4"] if nav else ["--pages", "4"])),  # 437 jobs @25/page — sweep 4
    "designweek": ("designweek.co.uk",   lambda nav: []),  # jm-ajax JSON (RSS keyword search is broken upstream) — see NOTES.md
    "dezeen":    ("dezeen.com",          lambda nav: ["--pages", "3"]),  # ⚠️ camofox-only (Cloudflare challenge); ~140 jobs @50/page
    "dribbble":  ("dribbble.com",        lambda nav: (["--nav", nav, "--pages", "2"] if nav else ["--pages", "2"])),  # ~69 jobs, remote-heavy
    # ── ATS-direct: employers' own boards, no aggregator in the middle ───────
    # ⭐ The highest-yield channel: every row is on an ATS that accepts an application with
    # NO ACCOUNT (greenhouse/lever/ashby/workable/smartrecruiters/recruitee), so it sidesteps
    # the downstream-employer-ATS wall that stops Adzuna/WTTJ/Dots at submit time. `ats_hint`
    # names the driver to use. Company universe: sites/ats-direct/companies.csv.
    "atsdirect": ("ats-direct",          lambda nav: []),   # filters are --what/--sector/--ats, not nav
    # ── academic / gov / public-sector portals ──────────────────────────────
    "jobsac":    ("jobs.ac.uk",          lambda nav: (["--nav", nav, "--pages", "2"] if nav else ["--pages", "2"])),  # unis: web/digital officer + IT/AV support
    "gchq":      ("gchq-careers.co.uk",  lambda nav: []),   # ⚠️ camofox-only: /api/search is Cloudflare-gated (facets are HTTP)
    # ⚠️ camofox-only: MHR iTrent SPA — list is client-rendered and fires NO xhr, so there is
    # nothing to intercept. Sweeps all 3 streams (pds/commons/lords); nav is meaningless.
    "parliament":("parliament.uk",       lambda nav: []),
    "jgp":       ("jobsgopublic.com",    lambda nav: ["--nav", nav] if nav else []),  # councils/housing/charities
    "lgjobs":    ("lgjobs.com",          lambda nav: ["--nav", nav] if nav else []),  # ⚠️ strict SUBSET of jgp (same Jobiqo index) — shares jgp's seen_pattern
    "apprentice":("findapprenticeship.service.gov.uk", lambda nav: ["--nav", nav] if nav else []),  # cyber/DevOps L4 — ask before a volume run
    "tfl":       ("tfl.gov.uk",          lambda nav: ["--nav", nav] if nav else []),  # SuccessFactors RMK; board is TfL+GLA+OPDC
    "bbc":       ("careers.bbc.co.uk",   lambda nav: []),   # POST API — a nav URL is meaningless here
    # ── aggregator APIs ─────────────────────────────────────────────────────
    "himalayas": ("himalayas.app",       lambda nav: ["--pages", "5"]),  # keyless JSON; no keyword search upstream, volume comes from --pages
    "talent":    ("talent.com",          lambda nav: (["--nav", nav, "--pages", "2"] if nav else ["--pages", "2"])),
    # Key-gated (feed exits 2 naming the exact ats-credentials.csv row + free signup URL):
    "reedapi":   ("reed.co.uk",          lambda nav: ["--nav", nav] if nav else [], "feed_api.py"),  # official API; distinct from the `reed` scraper
    "jooble":    ("jooble.org",          lambda nav: ["--nav", nav] if nav else []),
    "careerjet": ("careerjet.co.uk",     lambda nav: ["--nav", nav] if nav else []),
}

# ── family classifier (for per-family resume bases, Tier 2) ──────────────────
# Ordered: first hit wins. Keyed on lowercased title substrings.
_FAMILY_RULES = [
    ("research",  ("user research", "ux research", "researcher", "usability", "design research")),
    ("content",   ("content design", "content strateg", "ux writer", "service design", "content designer")),
    ("qa",        ("qa ", "quality assur", "test analyst", "software tester", "accessibility test",
                   "accessibility audit", "uat ", "tester")),
    ("support",   ("it support", "service desk", "desktop support", "technical support", "help desk",
                   "helpdesk", "application support", "1st line", "2nd line", "first line", "second line",
                   "computer repair", "field service", "deskside", "end user comput")),
    ("devops",    ("devops", "sre", "site reliability", "platform engineer", "infrastructure",
                   "linux", "systems admin", "sysadmin", "cloud engineer", "cloud support",
                   "soc analyst", "security analyst", "security operations", "network")),
    ("growth",    ("growth", "marketing", "cro ", "paid social", "performance market", "seo",
                   "social media", "digital marketing", "campaign")),
    ("digital",   ("digital officer", "digital communications", "digital content", "web editor",
                   "website editor", "web content", "digital engagement", "wordpress", "webflow")),
    ("product",   ("product owner", "product analyst", "product manager", "delivery", "business analyst",
                   "product operations")),
    ("ai",        ("prompt engineer", "ai trainer", "conversational", "chatbot", "ai product",
                   "genai", "machine learning", "annotation")),
    ("engineering", ("frontend", "front-end", "front end", "web developer", "ux engineer",
                     "design engineer", "design technologist", "creative technologist", "prototyp",
                     "engineer,")),
    ("design",    ("product designer", "ux designer", "ui designer", "interaction designer",
                   "digital designer", "web designer", "visual designer", "brand designer",
                   "design system", "accessibility designer", "mobile app designer", "designer")),
]


def family_of(title):
    t = (title or "").lower()
    for fam, keys in _FAMILY_RULES:
        if any(k in t for k in keys):
            return fam
    return "design"  # his default centre of gravity


# ── ATS hint + apply-success ranking (Tier 5 work-list ordering) ─────────────
# Lower rank = try first (more likely to complete autonomously, per per-ATS history +
# a static prior). Populated priors; refined by apply-stats.csv when present.
_ATS_PRIOR = {
    "linkedin-easyapply": 1, "wttj": 2, "ashby": 2, "greenhouse": 3, "lever": 3,
    "workable": 4, "smartrecruiters": 4, "csj-tal": 4, "external": 6, "workday": 8,
    "funnel": 9, "unknown": 5,
}


def ats_hint(url, board=""):
    u = (url or "").lower()
    if "linkedin.com/jobs" in u and board == "linkedin":
        return "linkedin-easyapply"  # refined at apply time if it's an external redirect
    for needle, hint in (
        ("ashbyhq.com", "ashby"), ("greenhouse.io", "greenhouse"), ("lever.co", "lever"),
        ("workable.com", "workable"), ("smartrecruiters.com", "smartrecruiters"),
        ("myworkdayjobs.com", "workday"), ("welcometothejungle", "wttj"),
        ("cshr.tal.net", "csj-tal"), ("civilservicejobs", "csj-tal"),
        ("recruitmentplatform.com", "external"),
    ):
        if needle in u:
            return hint
    return "external" if board in ("indeed", "csj", "hackney") else "unknown"


def _load_apply_stats():
    """apply-stats.csv (optional): ats,attempts,submitted -> success rate, refines the
    static prior so a driver that keeps failing sinks in the ordering."""
    path = os.path.join(_ROOT, "apply-stats.csv")
    stats = {}
    try:
        import csv
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                a = (row.get("ats") or "").strip()
                try:
                    att, sub = int(row.get("attempts", 0)), int(row.get("submitted", 0))
                except ValueError:
                    continue
                if a and att > 0:
                    stats[a] = sub / att
    except (FileNotFoundError, OSError):
        pass
    return stats


def apply_rank(hint, stats):
    base = _ATS_PRIOR.get(hint, 5)
    rate = stats.get(hint)
    if rate is not None:
        # blend: a proven-good ATS floats up, a proven-bad one sinks (±3).
        base = base - round((rate - 0.5) * 6)
    return base


# ── tolerant feed-stdout JSON parse (indeed prepends a non-JSON line) ────────
def _parse_feed_stdout(out):
    idx = out.find("[")
    if idx < 0:
        return []
    try:
        v = json.loads(out[idx:])
        return v if isinstance(v, list) else []
    except ValueError:
        # last resort: trim to the final ']'
        end = out.rfind("]")
        if end > idx:
            try:
                v = json.loads(out[idx:end + 1])
                return v if isinstance(v, list) else []
            except ValueError:
                return []
    return []


def _tab_dead():
    """True if the shared CFX_TAB no longer resolves (camofox restarted / tab closed) —
    the 410/500 'Tab not found' flake that silently zeroes a board's feed."""
    try:
        cfx.current_url()
        return False
    except Exception:
        return True


def _run_feed_once(cmd, board, timeout):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           env=os.environ, cwd=_ROOT)
    except subprocess.TimeoutExpired:
        return [], f"{board} feed timed out after {timeout}s"
    posts = _parse_feed_stdout(p.stdout or "")
    for x in posts:
        if isinstance(x, dict):
            x.setdefault("board", board)
            x.setdefault("source", board)
    err = None
    if not posts and p.returncode not in (0, 1, 3):
        tail = "\n".join((p.stderr or "").strip().splitlines()[-3:])
        err = f"{board} feed exit {p.returncode}: {tail}"
    return posts, err


def _build_args(argb, nav, query):
    """Call a FEEDS arg-builder with (nav) or (nav, query) depending on its arity.

    WHY: builders used to receive ONLY `nav`, so a board whose feed needs a *keyword*
    (rather than a parked search URL) could not be driven per-family from searches.csv —
    every family row produced the identical argv and re-sourced the same thing. That gap is
    exactly why agents hand-rolled family-loop orchestrators for CSJ. Two-arg builders now
    get the row's `query`; one-arg builders are untouched, so all pre-existing entries keep
    working unchanged.
    """
    try:
        n = len(inspect.signature(argb).parameters)
    except (TypeError, ValueError):
        n = 1
    return argb(nav, query) if n >= 2 else argb(nav)


def run_feed(board, nav, force, timeout=420, query=""):
    """Run one board's feed.py as a subprocess; return (postings, err_or_None).

    Tab-death self-heal: a dead camofox tab (410/500 'Tab not found') makes the feed exit
    non-zero and silently zeroes the board. Sourcing is an idempotent READ, so on such an
    error we reopen the tab via cfx.ensure_tab (which rewrites CFX_TAB in env for the retry
    subprocess) and re-run ONCE. Never applied to a mutating POST (double-submit risk)."""
    spec = FEEDS.get(bc.norm(board))
    if not spec:
        return [], f"no feed adapter for board {board!r}"
    # A spec is (subdir, argbuilder) or (subdir, argbuilder, script_name). The 3rd element
    # exists because a couple of domains ship TWO feeds — e.g. reed.co.uk has the browser
    # scraper `feed.py` AND the official-API `feed_api.py`. Without it, FEEDS could only
    # ever reach `feed.py` and the second feed was unroutable from the loop.
    subdir, argb = spec[0], spec[1]
    script = spec[2] if len(spec) > 2 else "feed.py"
    feed = os.path.join(_ROOT, "sites", subdir, "scripts", script)
    if not os.path.isfile(feed):
        return [], f"feed not found: {feed}"
    cmd = [sys.executable, feed] + _build_args(argb, nav, query) + (["--force"] if force else [])
    posts, err = _run_feed_once(cmd, board, timeout)
    if err and _tab_dead():                       # dead tab → reopen + retry ONCE (read-only)
        try:
            cfx.ensure_tab(persist=False)         # reopens + refreshes the CFX_TAB env var
            posts, err = _run_feed_once(cmd, board, timeout)
        except Exception:
            pass
    return posts, err


def run(target=None, no_screen=False, screen_limit=40, force=False,
        only_boards=None, out_path=None, now=None):
    """Importable funnel (F.2): run the WHOLE sourcing→screening pipeline in code and
    return (result, exit_code). `result` is the machine summary dict (verdict/counts/
    queue path/review items) on WORK, or {"verdict": …} on SLEEP/HOLD/DONE. queue.jsonl
    is written as a side effect. apply_queue.py / warm_queue.py call this instead of
    re-implementing sourcing/screening — that parallel-orchestrator re-implementation is
    the exact driver of the check_title-divergence class of bug (perf-roadmap root cause).
    `only_boards` is an iterable of board tokens (already split); None = all clear boards."""
    if target is None:
        env = os.environ.get("APPLY_TARGET")
        target = int(env) if (env and env.isdigit()) else sp.DEFAULT_TARGET
    only = {bc.norm(b) for b in only_boards} if only_boards else None
    out_path = out_path or QUEUE_DEFAULT

    now = now or datetime.now()
    r = sp.plan(now=now, target=target)
    verdict = r["verdict"]
    if verdict != "WORK":
        # Mirror the checkpoint's machine line so a caller can branch identically.
        summary = {"verdict": verdict}
        summary.update({k: r[k] for k in ("wake_at", "applied_today", "target")
                        if k in r})
        codes = {"SLEEP": 10, "HOLD": 11, "DONE": 12, "ERROR": 2}
        return summary, codes.get(verdict, 2)

    clear = r["clear"]
    if only:
        clear = [s for s in clear if bc.norm(s["board"]) in only]

    # C.8: load the work-list-ordering input ONCE, up front (off the post-feed
    # critical path). Cheap disk read; no concurrency risk on the read side.
    stats = _load_apply_stats()

    # ── 1) source every clear search (serialized: one tab) ───────────────────
    all_posts, errors, per_board = [], [], {}
    for s in clear:
        t0 = time.time()
        posts, err = run_feed(s["board"], s.get("nav", ""), force, query=s.get("query", ""))
        # C.7: one retry on a TRANSIENT feed error (never on a timeout — that would
        # double the tab cost). Feeds self-cooldown, so a flaky nav/consent hiccup
        # shouldn't zero a board's whole yield for the firing.
        if err and not posts and "timed out" not in err:
            posts, err2 = run_feed(s["board"], s.get("nav", ""), force, query=s.get("query", ""))
            if posts:
                err = None
            elif err2:
                err = err2
        per_board[s["board"]] = per_board.get(s["board"], 0) + len(posts)
        all_posts.extend(posts)
        if err:
            errors.append(err)
        print(f"  sourced {s['board']:<9} {len(posts):>3} cards in {time.time()-t0:4.0f}s"
              + (f"  ERR: {err}" if err else ""), file=sys.stderr)

    # ── 2) merge (dedup by canonical id) ─────────────────────────────────────
    # C.1: merge the in-memory list directly — no serialize-to-tmp + read-back of the
    # run's biggest blob. C.4: drop_tracked=False so precheck owns ALL tracker logic
    # and can route a tracked-Blocked posting to `review` (retry-if-cleared) instead of
    # it being silently dropped here first (the regression this restores).
    n_sourced = len(all_posts)
    merged, mstats = merge_sources.merge_lists(all_posts, drop_tracked=False)
    del all_posts  # C.2: free the raw-card blob before the minutes-long screen phase

    # ── 3) precheck (title/location/salary/dedup) ────────────────────────────
    screened = pc.precheck(merged)
    keeps, reviews, drops = screened["keep"], screened["review"], screened["drop"]
    survivors = keeps + reviews  # reviews still get screened; the model decides on them
    n_tracked_dropped = sum(1 for d in drops
                            if "already tracked" in (d.get("verdict_reason") or ""))

    # ── 4) jd batch-screen survivors, attach compact payload ─────────────────
    review_ids = {id(x) for x in reviews}   # C.3: O(1) membership, no deep dict-eq scan
    n_screened = 0
    if not no_screen and survivors:
        import jd  # imported late: pulls cfx (browser) — only needed when screening
        for i, c in enumerate(survivors):
            if i >= screen_limit:
                c["_screen_skipped"] = "screen-limit"
                continue
            url = c.get("url")
            if not url:
                continue
            try:
                data = jd.screen_one(url)
                # C.6: an under-rendered SPA shell yields a thin, misleading payload
                # (and jd.py refuses to cache it) — re-fetch once, cache-bypassed,
                # before trusting/queuing it. jd.py documents this "re-run once" flow.
                if not data.get("error") and (data.get("jd_text_full_len") or 0) < 300:
                    try:
                        data = jd.screen_one(url, use_cache=False)
                    except Exception:  # noqa: BLE001 — keep first payload if retry fails
                        pass
                c["jd"] = jd.compact(data)
                n_screened += 1
                # promote a review->drop if the JD's own signals settle location against it
                loc = (c["jd"] or {}).get("location_signals", {})
                if id(c) in review_ids and loc and not (loc.get("london") or loc.get("remote")) \
                        and loc.get("uk_city_other"):
                    c["verdict"] = "drop"
                    c["verdict_reason"] = ("JD location is a non-London UK city "
                                           f"({', '.join(loc['uk_city_other'][:2])}) — auto-dropped")
            except Exception as e:  # noqa: BLE001 — one bad posting must not sink the batch
                c["jd_error"] = str(e)

    # ── 5) enrich + write queue.jsonl ────────────────────────────────────────
    queue = []
    for c in survivors:
        if c.get("verdict") == "drop":
            continue  # auto-dropped during screening
        title = c.get("title") or ""
        hint = ats_hint(c.get("url"), bc.norm(c.get("board", "")))
        row = {
            "id": (c.get("id") or ""),
            "url": c.get("url"),
            "title": title,
            "company": c.get("company") or "",
            "location": c.get("location") or "",
            "board": c.get("board") or c.get("source") or "",
            "verdict": c.get("verdict", "keep"),
            "verdict_reason": c.get("verdict_reason", ""),
            "eligibility": c.get("eligibility"),
            "tier": (c.get("eligibility") or {}).get("tier"),
            "family": family_of(title),
            "ats_hint": hint,
            "apply_rank": apply_rank(hint, stats),
            "salary": c.get("salary"),
            "desired_salary": c.get("desired_salary"),
            "jd": c.get("jd"),
            "jd_error": c.get("jd_error"),
            # not silently dropped: a row past --screen-limit is queued UNSCREENED (jd=None);
            # mark it so the applier knows to `jd.py --nav` it before applying, not that it's
            # a jd_error or a real 0-field funnel.
            "screen_skipped": c.get("_screen_skipped"),
        }
        queue.append(row)
    # apply-success order: easiest ATS first, then higher tier, then family grouping
    tier_ord = {"A": 0, "B": 1, "C": 2, None: 3}
    queue.sort(key=lambda x: (x["apply_rank"], tier_ord.get(x["tier"], 3), x["family"]))

    # A.1: atomic + locked write so a concurrent firing (or the warm-queue daemon)
    # can never read a truncated/half-streamed queue.jsonl and conclude "no work".
    def _write_queue(f):
        for row in queue:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    with fsutil.file_lock(out_path):
        fsutil.atomic_write(out_path, _write_queue)

    # ── 6) compact result to STDOUT (this is all the model reads) ────────────
    # E.5: cap the per-item reason so a large review set can't bloat the model payload.
    review_items = [{"url": r_["url"], "title": r_["title"], "company": r_["company"],
                     "reason": (r_["verdict_reason"] or "")[:180]}
                    for r_ in queue if r_["verdict"] == "review"]
    result = {
        "verdict": "WORK",
        "queue": out_path,
        "counts": {
            "sourced": n_sourced, "per_board": per_board,   # C.2: all_posts freed
            "after_merge": mstats["out"], "tracked_dropped": n_tracked_dropped,  # C.4
            "keep": sum(1 for q in queue if q["verdict"] == "keep"),
            "review": len(review_items),
            "dropped_precheck": len(drops),
            "screened": n_screened,
            # survivors past --screen-limit, queued UNSCREENED — surfaced so a cap never
            # reads as "screened everything"; re-run with a higher --screen-limit or
            # jd.py --nav them individually before applying.
            "screen_capped": sum(1 for c in survivors if c.get("_screen_skipped") == "screen-limit"),
            "queued": len(queue),
        },
        "review": review_items,
        "errors": errors,
        "applied_today": r.get("applied_today"), "target": target,
    }
    _capped = result["counts"]["screen_capped"]
    print(f"pipeline: {len(queue)} queued ({result['counts']['keep']} keep, "
          f"{len(review_items)} review) -> {out_path}; "
          f"{len(drops)} dropped, {n_tracked_dropped} already-tracked, "
          f"{n_screened} screened. {len(errors)} feed error(s)."
          + (f" ⚠️ {_capped} queued UNSCREENED past --screen-limit={screen_limit}."
             if _capped else ""), file=sys.stderr)
    return result, 0


def main():
    argv = sys.argv[1:]

    def flag(name):
        return name in argv

    def opt(name, default=None, cast=str):
        if name in argv:
            i = argv.index(name)
            if i + 1 < len(argv):
                try:
                    return cast(argv[i + 1])
                except ValueError:
                    return default
        return default

    only_boards = opt("--boards", None)
    result, code = run(
        target=opt("--target", None, int),
        no_screen=flag("--no-screen"),
        screen_limit=opt("--screen-limit", 40, int),
        force=flag("--force"),
        only_boards=only_boards.split(",") if only_boards else None,
        out_path=opt("-o", QUEUE_DEFAULT),
    )
    print(json.dumps(result, ensure_ascii=False))  # E.5: no indent on the machine line
    if result.get("verdict") != "WORK":
        print(f"pipeline: verdict={result.get('verdict')} (nothing to source)", file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
