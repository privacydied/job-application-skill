#!/usr/bin/env python3
"""cross_audit.py — FINAL pre-drive safety gate on top of convertible_preaudit.py.

WHY this exists (verified 2026-07-24): convertible_preaudit.py reports the
"REAL-DRIVABLE" set, but its Company+Role tracker dedup matches the feed's
*exact* role string. A feed role like "Designer Advocate (London, United
Kingdom)" does NOT match a tracker row stored as "Designer Advocate" → preaudit
flags it drivable → gh_apply re-drives it → DOWNGRADES the existing Applied
row to Blocked (the redrive-destroys-applied-row trap). This script normalises
the role (strips the trailing "(location)" qualifier) before the CR match, so a
re-drive is correctly detected and skipped.

It then applies THREE further gates and prints ONLY the rows that are safe to
drive for real:
  1. url-prefix dedup (preaudit already does this)
  2. role_base + company dedup  (THE FIX above)
  3. check_title lane gate       (off-lane hardware/MEP/recruiting titles dropped)
  4. AI-attestation-wall filter (companies requiring a "no AI / own words" oath
     the applicant cannot truthfully certify via the agent — default Canonical)

USAGE
  python3 scripts/cross_audit.py /tmp/atsdirect.json
  python3 scripts/cross_audit.py /tmp/atsdirect.json /tmp/ifyoucould.json ...
  python3 scripts/cross_audit.py            # defaults to /tmp/atsdirect.json
  --ai-wall "canonical (ubuntu),canonical,ubuntu"   override the attestation wall set
  --no-ai-wall                                     disable the attestation-wall gate

Exit code 0 always; prints "GENUINE NEW ON-LANE DRIVABLE: N" + the reject
histogram so an unattended loop can read the count.
"""
import csv
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "sites", "_common", "scripts"))

import convertible_pool as cp  # noqa: E402

TRACKER = os.path.join(ROOT, "application-tracker.csv")
DEFAULT_FEED = "/tmp/atsdirect.json"
# AI-attestation wall is OFF by default (removed 2026-07-24 — user chose to pursue the Canonical
# roles). Opt back in per-run with `--ai-wall "co1,co2"`. NOTE: un-walling only makes these roles
# SURFACE and get filled — the agent still will NOT tick a form's "I used only my own words / no AI"
# oath itself (the agent authored the application, so ticking it is a false declaration); that box
# + the final submit stay the applicant's.
DEFAULT_AI_WALL = ""


def role_base(role):
    """Strip a trailing '(Location, Country)' qualifier so feed roles match
    tracker rows that omit it."""
    return re.sub(r"\s*\([^)]*\)\s*$", "", role).strip().lower()


def load_tracker():
    tracked_urls = set()
    tracked_cr = set()
    if not os.path.exists(TRACKER):
        return tracked_urls, tracked_cr
    with open(TRACKER, newline="") as f:
        for r in csv.DictReader(f):
            u = (r.get("URL") or "").split("?")[0].rstrip("/").lower()
            tracked_urls.add(u)
            tracked_cr.add(
                (r.get("Company", "").lower().strip(),
                 role_base(r.get("Role", "")))
            )
    return tracked_urls, tracked_cr


def driver_for(j):
    ats = (j.get("ats_hint") or "").lower()
    if ats == "greenhouse":
        return "greenhouse"
    if ats == "ashby":
        return "ashby"
    return None  # only these two have shipped guest-drivable drivers


def on_lane(title):
    """Mirror check_title (canonical lane guard). Returns True/False/None
    (None = check_title unavailable — caller decides)."""
    try:
        from check_title import check_title  # noqa
        res = check_title(title)
        s = str(res).lower()
        if "eligible" in s and "not" not in s.split("eligible")[0][-12:]:
            return True
        if "eligible" in s:
            # crude: eligible present and not preceded closely by 'not'
            return "eligible" in s and "not eligible" not in s
        return False
    except Exception:
        return None


def main():
    args = sys.argv[1:]
    ai_wall_arg = None
    no_ai_wall = False
    feeds = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--ai-wall":
            ai_wall_arg = args[i + 1]; i += 2; continue
        if a == "--no-ai-wall":
            no_ai_wall = True; i += 1; continue
        feeds.append(a); i += 1
    if not feeds:
        feeds = [DEFAULT_FEED]
    ai_wall = set()
    if not no_ai_wall:
        ai_wall = {x.strip().lower() for x in (ai_wall_arg or DEFAULT_AI_WALL).split(",") if x.strip()}

    rows = []
    for fp in feeds:
        if not os.path.exists(fp):
            print(f"# skip missing feed: {fp}", file=sys.stderr)
            continue
        try:
            data = json.load(open(fp))
        except Exception as e:
            print(f"# parse fail {fp}: {e}", file=sys.stderr)
            continue
        if isinstance(data, dict):
            data = data.get("jobs") or data.get("results") or []
        rows.extend(data)

    tracked_urls, tracked_cr = load_tracker()

    candidates = []
    hist = {}
    for j in rows:
        v = cp.classify_strict(j, tracked_urls, tracked_cr)
        if v != "convertible":
            continue
        drv = driver_for(j)
        if drv is None:
            hist["no_driver"] = hist.get("no_driver", 0) + 1
            continue
        co = (j.get("company") or "").strip()
        role = (j.get("title") or "").strip()
        u = str(j.get("url", ""))
        url_prefix = u.split("?")[0].rstrip("/").lower()
        rb = role_base(role)

        if url_prefix in tracked_urls or (co.lower().strip(), rb) in tracked_cr:
            hist["tracked_already"] = hist.get("tracked_already", 0) + 1
            continue
        lane = on_lane(role)
        if lane is False:
            hist["offlane"] = hist.get("offlane", 0) + 1
            continue
        if co.lower().strip() in ai_wall:
            hist["ai_attest_wall"] = hist.get("ai_attest_wall", 0) + 1
            continue
        candidates.append((drv, co, role, u))

    print("=" * 100)
    print("REJECT HISTOGRAM:", dict(hist))
    print(f"GENUINE NEW ON-LANE DRIVABLE: {len(candidates)}")
    print("=" * 100)
    for drv, co, role, u in candidates:
        print(f"{drv:10} | {co[:24]:24} | {role[:46]:46}")
        print(f"             {u}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
