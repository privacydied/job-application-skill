#!/usr/bin/env python3
"""feed.py — source jobs straight from employers' ATS job-board APIs (no job board at all).

WHY THIS IS THE HIGHEST-LEVERAGE FEED
-------------------------------------
Every aggregator channel (Adzuna / WTTJ / The Dots) sources fine and then dies at the
**downstream employer-ATS account wall** — you find the job, click Apply, and hit a login
for an ATS you have no account on. This feed inverts that: it sources *directly from the
ATSes this skill already knows how to submit to*, all of which are **account-less** —
Greenhouse, Lever, Ashby, Workable, SmartRecruiters and Recruitee all accept an
application from a cold visitor with no login.

So every posting this returns is, by construction, submittable with a driver that already
ships here (`sites/greenhouse|lever|ashbyhq|workable|smartrecruiters|recruitee/`), and the
`ats_hint` field names the exact driver. It also beats the boards on freshness: a role
appears on the company's ATS days before it propagates to LinkedIn/Indeed.

Each ATS exposes a public, **keyless** JSON listing endpoint:
    greenhouse       boards-api.greenhouse.io/v1/boards/<slug>/jobs?content=true
    lever            api.lever.co/v0/postings/<slug>?mode=json
    ashby            api.ashbyhq.com/posting-api/job-board/<slug>
    workable         apply.workable.com/api/v1/widget/accounts/<slug>
    smartrecruiters  api.smartrecruiters.com/v1/companies/<slug>/postings
    recruitee        <slug>.recruitee.com/api/offers/

The company universe lives in `companies.csv` (slug,ats,name,sector) next to this script —
edit that to change who is watched. Slugs are verified live; a dead slug is skipped with a
warning, never a hard failure.

Usage:
    python3 feed.py [--what "<terms>"] [--where London] [--all] [--force]
                    [--ats greenhouse,ashby] [--sector music,fintech] [--companies a,b]
                    [--remote] [--max-companies N] [--list-companies] [--verify]

  --what     free-text filter over titles (space-separated terms = OR; quoted phrase =
             substring). Omit to return every on-location posting.
  --where    location substring filter (default London; "" disables). Remote-flagged
             postings always pass.
  --remote   remote-only.
  --ats      restrict to given ATS platforms.
  --sector   restrict to companies.csv sectors (e.g. music, fintech, gov, design).
  --verify   probe every slug and report which are alive (maintenance helper).

No browser and no credentials — pure HTTPS GETs. Runs anywhere (Hermes cron, CI, Claude
Code) with no CFX_KEY.
"""
import concurrent.futures as futures
import csv
import json
import os
import re
import sys

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_here, "..", "..", "_common", "scripts"))
import board_cooldown  # noqa: E402
import httpfeed  # noqa: E402
from precheck import load_seen  # noqa: E402

BOARD = "atsdirect"
NAME = "ATS-direct"
COMPANIES = os.path.join(_here, "..", "companies.csv")
TRACKER = os.path.join(_here, "..", "..", "..", "application-tracker.csv")

# Tracker id regex: this feed's ids are "<ats>:<slug>:<jobid>", and the tracker holds the
# posting URL, so match every supported ATS's canonical job URL shape.
SEEN_PATTERN = (r"(?:boards\.greenhouse\.io/[^/\s,]+/jobs/(\d+)"
                r"|job-boards\.greenhouse\.io/[^/\s,]+/jobs/(\d+)"
                r"|jobs\.lever\.co/[^/\s,]+/([0-9a-f-]{36})"
                r"|jobs\.ashbyhq\.com/[^/\s,]+/([0-9a-f-]{36})"
                r"|apply\.workable\.com/[^/\s,]+/j/([0-9A-F]{8,})"
                r"|jobs\.smartrecruiters\.com/[^/\s,]+/(\d{6,})"
                r"|([a-z0-9-]+)\.recruitee\.com/o/)")


