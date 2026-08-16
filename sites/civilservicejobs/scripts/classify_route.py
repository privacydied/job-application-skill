#!/usr/bin/env python3
"""classify_route.py — split CSJ vacancies into the ones an autonomous run can actually drive
and the ones it cannot, BEFORE any of them costs a tailoring pass.

WHY THIS EXISTS (2026-08-16). CSJ is the biggest single pool this skill can reach — one
sourcing pass returned 883 cards — but a CSJ advert is not one thing. Some vacancies are
in-platform TAL eforms (cshr.tal.net), which `tal_eform.py` drives end to end. Many others say
**"Apply at advertiser's site"** and hand off to the department's own ATS, which needs an
account this run does not have. Of the first ten queued, only THREE were TAL eforms.

That ratio matters because a CSJ Section 2 is 30+ minutes of genuinely bespoke writing
(name-blind CV, personal statement, Success Profile behaviours). Discovering "this one hands
off to an external site" AFTER writing all that is the expensive way to find out. So classify
first, then spend the writing time only on the drivable ones.

Why it needs the browser: civilservicejobs.service.gov.uk is behind an ALTCHA "Quick Check
Needed" interstitial, so a plain HTTP fetch returns the gate page, not the advert (verified —
`curl` gets `<title>Quick Check Needed</title>` and zero apply markers). The sanctioned ALTCHA
auto-solve lives in feed.py and is invoked HERE (solve_altcha) — this module runs
standalone from the apply lane, so it cannot assume a feed run already cleared the gate.

USAGE:
  python3 sites/civilservicejobs/scripts/classify_route.py <cards.json> [<cards.json> ...] \
      [--out worklist.json] [--limit N]
    cards.json: feed.py output (a list of rows with `url`, `title`, `company`).

Emits one row per vacancy: route = tal | external | closed | unknown, plus grade and salary
when the advert states them (CSJ seniority is the GRADE, not the title word — see SKILL.md).
"""
import json
import os
import re
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(_ROOT, "sites", "_common", "scripts"))
import cfx  # noqa: E402


