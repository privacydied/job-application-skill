#!/usr/bin/env python3
"""
dedup_tracker.py — merge tracker rows that are the SAME posting logged twice.

WHY THIS EXISTS. `log-application.py` merges on write (canonical id, then Company+Role), and
`precheck.guard()` refuses a duplicate submit — but both are only as good as
`precheck.canon_ids()`. Every gap in that id extraction produces a pair of rows for one job,
and nothing cleans them up after the fact. Live case (2026-07-24): Reed SEARCH-results URLs
carry the id as a query param (`…?q=…&jobId=57050584`) while `reed_apply` synthesizes
`…/jobs/ux-designer/57050584`; canon_ids matched neither to the other, so jobs 57050584 and
57067097 were each applied and logged TWICE — and then reported as four separate applications.
Fixing canon_ids stops NEW duplicates; this repairs the rows already written.

Grouping uses `precheck.canon_ids` — the SAME key the dedup/guard/write paths use, so a pair
this tool merges is exactly a pair those paths now treat as one posting. Rows with no URL are
never grouped (no id = no safe evidence they're the same job); Company+Role is deliberately NOT
used as a merge key here, because two genuinely different postings can share a title.

KEEPER = the most authoritative row: highest status rank (Applied > Applied? > everything else,
via log-application's own `_rank`), then a row citing proof=, then a real company name over a
placeholder like "(unknown employer — Reed)", then the earliest Date. The discarded row's URL is
folded into the keeper's Notes as `ATS: <url>` (log-application's convention) so its id stays
greppable and both keys keep deduping; any other unique Notes text is appended, never dropped.

SAFE: dry-run by default — prints the merge plan and changes nothing. `--fix` applies it, after
writing a timestamped backup to state-backups/. The write is the SKILL.md-blessed pattern
(read all rows → mutate the list → writerows in ONE open('w')) under the tracker lock, so a
concurrent append can't be clobbered.

Usage:
  dedup_tracker.py                      # dry-run, whole tracker
  dedup_tracker.py --date 2026-07-24    # only rows on that date (safest scope)
  dedup_tracker.py --date 2026-07-24 --fix
  dedup_tracker.py --fix                # merge every duplicate group in the tracker

Exit codes: 0 nothing to do / merged ok · 3 duplicates found (dry-run) · 2 error
"""
import argparse
import csv
import importlib.util
import os
import shutil
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_ROOT, "sites", "_common", "scripts"))
import precheck                                  # noqa: E402  (canon_ids — the shared key)
from fsutil import file_lock                     # noqa: E402  (tracker RMW lock)

TRACKER = os.path.join(_ROOT, "application-tracker.csv")
BACKUPS = os.path.join(_ROOT, "state-backups")
COLS = ["Date", "Company", "Role", "Source", "URL", "Status", "Next Action", "Notes"]
_PLACEHOLDER_CO = ("unknown employer", "unknown", "(unknown", "n/a", "")