# ── company registry ─────────────────────────────────────────────────────────
def load_companies(path=COMPANIES):
    """Rows of {slug, ats, name, sector} from companies.csv. Blank lines and `#` ignored."""
    out = []
    try:
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(l for l in f if l.strip() and not l.startswith("#")):
                slug = (row.get("slug") or "").strip()
                ats = (row.get("ats") or "").strip().lower()
                if not slug or not ats:
                    continue
                out.append({"slug": slug, "ats": ats,
                            "name": (row.get("name") or slug).strip(),
                            "sector": (row.get("sector") or "").strip().lower()})
    except FileNotFoundError:
        pass
    return out


# ── per-ATS listing endpoints + row normalisers (pure — unit-tested) ─────────
def _u(*parts):
    return "".join(parts)


def gh_url(slug):
    return f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=false"


def gh_rows(payload, co):
    for j in httpfeed.jsonpath(payload, "jobs", default=[]) or []:
        jid = str(j.get("id") or "")
        if not jid:
            continue
        yield {
            "id": f"greenhouse:{co['slug']}:{jid}",
            "url": j.get("absolute_url") or f"https://job-boards.greenhouse.io/{co['slug']}/jobs/{jid}",
            "title": httpfeed.clean(j.get("title")),
            "company": co["name"],
            "location": httpfeed.clean(httpfeed.jsonpath(j, "location", "name")),
            "salary": "",
            "created": (j.get("updated_at") or "")[:10],
            "ats_hint": "greenhouse",
        }


def lv_url(slug):
    return f"https://api.lever.co/v0/postings/{slug}?mode=json"


def lv_rows(payload, co):
    for j in (payload if isinstance(payload, list) else []):
        jid = str(j.get("id") or "")
        if not jid:
            continue
        cat = j.get("categories") or {}
        yield {
            "id": f"lever:{co['slug']}:{jid}",
            "url": j.get("hostedUrl") or f"https://jobs.lever.co/{co['slug']}/{jid}",
            "title": httpfeed.clean(j.get("text")),
            "company": co["name"],
            "location": httpfeed.clean(cat.get("location")),
            "salary": httpfeed.clean(cat.get("commitment") or ""),
            "created": "",
            "ats_hint": "lever",
        }


def ab_url(slug):
    return f"https://api.ashbyhq.com/posting-api/job-board/{slug}"


def ab_rows(payload, co):
    for j in httpfeed.jsonpath(payload, "jobs", default=[]) or []:
        jid = str(j.get("id") or "")
        if not jid:
            continue
        comp = j.get("compensation") or {}
        yield {
            "id": f"ashby:{co['slug']}:{jid}",
            "url": j.get("jobUrl") or f"https://jobs.ashbyhq.com/{co['slug']}/{jid}",
            "title": httpfeed.clean(j.get("title")),
            "company": co["name"],
            "location": httpfeed.clean(j.get("location")),
            "salary": httpfeed.clean(httpfeed.jsonpath(comp, "compensationTierSummary") or ""),
            "created": (j.get("publishedAt") or "")[:10],
            "ats_hint": "ashby",
            "_remote": bool(j.get("isRemote")),
        }


def wk_url(slug):
    return f"https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true"


def wk_rows(payload, co):
    for j in httpfeed.jsonpath(payload, "jobs", default=[]) or []:
        short = str(j.get("shortcode") or "")
        if not short:
            continue
        loc = " ".join(x for x in [j.get("city"), j.get("country")] if x)
        yield {
            "id": f"workable:{co['slug']}:{short}",
            "url": j.get("url") or j.get("application_url") or f"https://apply.workable.com/{co['slug']}/j/{short}/",
            "title": httpfeed.clean(j.get("title")),
            "company": co["name"],
            "location": httpfeed.clean(loc),
            "salary": "",
            "created": (j.get("published_on") or "")[:10],
            "ats_hint": "workable",
            "_remote": bool(j.get("telecommuting")),
        }


def sr_url(slug):
    return f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100"


def sr_rows(payload, co):
    for j in httpfeed.jsonpath(payload, "content", default=[]) or []:
        jid = str(j.get("id") or "")
        if not jid:
            continue
        loc = httpfeed.jsonpath(j, "location", "city") or ""
        yield {
            "id": f"smartrecruiters:{co['slug']}:{jid}",
            "url": (f"https://jobs.smartrecruiters.com/{co['slug']}/"
                    f"{jid}"),
            "title": httpfeed.clean(j.get("name")),
            "company": co["name"],
            "location": httpfeed.clean(loc),
            "salary": "",
            "created": (j.get("releasedDate") or "")[:10],
            "ats_hint": "smartrecruiters",
            "_remote": bool(httpfeed.jsonpath(j, "location", "remote")),
        }