def _csj_feed():
    """Load THIS board's feed.py by explicit path, for solve_altcha().

    ⛔ NEVER `import feed` (2026-08-16). Forty-three boards ship a module named `feed.py`
    (sites/*/scripts/feed.py), so a bare import binds whichever directory happens to be first
    on sys.path — and inserting _HERE to win that race poisons the path for every script
    imported afterwards. It did exactly that: the codebase-wide import test started failing in
    sites/lgjobs.com/scripts/feed.py, which is not a file this change went near. Address the
    file, not the name."""
    import importlib.util  # noqa: PLC0415
    path = os.path.join(_HERE, "feed.py")
    spec = importlib.util.spec_from_file_location("csj_feed", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

# "Apply at advertiser's site" is the hand-off marker. Keep this narrow: the phrase appears in
# the apply block, and a looser match ("advertiser") would also hit unrelated boilerplate.
_EXTERNAL = re.compile(r"apply at advertiser|advertiser'?s? (own )?site|apply on the .{0,30}website", re.I)
# CSJ's real wording for a dead advert is "Cannot view job / This job has closed or been
# withdrawn" — the first version of this regex missed it, so closed vacancies came back
# as `unknown` (verified on DBT SOC Analyst 2006355 and OFGEM Snr Digital BA 2005969).
# NB the same "Cannot view job" page is also the SID-expiry symptom documented in NOTES.md,
# but reached via a stable jobs.cgi?jcode= URL it means the vacancy really is gone.
_CLOSED = re.compile(r"no longer (available|accepting)|vacancy has closed|"
                    r"closed for applications|cannot view job|"
                    r"has closed or been withdrawn", re.I)
_APPLY_NOW = re.compile(r"\bapply now\b", re.I)


def classify_one(url):
    """-> dict(route, grade, salary, title_seen). Never raises; a nav failure is `unknown`."""
    out = {"route": "unknown", "grade": "", "salary": "", "note": ""}
    try:
        nav = cfx.goto(url)
    except Exception as e:  # noqa: BLE001
        out["note"] = f"nav error: {str(e)[:60]}"
        return out
    if not nav.get("ok"):
        out["note"] = "blank render"
        return out
    # ⛔ SOLVE THE GATE, DON'T ASSUME SOMEONE ELSE DID (2026-08-16). This module's header said
    # it "reuses the same live tab" as feed.py and therefore inherits its ALTCHA solve. That
    # only holds if a feed run happened first, in this session, on this tab. Run standalone —
    # which is exactly how the apply lane calls it — every vacancy lands on the "Quick Check
    # Needed" interstitial instead, so no apply/external/closed marker is ever present and
    # ALL TEN vacancies came back `unknown` with empty grade and salary. That reads as "cannot
    # classify" when the truth is "never saw the advert", and it silently zeroes out the one
    # lane that is UK-only by definition. feed.solve_altcha() is the sanctioned solver and its
    # own docstring says it is "worth reusing"; do so (loaded by PATH — see _csj_feed).
    try:
        if "quick check" in (cfx.evaluate("(()=>document.title)()") or "").lower():
            _csj_feed().solve_altcha()
    except Exception as e:  # noqa: BLE001 — a gate we cannot solve stays `unknown`, as before
        out["note"] = f"altcha: {str(e)[:50]}"
    # ⛔ SETTLE BEFORE READING (2026-08-16). goto() returns as soon as the page has content,
    # but CSJ renders the apply block a beat later. Reading immediately produced `unknown` for
    # adverts that plainly carry an "Apply now" button — i.e. it under-reported the DRIVABLE
    # set, which is the expensive direction to be wrong in. Poll until an apply marker appears
    # (or the closed/external marker does), then read once.
    text = ""
    for _ in range(10):
        try:
            text = cfx.evaluate("(()=>document.body.innerText)()") or ""
        except Exception as e:  # noqa: BLE001
            out["note"] = f"read error: {str(e)[:60]}"
            return out
        if _APPLY_NOW.search(text) or _EXTERNAL.search(text) or _CLOSED.search(text):
            break
        time.sleep(0.6)
    for key, field in (("Job grade", "grade"), ("Salary", "salary")):
        m = re.search(key + r"\s*\n(.{0,60})", text)
        if m:
            out[field] = m.group(1).strip()
    # ⛔ ASK THE DOM FOR THE APPLY CONTROL (2026-08-16). CSJ keeps the apply block inside a
    # COLLAPSED "Apply and further information" section, so its button text is absent from
    # document.body.innerText even though the control exists. Matching on innerText alone
    # reported `unknown` for adverts that plainly have an "Apply now" button — under-reporting
    # the drivable set, which is the expensive direction to be wrong in. innerText stays the
    # right signal for the EXTERNAL hand-off notice, which is prose in the advert body.
    try:
        has_apply = cfx.evaluate(
            "(()=>[...document.querySelectorAll('a,button,input[type=submit]')]"
            ".some(x=>/^apply now$/i.test((x.innerText||x.value||'').trim())))()")
    except Exception:  # noqa: BLE001
        has_apply = False
    if _CLOSED.search(text):
        out["route"] = "closed"
    elif _EXTERNAL.search(text):
        out["route"] = "external"
        out["note"] = "hands off to the department's own ATS — needs an account"
    elif has_apply or _APPLY_NOW.search(text):
        out["route"] = "tal"
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    out_path = None
    if "--out" in sys.argv:
        out_path = sys.argv[sys.argv.index("--out") + 1]
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    if not args:
        print(__doc__)
        return 2

    rows, seen = [], set()
    for path in args:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        for r in data if isinstance(data, list) else []:
            u = (r or {}).get("url")
            if u and u not in seen:
                seen.add(u)
                rows.append(r)
    if limit:
        rows = rows[:limit]
    print(f"classifying {len(rows)} CSJ vacancies", file=sys.stderr)

    work = []
    for i, r in enumerate(rows, 1):
        res = classify_one(r["url"])
        res.update(url=r["url"], title=r.get("title", ""), company=r.get("company", ""))
        work.append(res)
        print(f"  [{i}/{len(rows)}] {res['route']:8s} {(res.get('grade') or '-')[:28]:30s} "
              f"{(r.get('company') or '')[:26]:28s} {(r.get('title') or '')[:40]}",
              file=sys.stderr)
        time.sleep(0.8)

    tal = [w for w in work if w["route"] == "tal"]
    print(f"\nDRIVABLE (in-platform TAL eform): {len(tal)} of {len(work)}", file=sys.stderr)
    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(work, f, indent=1, ensure_ascii=False)
    print(json.dumps(work, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
