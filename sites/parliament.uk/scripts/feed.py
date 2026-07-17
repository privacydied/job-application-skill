#!/usr/bin/env python3
"""feed.py — enumerate UK Parliament vacancies (House of Commons, House of Lords, PDS).

Parliament recruits on **MHR Web Recruitment (iTrent)** — NOT Oleeo, and NOT
`workforus.parliament.uk` (NXDOMAIN). There are **three separate boards**, one per employer
stream, each a different `WVID` ("web view id") on the ETREC179GF search app:

    pds      hrhoc.parliament.uk/ce0912li_webrecruitment  WVID=6744175kYE
    commons  hrhoc.parliament.uk/ce0912li_webrecruitment  WVID=3402965kYE
    lords    hrhol.parliament.uk/ce0913li_webrecruitment  WVID=7744073cYW   (different host)

**PDS = Parliamentary Digital Service** — Parliament's in-house design/UX/engineering arm and
the on-profile stream (§1/§3/§12). It is also usually the *smallest* board: a PDS pass that
returns 0 is normal, not a broken feed — check `commons` before concluding anything is wrong.
This feed sweeps all three by default (~15 live vacancies total); `--tenant` narrows it.

⚠️ WHY THIS NEEDS CAMOFOX (`CFX_KEY`): the board is a session-bound SPA. Plain HTTP gets a
shell — the vacancy list is rendered client-side and **no XHR fires** (the results are
computed in-page), so there is nothing to intercept and no JSON endpoint to call. POSTing
the search form returns a bare "Search for jobs" page. Rendering is the only route.

Cards are `.Mhr-jobSearchJobs > *` and carry a stable `vac-id`; fields come from
`.Mhr-jobDetailEntry` label/text pairs (Apply by / Location / Salary / Basis).

Canonical URL — `ETREC179GF.open?WVID=<wvid>&VACANCY_ID=<vac-id>` deep-links straight to the
job profile, session-free (verified). Do NOT use the card's `bu-send` attribute: it points at
`ETREC148GF` (the *apply* screening flow) and carries a `USESSION` token that expires — and
without the session it renders "Screening Questions" with no vacancy context at all.

Apply is account-gated (MHR candidate account: "Existing user login" / "My applications").
Sourcing is open; submission needs that account.

Usage:
    CFX_KEY=... python3 feed.py [--tenant pds|commons|lords] [--what "<terms>"] [--all] [--force]
    python3 feed.py --list-tenants
"""
import json
import os
import re
import sys
import time

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_here, "..", "..", "_common", "scripts"))
import board_cooldown  # noqa: E402
import httpfeed  # noqa: E402
from precheck import load_seen  # noqa: E402

BOARD = "parliament"
NAME = "UK Parliament"
TRACKER = os.path.join(_here, "..", "..", "..", "application-tracker.csv")
SEEN_PATTERN = r"parliament\.uk/[^,\s]*?VACANCY_ID=([A-Za-z0-9]+)"

TENANTS = {
    "pds": {
        "base": "https://hrhoc.parliament.uk/ce0912li_webrecruitment/wrd/run",
        "wvid": "6744175kYE",
        "employer": "UK Parliament — Parliamentary Digital Service",
    },
    "commons": {
        "base": "https://hrhoc.parliament.uk/ce0912li_webrecruitment/wrd/run",
        "wvid": "3402965kYE",
        "employer": "UK Parliament — House of Commons",
    },
    "lords": {
        "base": "https://hrhol.parliament.uk/ce0913li_webrecruitment/wrd/run",
        "wvid": "7744073cYW",
        "employer": "UK Parliament — House of Lords",
    },
}

# Read every card out of the rendered board in ONE evaluate.
ENUM = r"""
(() => {
  const out = [];
  document.querySelectorAll('.Mhr-jobSearchJobs > *').forEach(c => {
    const id = c.getAttribute('vac-id');
    if (!id) return;
    const t = c.querySelector('.Mhr-jobDetailTitleLink span');
    const entries = {};
    c.querySelectorAll('.Mhr-jobDetailEntry').forEach(e => {
      const l = (e.querySelector('.Mhr-jobDetailEntry--label') || {}).innerText || '';
      const v = (e.querySelector('.Mhr-jobDetailEntry--text') || {}).innerText || '';
      const k = l.replace(/\s+/g, ' ').trim().toLowerCase();
      if (k) entries[k] = v.replace(/\s+/g, ' ').trim();
    });
    out.push({ id, title: ((t && t.innerText) || '').trim(), entries });
  });
  return JSON.stringify(out);
})()
"""


def canonical_url(tenant, vac_id):
    """Session-free deep link to the job profile. `bu-send`'s ETREC148GF URL is the apply
    flow and its USESSION expires — never persist that one."""
    t = TENANTS[tenant]
    return f"{t['base']}/ETREC179GF.open?WVID={t['wvid']}&VACANCY_ID={vac_id}"


def board_url(tenant):
    t = TENANTS[tenant]
    return f"{t['base']}/ETREC179GF.open?WVID={t['wvid']}"