def rc_url(slug):
    return f"https://{slug}.recruitee.com/api/offers/"


def rc_rows(payload, co):
    for j in httpfeed.jsonpath(payload, "offers", default=[]) or []:
        jid = str(j.get("id") or "")
        if not jid:
            continue
        yield {
            "id": f"recruitee:{co['slug']}:{jid}",
            "url": j.get("careers_url") or j.get("careers_apply_url") or "",
            "title": httpfeed.clean(j.get("title")),
            "company": co["name"],
            "location": httpfeed.clean(j.get("location") or j.get("city") or ""),
            "salary": "",
            "created": (j.get("published_at") or "")[:10],
            "ats_hint": "recruitee",
            "_remote": str(j.get("remote") or "").lower() in ("true", "1"),
        }


ATS = {
    "greenhouse":      (gh_url, gh_rows),
    "lever":           (lv_url, lv_rows),
    "ashby":           (ab_url, ab_rows),
    "workable":        (wk_url, wk_rows),
    "smartrecruiters": (sr_url, sr_rows),
    "recruitee":       (rc_url, rc_rows),
}


# ── filtering (pure — unit-tested) ───────────────────────────────────────────
REMOTE_RE = re.compile(r"\b(remote|anywhere|work from home|wfh|distributed|home[- ]based)\b", re.I)


def is_remote(job):
    return bool(job.get("_remote")) or bool(REMOTE_RE.search(job.get("location") or ""))


def match_where(job, where):
    """London-or-remote gate. Empty `where` disables. Remote always passes (he can do it
    from London); an empty location string passes too (many ATS rows omit it and the JD
    screen catches those later) — a false negative here silently loses real inventory."""
    if not where:
        return True
    if is_remote(job):
        return True
    loc = (job.get("location") or "").strip()
    if not loc:
        return True
    return where.lower() in loc.lower()


def match_what(job, what):
    """Free-text title filter. A quoted phrase is a substring test; otherwise ANY
    whitespace-separated term matching is a hit (OR), matching how the board feeds treat
    their bundled OR-queries."""
    if not what:
        return True
    title = (job.get("title") or "").lower()
    w = what.strip()
    if len(w) > 1 and w[0] == w[-1] and w[0] in "\"'":
        return w[1:-1].lower() in title
    terms = [t for t in re.split(r'\s*(?:\bOR\b|,)\s*|\s+', w) if t]
    return any(t.strip('"\'').lower() in title for t in terms)


# ── fetch ────────────────────────────────────────────────────────────────────
def fetch_company(co, timeout=15):
    """(rows, error) for one company. Never raises — a dead slug must not kill the pass."""
    spec = ATS.get(co["ats"])
    if not spec:
        return [], f"unknown ats {co['ats']!r}"
    url_fn, rows_fn = spec
    try:
        text = httpfeed.http_get(url_fn(co["slug"]),
                                 headers={"Accept": "application/json"}, timeout=timeout)
        payload = json.loads(text)
    except httpfeed.FetchError as e:
        return [], str(e)
    except ValueError:
        return [], "bad JSON"
    try:
        return list(rows_fn(payload, co)), ""
    except Exception as e:
        return [], f"parse: {e}"


def harvest(companies, workers=12):
    """Pull every company's postings concurrently. Returns (jobs, dead_slugs)."""
    jobs, dead = [], []
    with futures.ThreadPoolExecutor(max_workers=workers) as ex:
        fut = {ex.submit(fetch_company, c): c for c in companies}
        for f in futures.as_completed(fut):
            co = fut[f]
            try:
                rows, err = f.result()
            except Exception as e:
                rows, err = [], str(e)
            if err:
                dead.append(f"{co['ats']}/{co['slug']}: {err}")
            jobs.extend(rows)
    return jobs, dead


