#!/usr/bin/env python3
"""
feed.py — enumerate distinct job postings from the WTTJ app feed.

WHY THIS EXISTS (the anti-loop fix): WTTJ's app is NOT a list-model board like
Indeed. Navigating to `/jobs` does NOT show a browsable list — it auto-opens the
top recommended job and rewrites the URL to `/jobs/<id>` (see NOTES.md). An agent
that treats `/jobs` as a list keeps re-navigating there, gets the SAME top job
every time, and spins forever (observed: an hour bouncing on `/jobs/NSPehZ_f`).
This returns a concrete, de-duplicated list of {id, url, title, sources} so the
driver iterates REAL distinct postings by navigating straight to each `/jobs/<id>`
— never touching the ambiguous `/jobs` route again.

TWO SOURCES OF JOBS ("carousel expansion"):
  * **Home dashboard** (`app.welcometothejungle.com/`) — the user's pipeline +
    inline cards (`[data-testid=preview-card]` anchors). source="home".
  * **Themed feed routes** — WTTJ has NO horizontal carousels (verified: no
    overflow containers, no "See all", no infinite scroll). Instead each themed
    feed is its own route `/jobs?theme=<name>` (e.g. fully-remote, recently-funded,
    newly-added, has-salaries, female-leaders, apply-via-otta). Visiting one is
    the real equivalent of "expanding that carousel". CAVEAT: a theme route ALSO
    auto-opens just its TOP job (same SPA behavior as /jobs), so each theme
    contributes its single top pick — but that pick is a FRESH recommendation
    distinct from the home pipeline (e.g. fully-remote -> "Product Manager,
    CharlieHR"). Harvesting all themes therefore multiplies the fresh-lead pool.
    We deliberately do NOT click the in-app "Move"/skip control to walk deeper
    into a theme — that mutates the user's real recommendation/seen state.

Usage:
    CFX_KEY=... CFX_TAB=... python3 feed.py [--home-only] [--themes a,b,c] [--scrolls N] [--all] [--force]
    CFX_KEY=... CFX_TAB=... python3 feed.py id      # print canonical id/URL of the open job

  id           print `<id>\t<url>` for the WTTJ job currently open in the tab (robust
               multi-source extractor). Run this at LOG time so every WTTJ tracker row
               carries a stable `/jobs/<id>` — the exact thing dedup needs to filter it
               out next run. Fixes the historical "no stable job URL captured" rows that
               resurfaced forever. Prints `NO_ID` + exit 1 if none is extractable.
  --force      re-source even if this board's exhaustion cooldown is still active.
  --home-only  skip theme harvesting (just the home dashboard; fast).
  --themes     comma-separated theme names to harvest, overriding auto-discovery.
  --scrolls N  scroll the home page N times (default 6) to load its cards.
  --all        include jobs already in application-tracker.csv (default: EXCLUDE
               them, so you only get FRESH candidates).

Prints a JSON array of {"id","url","title","sources"} of FRESH jobs (not yet in
the tracker). **If it returns [] the WTTJ feed is exhausted for this profile —
do NOT keep re-walking the carousel; move to another board (Indeed/LinkedIn).**
By default already-tracked ids are filtered out precisely so the carousel stops
re-surfacing jobs that were already Applied/Skipped/Blocked (the #1 cause of the
"goes through the carousel forever, never applies" failure).
"""
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "_common", "scripts"))
import cfx  # noqa: E402
import board_cooldown  # noqa: E402

BOARD = "wttj"
# WTTJ is homepage/carousel driven, not a keyword search, so its cooldown key is a
# single fixed slug ("home") rather than a per-query one.
QUERY = "home"

APP = "https://app.welcometothejungle.com"
HOME = APP + "/"
# application-tracker.csv lives at the skill root (…/scripts -> welcometothejungle -> sites -> root)
TRACKER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "application-tracker.csv")


def load_seen_ids():
    """Job ids already in application-tracker.csv (any status). Parsed by regex,
    not the csv module, so malformed/broken rows don't blow up — we only need
    the `/jobs/<id>` tokens. This is what stops the carousel from re-surfacing a
    job that was already Applied/Skipped/Blocked (the `?theme=`/`?query=` params
    it appends otherwise defeat URL-based dedup)."""
    seen = set()
    try:
        with open(TRACKER, encoding="utf-8", errors="replace") as f:
            for line in f:
                for m in re.findall(r"/jobs/([A-Za-z0-9_-]+)", line):
                    seen.add(m)
    except FileNotFoundError:
        pass
    return seen

# Fallback if none are discoverable from the home DOM (the app has shipped these
# consistently). Auto-discovery from the live page takes precedence.
DEFAULT_THEMES = [
    "apply-via-otta", "newly-added", "fully-remote",
    "recently-funded", "has-salaries", "female-leaders",
]

