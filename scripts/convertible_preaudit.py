#!/usr/bin/env python3
"""convertible_preaudit.py — run BEFORE driving any `convertible` row.

Folds every harvested feed, applies convertible_pool.classify_strict WITH the Company+Role
tracker dedup (so cross-URL cross-posts are excluded), then maps each truly-new convertible to
its shipped driver. Prints the reject histogram, the honest convertible count, and the
driver spread — drive ONLY the rows whose driver is a shipped one.

WHY (2026-07-20 lesson): the strict `convertible` set over-counts two ways — (a) no-driver
sources (creativepool/escapecity/thedots/adzuna) classified as convertible (they need your VNC),
and (b) it dedups on URL only, so a role cross-posted under a different URL/board shows "fresh"
even when the SAME Company+Role is already in the tracker. This script closes both gaps and
prints exactly which rows are safe to drive. Full post-mortem: references/convertible-drive-preaudit.md.

USAGE
  python3 scripts/convertible_preaudit.py /tmp/feed1.json /tmp/feed2.json ...
  python3 scripts/convertible_preaudit.py /tmp/*.json
"""
import csv
import glob
import json
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
import convertible_pool as cp

TRACKER = os.path.join(ROOT, "application-tracker.csv")


def driver(j):
    ats = (j.get("ats_hint") or "").lower()
    src = (j.get("source") or "").lower()
    u = str(j.get("url", ""))
    if ats == "greenhouse":
        return "greenhouse"
    if ats == "ashby":
        return "ashby"
    if "smartrecruiters" in ats:
        return "smartrecruiters_NO_DRIVER"
    if src == "csj" or "civilservicejobs" in u:
        return "csj_tal"
    if src == "guardian" or "jobs.theguardian" in u:
        return "guardian_direct"
    if src == "wttj" or "welcometothejungle" in u:
        return "wttj_apply"
    if src == "atsdirect":
        return "atsdirect_" + ats
    if src in ("adzuna", "thedots", "creativepool", "escapecity", "dezeen",
               "designweek", "ifyoucould"):
        return "NO_DRIVER_" + src
    if "applicationtrack" in u or src in ("mi5", "mi6", "gchq"):
        return "aptrack"
    return "unknown:" + src


def main():
    feeds = []
    for pat in sys.argv[1:]:
        feeds += glob.glob(pat) if "*" in pat else [pat]
    if not feeds:
        print("usage: convertible_preaudit.py /tmp/feed1.json [...]")
        return 2

    rows = []
    for fp in feeds:
        try:
            rows += cp.load_rows(fp)
        except Exception as e:
            sys.stderr.write(f"warn: skip {fp}: {e}\n")

    seen = set()
    uniq = []
    for j in rows:
        u = (j.get("url") or "").strip()
        if not u or u in seen:
            continue
        seen.add(u)
        uniq.append(j)

    tracked_urls = set()
    cr = set()
    if os.path.exists(TRACKER):
        with open(TRACKER, newline="") as f:
            for r in csv.DictReader(f):
                tracked_urls.add((r.get("URL") or "").strip())
                cr.add(((r.get("Company") or "").strip().lower(),
                        (r.get("Role") or "").strip().lower()))

    reasons = Counter()
    conv = []
    for j in uniq:
        r = cp.classify_strict(j, tracked_urls, cr)
        reasons[r] += 1
        if r == "convertible":
            key = ((j.get("company") or "").strip().lower(),
                   (j.get("title") or "").strip().lower())
            if (j.get("url") or "").strip() in tracked_urls or key in cr:
                reasons["convertible_but_tracked"] += 1
            else:
                conv.append(j)

    print(f"UNIQUE candidates : {len(uniq)}")
    for k, v in reasons.most_common():
        print(f"  {v:4d}  {k}")
    print(f"CONVERTIBLE truly-new: {len(conv)}")
    drv = Counter(driver(j) for j in conv)
    print("driver spread (truly-new convertible):")
    for k, v in drv.most_common():
        print(f"  {v:3d}  {k}")
    drivable = [j for j in conv
                if not driver(j).startswith(("NO_DRIVER", "smartrecruiters", "unknown"))]
    print(f"\nREAL-DRIVABLE (shipped driver + not tracked): {len(drivable)}")
    for j in drivable:
        print(f"  {driver(j):16s} {j.get('source',''):10s} "
              f"{(j.get('company') or '')[:22]:22s} | {(j.get('title') or '')[:40]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
