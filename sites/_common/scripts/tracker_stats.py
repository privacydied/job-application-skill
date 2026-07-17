#!/usr/bin/env python3
"""
tracker_stats.py — the ONE reporting path for the tracker's counts (feature-roadmap H.2).

WHY THIS EXISTS. SKILL.md documents, at length, the "269-vs-267" scar: `grep -c ',Applied,'`
returns a LOOSE count that also catches `Applied?` and malformed rows, so a run's headline
number kept getting inflated. The fix was always "report the strict-parse count," but that
was prose the model had to remember and re-derive with an ad-hoc `execute_code` block every
time. This makes it a tool: `tracker_stats.py` parses the CSV properly and reports the
STRICT count (Status stripped == 'Applied', exact), plus a full status breakdown. Docs stop
describing the grep-vs-strict trap and instead say "run tracker_stats.py".

Definitions (locked to search_plan.applied_today's semantics):
  strict Applied = row whose Status column, stripped, is EXACTLY 'Applied'
                   (NOT 'Applied?', NOT a substring match).

CLI:
  tracker_stats.py                 # strict Applied total + today + status breakdown
  tracker_stats.py --count         # just the strict Applied integer (for scripts)
  tracker_stats.py --today         # just today's strict Applied integer
  tracker_stats.py --json          # machine summary
  tracker_stats.py --since 271     # show the strict delta vs a baseline (the run floor)
"""
import csv
import json
import os
import sys
from collections import Counter
from datetime import datetime

_here = os.path.dirname(os.path.abspath(__file__))
TRACKER = os.path.join(_here, "..", "..", "..", "application-tracker.csv")


def read_rows(path=None):
    rows = []
    try:
        with open(path or TRACKER, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    except (FileNotFoundError, OSError):
        pass
    return rows


def stats(path=None, day=None):
    """Strict, CSV-correct counts. Returns a dict:
      {applied, applied_today, total_rows, by_status: {status: n}, loose_applied}
    `loose_applied` is the grep-style count (substring 'Applied' incl. 'Applied?') shown ONLY
    so a caller can SEE the inflation the strict count corrects — never report it as truth."""
    rows = read_rows(path)
    day = day or datetime.now().strftime("%Y-%m-%d")
    by_status = Counter()
    applied = applied_today = loose = 0
    for r in rows:
        st = (r.get("Status") or "").strip()
        by_status[st or "(blank)"] += 1
        if st == "Applied":
            applied += 1
            if (r.get("Date") or "").strip().startswith(day):
                applied_today += 1
        if "applied" in st.lower():
            loose += 1
    return {
        "applied": applied,
        "applied_today": applied_today,
        "total_rows": len(rows),
        "by_status": dict(by_status),
        "loose_applied": loose,
    }


def _cli(argv):
    def opt(flag, default=None):
        return argv[argv.index(flag) + 1] if flag in argv and argv.index(flag) + 1 < len(argv) else default

    s = stats()
    if "--count" in argv:
        print(s["applied"]); return 0
    if "--today" in argv:
        print(s["applied_today"]); return 0
    if "--json" in argv:
        print(json.dumps(s, ensure_ascii=False)); return 0
    print(f"Applied (STRICT, Status=='Applied'):  {s['applied']}")
    print(f"  of which today:                     {s['applied_today']}")
    print(f"  total tracker rows:                 {s['total_rows']}")
    since = opt("--since")
    if since and since.lstrip("-").isdigit():
        base = int(since)
        print(f"  strict delta vs baseline {base}:      +{s['applied'] - base}")
    if s["loose_applied"] != s["applied"]:
        print(f"  ⚠️  loose 'grep Applied' count is {s['loose_applied']} "
              f"({s['loose_applied'] - s['applied']} inflated by Applied?/malformed — "
              f"report the STRICT {s['applied']}, never the grep count)")
    print("  status breakdown: " + ", ".join(
        f"{k}={v}" for k, v in sorted(s["by_status"].items(), key=lambda kv: -kv[1])))
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv))