# Enumerate every distinct /jobs/<id> anchor on the CURRENT page with a title.
ENUM_EXPR = r"""
(() => {
  const seen = new Map();
  const strip = t => (t || "").replace(/\s+/g, " ")
      .replace(/\b(View|Apply|Move|Save|Not interested|Shortlist)\b/gi, " ")
      .replace(/\s+/g, " ").trim();
  for (const a of document.querySelectorAll('a[href*="/jobs/"]')) {
    const id = ((a.getAttribute("href") || "").split("/jobs/")[1] || "").split(/[?#\/]/)[0];
    if (!id || id === "company" || seen.has(id)) continue;
    const card = a.closest('[data-testid=preview-card]') || a.closest('[data-testid=job-card-v2]');
    seen.set(id, card ? strip(card.innerText) : strip(a.textContent));
  }
  return [...seen].map(([id, title]) => ({ id, title }));
})()
"""

# Robust canonical-id extractor for whatever WTTJ job is currently displayed.
# WHY MULTI-SOURCE: on a theme route WTTJ often shows the job as an overlay while
# `location.pathname` is still `/jobs` (or `/jobs?theme=…`) with NO id in the path —
# a single pathname read then returns "" and the job gets logged as "no stable job URL
# captured", which permanently defeats dedup (it can never be filtered out again). We
# try, in order: the URL path, the canonical <link>, og:url, any /jobs/<id> anchor on
# the page (apply/share CTAs carry it), and data-* id attributes. First hit wins.
JOB_ID_EXPR = r"""
(() => {
  const RE = /\/jobs\/([A-Za-z0-9_-]+)/;
  const bad = new Set(["company", "search", "new", ""]);
  const pick = s => { const m = (s || "").match(RE); const id = m && m[1];
                      return (id && !bad.has(id)) ? id : null; };
  let id = pick(location.pathname);
  if (!id) { const c = document.querySelector('link[rel=canonical]'); id = c && pick(c.href); }
  if (!id) { const o = document.querySelector('meta[property="og:url"]'); id = o && pick(o.getAttribute("content")); }
  if (!id) {
    for (const a of document.querySelectorAll('a[href*="/jobs/"]')) {
      id = pick(a.getAttribute("href")); if (id) break;
    }
  }
  if (!id) {
    const d = document.querySelector('[data-job-id],[data-jobid],[data-testid=job-page]');
    id = d && (d.getAttribute("data-job-id") || d.getAttribute("data-jobid")
               || pick(d.getAttribute("href") || ""));
  }
  const t = (document.querySelector("[data-testid=job-title]")
            || document.querySelector("h1") || {}).textContent || "";
  return { id: id || "", title: t.replace(/\s+/g, " ").trim() };
})()
"""

# Back-compat alias — harvest_theme reads the auto-opened top pick via the same robust
# extractor now (was a pathname-only read that silently produced id-less jobs).
OPENED_EXPR = JOB_ID_EXPR

# Theme-route hrefs present on the home page (e.g. "/jobs?theme=fully-remote").
DISCOVER_THEMES_EXPR = r"""
[...new Set([...document.querySelectorAll('a[href*="theme="]')]
  .map(a => a.getAttribute("href")).filter(Boolean))]
"""


def _add(pool, id_, title, source):
    if not id_ or id_ == "company":
        return
    entry = pool.setdefault(id_, {"id": id_, "url": f"{APP}/jobs/{id_}", "title": "", "sources": []})
    if title and len(title) > len(entry["title"]):
        entry["title"] = title
    if source not in entry["sources"]:
        entry["sources"].append(source)


def enumerate_home(pool, scrolls):
    for _ in range(max(0, scrolls)):
        try:
            cfx.post(f"/tabs/{cfx._tab()}/scroll",
                     {"userId": cfx._uid(),
                      "direction": "down", "amount": 1200})
        except cfx.CfxError:
            break
        time.sleep(1.0)
    for j in (cfx.evaluate(ENUM_EXPR) or []):
        _add(pool, j.get("id"), j.get("title"), "home")


def discover_theme_hrefs():
    hrefs = cfx.evaluate(DISCOVER_THEMES_EXPR)
    return [h for h in hrefs if isinstance(h, str) and "theme=" in h] if isinstance(hrefs, list) else []


def harvest_theme(pool, href, label):
    """Navigate to a theme route and capture its auto-opened top job."""
    url = href if href.startswith("http") else APP + (href if href.startswith("/") else "/jobs?theme=" + href)
    cfx.navigate(url)
    time.sleep(4)
    opened = cfx.evaluate(OPENED_EXPR)
    if isinstance(opened, dict):
        if not opened.get("id"):
            # Visible, not silent: a theme that shows a job we can't id would otherwise
            # be logged id-less and evade dedup forever. Skip it and say so.
            print(f"(theme {label}: opened job had NO extractable id "
                  f"({opened.get('title','?')!r}) — skipped to avoid an un-dedupable "
                  f"tracker row)", file=sys.stderr)
        _add(pool, opened.get("id"), opened.get("title"), f"theme:{label}")