def main():
    args = sys.argv[1:]

    def opt(name, default=None):
        return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else default

    def listopt(name):
        v = opt(name)
        return [x.strip().lower() for x in v.split(",") if x.strip()] if v else []

    what = opt("--what") or ""
    where = opt("--where")
    where = "London" if where is None else where
    remote_only = "--remote" in args
    force = "--force" in args or "--all" in args
    include_tracked = "--all" in args

    companies = load_companies()
    if not companies:
        print(f"ERROR: no companies in {COMPANIES}", file=sys.stderr)
        return 2

    if "--list-companies" in args:
        for c in companies:
            print(f"{c['ats']:16} {c['slug']:28} {c['sector']:12} {c['name']}")
        print(f"\n{len(companies)} companies watched.", file=sys.stderr)
        return 0

    ats_f, sec_f, co_f = listopt("--ats"), listopt("--sector"), listopt("--companies")
    if ats_f:
        companies = [c for c in companies if c["ats"] in ats_f]
    if sec_f:
        companies = [c for c in companies if any(s in c["sector"].split("|") for s in sec_f)]
    if co_f:
        companies = [c for c in companies if c["slug"].lower() in co_f]
    try:
        cap = int(opt("--max-companies", "0"))
        if cap > 0:
            companies = companies[:cap]
    except ValueError:
        pass

    if "--verify" in args:
        alive, dead = [], []
        for c in companies:
            rows, err = fetch_company(c)
            (dead if err else alive).append(f"{c['ats']}/{c['slug']}"
                                            + (f" — {err}" if err else f" — {len(rows)} jobs"))
        print("ALIVE:\n  " + "\n  ".join(alive))
        print("\nDEAD:\n  " + "\n  ".join(dead) if dead else "\nDEAD: none")
        print(f"\n{len(alive)}/{len(companies)} slugs alive.", file=sys.stderr)
        return 0

    query = what or "all"
    if not force:
        rem = board_cooldown.remaining_hours(BOARD, query)
        if rem > 0:
            print("[]")
            print(f"\nCOOLDOWN: {BOARD}/{query!r} confirmed exhausted ({rem:.1f}h remaining). "
                  f"--force to override.", file=sys.stderr)
            return 1

    raw, dead = harvest(companies)

    pool = {}
    for j in raw:
        if not match_what(j, what):
            continue
        if remote_only and not is_remote(j):
            continue
        if not remote_only and not match_where(j, where):
            continue
        j.pop("_remote", None)
        j["source"] = BOARD
        pool.setdefault(j["id"], j)

    all_jobs = list(pool.values())
    if include_tracked:
        jobs = all_jobs
    else:
        seen = load_seen(SEEN_PATTERN, tracker=TRACKER)
        seen = {s for s in seen if s}
        jobs = [j for j in all_jobs if not (set(re.findall(SEEN_PATTERN, j["url"])) & seen)
                and j["id"].split(":")[-1] not in seen]
    filtered = len(all_jobs) - len(jobs)

    track = not include_tracked
    if track:
        board_cooldown.record_yield(BOARD, query, len(jobs))

    print(json.dumps(jobs, ensure_ascii=False, indent=2))
    if dead:
        print(f"\n{len(dead)} slug(s) unreachable (skipped): " + "; ".join(dead[:6])
              + (" …" if len(dead) > 6 else ""), file=sys.stderr)
    if jobs:
        by_ats = {}
        for j in jobs:
            by_ats[j["ats_hint"]] = by_ats.get(j["ats_hint"], 0) + 1
        mix = ", ".join(f"{k}:{v}" for k, v in sorted(by_ats.items(), key=lambda x: -x[1]))
        print(f"\n{len(jobs)} FRESH {NAME} jobs from {len(companies)} companies "
              f"({filtered} already tracked, filtered). Mix: {mix}. "
              f"EVERY row is account-lessly submittable — drive .ats_hint's driver in "
              f"sites/<ats>/ straight from .url.", file=sys.stderr)
    else:
        marked = ""
        if track and all_jobs:
            hrs = board_cooldown.adaptive_hours(BOARD, query)
            until = board_cooldown.mark(BOARD, query, hrs)
            marked = f" Auto-marked {BOARD}/{query!r} cooldown until {until} ({hrs:.0f}h)."
        print(f"\nEXHAUSTED: all {len(all_jobs)} {NAME} results for {query!r} already "
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