def _load_rank():
    """log-application.py's own `_rank` (Applied > Applied? > rest). Loaded BY PATH because the
    filename is hyphenated and can't be `import`ed — one definition of which status outranks
    which, rather than a second copy here."""
    path = os.path.join(_ROOT, "sites", "_common", "scripts", "log-application.py")
    spec = importlib.util.spec_from_file_location("_logapp", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._rank


def _clean(s):
    return (s or "").replace("\n", " ").replace("\r", " ").strip()


def _groups(rows, date=None):
    """[(canonical_id, [row indices])] for postings appearing on MORE THAN ONE row. Two rows
    group iff their canon_ids sets intersect."""
    id_to_rows = {}
    for i, r in enumerate(rows):
        if date and (r.get("Date") or "").strip() != date:
            continue
        url = (r.get("URL") or "").strip()
        if not url:
            continue                     # no URL = no safe identity; never merge on title alone
        for cid in precheck.canon_ids(url):
            id_to_rows.setdefault(cid, [])
            if i not in id_to_rows[cid]:
                id_to_rows[cid].append(i)
    out = []
    claimed = set()
    for cid, idxs in id_to_rows.items():
        if len(idxs) < 2 or any(i in claimed for i in idxs):
            continue
        claimed.update(idxs)
        out.append((cid, idxs))
    return out


def _pick_keeper(rows, idxs, rank):
    """Index of the most authoritative row in the group (see module docstring)."""
    def score(i):
        r = rows[i]
        co = _clean(r.get("Company")).lower()
        return (
            rank(r.get("Status")),                                  # Applied > Applied? > rest
            1 if "proof=" in (r.get("Notes") or "") else 0,         # proof-citing row wins
            0 if any(co.startswith(p) for p in _PLACEHOLDER_CO) else 1,   # real company name
            -_ord_date(r.get("Date")),                              # earliest date wins
        )
    return max(idxs, key=score)


def _ord_date(d):
    try:
        return time.mktime(time.strptime((d or "").strip(), "%Y-%m-%d"))
    except (ValueError, TypeError):
        return 0.0


def merge(rows, date=None):
    """-> (plan, merged_rows). plan = [(cid, keeper_idx, [dropped_idx], keeper_after)]."""
    rank = _load_rank()
    plan = []
    drop = set()
    for cid, idxs in _groups(rows, date):
        keep = _pick_keeper(rows, idxs, rank)
        others = [i for i in idxs if i != keep]
        k = rows[keep]
        notes = _clean(k.get("Notes"))
        for i in others:
            o = rows[i]
            ourl = _clean(o.get("URL"))
            # keep the other URL greppable so BOTH id shapes keep matching this row
            if ourl and ourl != _clean(k.get("URL")) and ourl not in notes:
                notes = f"{notes} | ATS: {ourl}".strip(" |")
            onote = _clean(o.get("Notes"))
            if onote and onote not in notes:
                notes = f"{notes} | {onote}".strip(" |")
        notes = f"{notes} | merged-duplicate-row(s) on {time.strftime('%Y-%m-%d')} " \
                f"(same posting id {cid[:40]})".strip(" |")
        k["Notes"] = notes
        plan.append((cid, keep, others, k))
        drop.update(others)
    merged = [r for i, r in enumerate(rows) if i not in drop]
    return plan, merged


def main():
    ap = argparse.ArgumentParser(description="Merge tracker rows that are the same posting.")
    ap.add_argument("--date", default=None, help="only rows with this Date (YYYY-MM-DD)")
    ap.add_argument("--fix", action="store_true", help="apply the merge (default: dry-run)")
    ap.add_argument("--tracker", default=TRACKER)
    a = ap.parse_args()

    with file_lock(a.tracker):
        try:
            with open(a.tracker, newline="", encoding="utf-8") as f:
                rdr = csv.DictReader(f)
                rows = list(rdr)
                fieldnames = rdr.fieldnames
        except (OSError, csv.Error) as e:
            print(f"ERROR: cannot read tracker: {e}", file=sys.stderr)
            return 2
        if fieldnames != COLS:
            print(f"ERROR: tracker header {fieldnames} != {COLS} — refusing to write",
                  file=sys.stderr)
            return 2

        plan, merged = merge(rows, a.date)
        if not plan:
            print(f"No duplicate postings found{' on ' + a.date if a.date else ''}. "
                  f"({len(rows)} rows)")
            return 0

        print(f"{len(plan)} duplicate posting(s){' on ' + a.date if a.date else ''} — "
              f"{len(rows)} rows -> {len(merged)}:")
        for cid, keep, others, k in plan:
            print(f"\n  posting id {cid[:46]}")
            print(f"    KEEP  [{rows[keep].get('Status'):9s}] {rows[keep].get('Company')} | "
                  f"{rows[keep].get('Role')}")
            for i in others:
                print(f"    DROP  [{rows[i].get('Status'):9s}] {rows[i].get('Company')} | "
                      f"{rows[i].get('Role')}   ({rows[i].get('URL')})")
        if not a.fix:
            print("\nDRY-RUN — nothing written. Re-run with --fix to apply.")
            return 3

        os.makedirs(BACKUPS, exist_ok=True)
        bak = os.path.join(BACKUPS, "application-tracker.csv.predup-"
                           + time.strftime("%Y%m%dT%H%M%S"))
        shutil.copy2(a.tracker, bak)
        tmp = a.tracker + ".tmp-dedup"
        try:
            with open(tmp, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=COLS)
                w.writeheader()
                w.writerows(merged)
            os.replace(tmp, a.tracker)
        except OSError as e:
            print(f"ERROR: write failed: {e} (tracker untouched; backup at {bak})",
                  file=sys.stderr)
            return 2
        print(f"\nMERGED. {len(rows)} -> {len(merged)} rows. Backup: {os.path.relpath(bak, _ROOT)}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