def current_job_id():
    """Print the canonical id + URL of the WTTJ job currently open in the tab, via the
    robust multi-source extractor. USE THIS at log time so every WTTJ tracker row carries
    a stable `/jobs/<id>` URL — the thing that lets dedup filter it out next run. Prints
    `NO_ID` + exit 1 if nothing is extractable (then don't log a bare/id-less URL —
    re-open the posting from its canonical link first)."""
    res = cfx.evaluate(JOB_ID_EXPR)
    jid = (res or {}).get("id") if isinstance(res, dict) else ""
    if not jid:
        print("NO_ID: no /jobs/<id> extractable from the current page. Re-open the "
              "posting from its canonical URL before logging — do NOT write an id-less "
              "row (it can never be deduped).", file=sys.stderr)
        print("NO_ID")
        return 1
    print(f"{jid}\t{APP}/jobs/{jid}")
    return 0


def theme_label(href):
    # "/jobs?theme=fully-remote" -> "fully-remote"
    if "theme=" in href:
        return href.split("theme=")[1].split("&")[0]
    return href


def main():
    args = sys.argv[1:]
    if args and args[0] == "id":
        # `feed.py id` — print the canonical id/URL of the job open in the tab, for the
        # logging step. Keeps every WTTJ tracker row dedupable (no more id-less rows).
        try:
            return current_job_id()
        except cfx.CfxError as e:
            print(f"ERROR: {e}")
            return 2
    home_only = "--home-only" in args
    include_all = "--all" in args
    scrolls = 6
    if "--scrolls" in args:
        try:
            scrolls = int(args[args.index("--scrolls") + 1])
        except (ValueError, IndexError):
            pass
    override_themes = None
    if "--themes" in args:
        try:
            override_themes = [t.strip() for t in args[args.index("--themes") + 1].split(",") if t.strip()]
        except IndexError:
            pass

    force = "--force" in args
    # COOLDOWN GATE — bail before touching the browser if the WTTJ feed was already
    # confirmed dry this window. Same automatic enforcement as the Indeed/LinkedIn feeds.
    if not force and not include_all:
        rem = board_cooldown.remaining_hours(BOARD, QUERY)
        if rem > 0:
            print("[]")
            print(f"\nCOOLDOWN: WTTJ feed was already confirmed exhausted "
                  f"({rem:.1f}h remaining). Skipped WITHOUT re-walking the carousel — no "
                  f"new candidates to expect. Move to another board, or pass --force to "
                  f"re-source anyway.", file=sys.stderr)
            sys.exit(3)

    pool = {}
    try:
        cfx.navigate(HOME)
        time.sleep(4)  # let the dashboard render
        enumerate_home(pool, scrolls)

        if not home_only:
            if override_themes is not None:
                theme_hrefs = ["/jobs?theme=" + t for t in override_themes]
            else:
                theme_hrefs = discover_theme_hrefs() or ["/jobs?theme=" + t for t in DEFAULT_THEMES]
            for href in theme_hrefs:
                try:
                    harvest_theme(pool, href, theme_label(href))
                except cfx.CfxError as e:
                    print(f"(theme {theme_label(href)} skipped: {e})", file=sys.stderr)
    except cfx.CfxError as e:
        print(f"ERROR: {e}")
        sys.exit(2)

    all_jobs = list(pool.values())
    seen = set() if include_all else load_seen_ids()
    jobs = [j for j in all_jobs if j["id"] not in seen]
    filtered = len(all_jobs) - len(jobs)

    print(json.dumps(jobs, ensure_ascii=False, indent=2))

    if not all_jobs:
        print("(no job cards found — confirm you're logged in and on the app "
              "dashboard, NOT the www marketing site.)", file=sys.stderr)
        sys.exit(1)
    if not include_all:
        board_cooldown.record_yield(BOARD, QUERY, len(jobs))
    if not jobs:
        marked = ""
        if not include_all:
            hrs = board_cooldown.adaptive_hours(BOARD, QUERY)
            until = board_cooldown.mark(BOARD, QUERY, hours=hrs)
            marked = f" Auto-marked WTTJ on cooldown until {until} ({hrs:.0f}h, adaptive)."
        print(f"\nEXHAUSTED: all {len(all_jobs)} jobs in the WTTJ feed are already in "
              f"application-tracker.csv.{marked} Do NOT re-walk the carousel — move to "
              f"another board (Indeed/LinkedIn).", file=sys.stderr)
        sys.exit(3)  # distinct code so the driver can branch on "site exhausted"
    theme_fresh = sum(1 for j in jobs if any(s.startswith("theme:") for s in j["sources"]))
    print(f"\n{len(jobs)} FRESH jobs ({theme_fresh} from theme feeds; {filtered} already-"
          f"tracked filtered out). Iterate each .url directly; do NOT go back to /jobs.",
          file=sys.stderr)


if __name__ == "__main__":
    try:
        import stagetimer  # _common/scripts is on sys.path; no-op unless STAGETIMER set
        _src = stagetimer.timed("source")
    except Exception:
        import contextlib
        _src = contextlib.nullcontext()
    with _src:
        main()