def normalize(raw, tenant):
    """Pure: one rendered card -> the shared posting shape. Unit-tested."""
    vid = (raw.get("id") or "").strip()
    title = httpfeed.clean(raw.get("title"))
    if not vid or not title:
        return None
    e = {k: httpfeed.clean(v) for k, v in (raw.get("entries") or {}).items()}
    return {
        "id": vid,
        "url": canonical_url(tenant, vid),
        "title": title,
        "company": TENANTS[tenant]["employer"],
        "location": e.get("location", ""),
        "salary": e.get("salary", ""),
        "closes": e.get("apply by", ""),
        "basis": e.get("basis", ""),
        "ats_hint": "mhr-webrec",
        "source": BOARD,
        "tenant": tenant,
    }


def match_what(job, what):
    """Free-text title filter (space/OR/comma = OR; quoted = phrase). The board's own
    keyword box is client-side, so filtering here avoids driving its UI."""
    if not what:
        return True
    title = (job.get("title") or "").lower()
    w = what.strip()
    if len(w) > 1 and w[0] == w[-1] and w[0] in "\"'":
        return w[1:-1].lower() in title
    terms = [t for t in re.split(r'\s*(?:\bOR\b|,)\s*|\s+', w) if t]
    return any(t.strip('"\'').lower() in title for t in terms)


def scrape(tenant, wait=9):
    """Render one tenant's board and return its raw cards. Cards render ON LOAD — there is
    no need to click 'Find jobs' (and that click times out anyway: it fires a re-render
    Playwright waits on, the documented click-hang pattern)."""
    import cfx
    cfx.ensure_tab()
    cfx.navigate(board_url(tenant))
    time.sleep(wait)
    raw = cfx.evaluate(ENUM, timeout=45)
    try:
        return json.loads(raw) if isinstance(raw, str) else (raw or [])
    except ValueError:
        return []


def main():
    args = sys.argv[1:]

    def opt(name, default=None):
        return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else default

    if "--list-tenants" in args:
        for k, v in TENANTS.items():
            print(f"  {k:8} WVID={v['wvid']:12} {v['employer']}")
            print(f"           {board_url(k)}")
        return 0

    tenant = (opt("--tenant") or "").strip().lower()
    if tenant and tenant not in TENANTS:
        print(f"ERROR: unknown --tenant {tenant!r} (pds|commons|lords)", file=sys.stderr)
        return 2
    tenants = [tenant] if tenant else list(TENANTS)

    what = opt("--what") or ""
    include_tracked = "--all" in args
    force = "--force" in args or include_tracked
    query = what or tenant or "all"

    if not force:
        rem = board_cooldown.remaining_hours(BOARD, query)
        if rem > 0:
            print("[]")
            print(f"\nCOOLDOWN: {BOARD}/{query!r} confirmed exhausted ({rem:.1f}h remaining). "
                  f"--force to override.", file=sys.stderr)
            return 1

    if not os.environ.get("CFX_KEY"):
        print("ERROR: Parliament's board is a client-rendered SPA (no JSON endpoint, no XHR "
              "to intercept) — this feed needs camofox (set CFX_KEY). --list-tenants works "
              "without it.", file=sys.stderr)
        return 2

    pool, per_tenant = {}, {}
    for t in tenants:
        try:
            cards = scrape(t)
        except Exception as e:
            print(f"WARN: {NAME}/{t} render failed: {e}", file=sys.stderr)
            per_tenant[t] = 0
            continue
        n = 0
        for c in cards:
            job = normalize(c, t)
            if job and match_what(job, what) and job["id"] not in pool:
                pool[job["id"]] = job
                n += 1
        per_tenant[t] = n

    all_jobs = list(pool.values())
    if include_tracked:
        jobs = all_jobs
    else:
        seen = load_seen(SEEN_PATTERN, tracker=TRACKER)
        jobs = [j for j in all_jobs if j["id"] not in seen]
    filtered = len(all_jobs) - len(jobs)

    track = not include_tracked
    if track:
        board_cooldown.record_yield(BOARD, query, len(jobs))

    print(json.dumps(jobs, ensure_ascii=False, indent=2))
    mix = ", ".join(f"{k}:{v}" for k, v in per_tenant.items())
    if jobs:
        print(f"\n{len(jobs)} FRESH {NAME} vacancies ({filtered} already tracked, filtered). "
              f"By stream: {mix}. Apply is account-gated (MHR candidate account).",
              file=sys.stderr)
    else:
        marked = ""
        if track and all_jobs:
            hrs = board_cooldown.adaptive_hours(BOARD, query)
            until = board_cooldown.mark(BOARD, query, hrs)
            marked = f" Auto-marked {BOARD}/{query!r} cooldown until {until} ({hrs:.0f}h)."
        print(f"\nEXHAUSTED: all {len(all_jobs)} {NAME} results for {query!r} already "
              f"tracked (by stream: {mix}).{marked}", file=sys.stderr)
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
