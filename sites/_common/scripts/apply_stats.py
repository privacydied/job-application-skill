#!/usr/bin/env python3
"""
apply_stats.py — per-ATS attempt/submit tally so the work-list ordering LEARNS which
ATS actually completes (Tier-5 feedback loop). pipeline.apply_rank() blends this with a
static prior: a driver that keeps failing sinks, a proven-good one floats up.

apply-stats.csv (skill root) columns: ats,attempts,submitted,last
  ats        the ats_hint bucket (linkedin-easyapply / greenhouse / workday / …)
  attempts   times a real submit was attempted through this ATS
  submitted  times it actually confirmed submitted
  last       YYYY-MM-DD of the most recent attempt

record(ats, submitted) is called by the apply drivers at their terminal outcome — one
line, best-effort, never raises. rate(ats) = submitted/attempts (None if untried).

CLI:
  apply_stats.py record <ats> <ok|fail>
  apply_stats.py rate <ats>
  apply_stats.py list
"""
import csv
import os
import sys

from fsutil import file_lock, atomic_write  # shared lock + atomic write (Tier A)

_here = os.path.dirname(os.path.abspath(__file__))
CSV = os.path.join(_here, "..", "..", "..", "apply-stats.csv")
HEADER = ["ats", "attempts", "submitted", "last"]


def _read():
    d = {}
    try:
        with open(CSV, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                a = (row.get("ats") or "").strip()
                if not a:
                    continue
                try:
                    d[a] = {"attempts": int(row.get("attempts", 0)),
                            "submitted": int(row.get("submitted", 0)),
                            "last": (row.get("last") or "").strip()}
                except ValueError:
                    continue
    except FileNotFoundError:
        pass
    return d


def record(ats, submitted, day=None):
    """Increment attempts (and submitted if the apply confirmed) for `ats`. Best-effort;
    swallows all errors so a stats write can never break an application."""
    ats = (ats or "").strip()
    if not ats:
        return False
    try:
        if day is None:
            try:
                from datetime import datetime
                day = datetime.now().strftime("%Y-%m-%d")
            except Exception:
                day = ""
        # A.3: read→increment→write held under the lock and committed atomically, so
        # concurrent drivers don't lose an increment and pipeline._load_apply_stats()
        # can never read a truncated file mid-write.
        with file_lock(CSV):
            d = _read()
            cur = d.get(ats, {"attempts": 0, "submitted": 0, "last": ""})
            cur["attempts"] += 1
            if submitted:
                cur["submitted"] += 1
            cur["last"] = day
            d[ats] = cur

            def _w(f):
                w = csv.DictWriter(f, fieldnames=HEADER)
                w.writeheader()
                for a, v in sorted(d.items()):
                    w.writerow({"ats": a, "attempts": v["attempts"],
                                "submitted": v["submitted"], "last": v["last"]})
            atomic_write(CSV, _w)
        return True
    except OSError:
        return False


def rate(ats):
    v = _read().get((ats or "").strip())
    if not v or v["attempts"] == 0:
        return None
    return v["submitted"] / v["attempts"]


def _cli(argv):
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "record" and len(argv) >= 4:
        ok = argv[3].strip().lower() in ("ok", "true", "1", "yes", "submitted", "success")
        print("recorded" if record(argv[2], ok) else "FAIL")
        return 0
    if cmd == "rate" and len(argv) >= 3:
        r = rate(argv[2])
        print("untried" if r is None else f"{r:.2f}")
        return 0
    if cmd == "list":
        for a, v in sorted(_read().items()):
            r = v["submitted"] / v["attempts"] if v["attempts"] else 0.0
            print(f"{a}\t{v['submitted']}/{v['attempts']}\t{r:.2f}\t{v['last']}")
        return 0
    print("Usage: apply_stats.py record <ats> <ok|fail> | rate <ats> | list", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(_cli(sys.argv))
