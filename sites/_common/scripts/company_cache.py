#!/usr/bin/env python3
"""
company_cache.py — one reusable hook fact per company (Tier-2: don't re-research a
company you've already written a cover letter for).

Step 3's cover-letter rule needs "one specific fact about the company (product, mission,
recent launch) that couldn't be pasted into a different letter." That fact is stable —
caching it means the second application to the same company (or a company that recurs
across boards) reuses it instead of spending a turn re-deriving it.

company-cache.csv (skill root) columns: company,hook,source,date
  company  normalized key (lowercased, collapsed) — the lookup key
  hook     the one-sentence specific fact to open the cover letter with
  source   where it came from (url / "careers page" / "known")
  date     YYYY-MM-DD captured (refresh if stale for time-sensitive hooks)

Usage:
  company_cache.py get "<Company>"                 -> hook (exit 0) or MISS (exit 1)
  company_cache.py put "<Company>" "<hook>" [src] [date]
  company_cache.py list
"""
import csv
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fsutil import file_lock, atomic_write  # noqa: E402  (locked atomic put, G.1)

_here = os.path.dirname(os.path.abspath(__file__))
CSV = os.path.join(_here, "..", "..", "..", "company-cache.csv")
HEADER = ["company", "hook", "source", "date"]


def norm(name):
    """Company key: lowercase, drop a trailing legal suffix (ltd/limited/inc/llc/plc/
    gmbh) and punctuation, collapse whitespace — so 'Acme Ltd.' and 'ACME' collide."""
    s = re.sub(r"[.,]", " ", (name or "").lower())
    s = re.sub(r"\b(ltd|limited|inc|llc|plc|gmbh|co|company|group|uk)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _read():
    rows = []
    try:
        with open(CSV, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("company"):
                    rows.append(row)
    except FileNotFoundError:
        pass
    return rows


def get(company):
    """The cached hook for `company` (last write wins), or None."""
    k = norm(company)
    hook = None
    for r in _read():
        if norm(r.get("company")) == k:
            hook = (r.get("hook") or "").strip() or hook
    return hook


def put(company, hook, source="", date=""):
    """Append a hook (rewriting any prior row for this company). Best-effort.
    G.1: the read→rewrite is held under a file lock and committed atomically (tmp+
    os.replace via fsutil), so a concurrent daemon warm + live-loop put can't lose a row
    or let a reader (cover-letter step) see a truncated file mid-write."""
    if not company or not hook:
        return False
    k = norm(company)
    try:
        with file_lock(CSV):
            kept = [r for r in _read() if norm(r.get("company")) != k]

            def _w(f):
                w = csv.DictWriter(f, fieldnames=HEADER)
                w.writeheader()
                for r in kept:
                    w.writerow({h: r.get(h, "") for h in HEADER})
                w.writerow({"company": company, "hook": hook, "source": source, "date": date})
            atomic_write(CSV, _w)
        return True
    except OSError:
        return False


def _cli(argv):
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "get" and len(argv) >= 3:
        h = get(argv[2])
        if h:
            print(h)
            return 0
        print("MISS", file=sys.stderr)
        return 1
    if cmd == "put" and len(argv) >= 4:
        src = argv[4] if len(argv) > 4 else ""
        date = argv[5] if len(argv) > 5 else ""
        print("stored" if put(argv[2], argv[3], src, date) else "FAIL")
        return 0
    if cmd == "list":
        for r in _read():
            print(f"{r.get('company')}\t{r.get('hook')}\t{r.get('source')}\t{r.get('date')}")
        return 0
    print('Usage: company_cache.py get "<Company>" | put "<Company>" "<hook>" [src] [date] | list',
          file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(_cli(sys.argv))
