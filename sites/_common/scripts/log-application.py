#!/usr/bin/env python3
"""
log-application.py — the ONE way to write application-tracker.csv rows.

Promoted from a Hermes run's /tmp/log.py (2026-07-14), which encoded the tracker's
column schema but appended blindly. This version implements SKILL.md step 8's actual
rule: **update the posting's row in place if one exists (e.g. a `Saved` row from
sourcing, or a `Blocked` row being resolved); only append when there's no row yet.**
Blind appends create duplicate Company+Role rows that poison the tracker dedup in
feed.py/precheck.py (first-match status wins), so don't hand-append and don't use
raw `echo >>` — use this.

Usage:
    log-application.py <Company> <Role> <Source> <URL> <Status>
                       [--next "<next action>"] [--notes "<notes>"]
                       [--date YYYY-MM-DD] [--tracker <path>] [--append-new]
                       [--proof <path>]

HARD RULE (added 2026-07-14 after an audit found ~3/22 "Applied" rows had no
proof of submission): a row may only be logged with Status **Applied** if
`--proof <path>` points to an existing, non-empty confirmation artifact — a
screenshot of the "application sent / we have received your application"
page/modal, OR a .txt capturing that confirmation string. No proof => the write
is REFUSED (exit 2). If a submission genuinely can't be confirmed (form filled
but no confirmation page reached), log Status **Applied?** instead; if there's
no evidence at all, use **Unverified**. Neither requires proof. This keeps the
"Applied" count meaning "provably submitted" rather than "attempted".
Capture proof INTO the posting's folder, e.g. applications/<slug>/confirmation.png,
then pass --proof applications/<slug>/confirmation.png. The proof's basename is
recorded in Notes (proof=<file>) so the row stays self-documenting.

Matching (same keys the dedup uses): canonical URL id first (LinkedIn/Indeed/WTTJ/
Greenhouse/Lever/Ashby/Workday/CSJ patterns via precheck.canon_ids), then normalized
Company+Role. On match -> update Date/Status/Next Action in place, and merge Notes.

URL handling on update: the EXISTING URL column is kept (it's a live dedup key —
overwriting a LinkedIn URL with the ATS URL would make the next LinkedIn feed pass
resurface the posting as "fresh"). A DIFFERENT new URL is appended to Notes as
"ATS: <url>" instead — feed.py's line-regex dedup catches ids there too, so both
keys stay active on the row.

Append path is O_APPEND (no rewrite); update path rewrites atomically (os.replace).
Both run under an advisory file lock (fsutil.file_lock, Tier A.4) held across
read→decide→write, so a concurrent append can't be clobbered by another process's
rewrite (the lost-append race) even with the warm-queue daemon or a second driver live.

Exit codes: 0 wrote/updated · 2 bad input/IO.
"""
import csv
import os
import re
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from precheck import canon_ids, _norm  # noqa: E402  (same keys as the dedup)
from fsutil import file_lock  # noqa: E402  (tracker RMW lock, Tier A.4)

COLS = ["Date", "Company", "Role", "Source", "URL", "Status", "Next Action", "Notes"]


def _default_tracker():
    d = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(d, "..", "..", "..", "application-tracker.csv"))


def _clean(s):
    return (s or "").replace("\n", " ").replace("\r", " ").strip()


def load_rows(path):
    """Read all rows, tolerating the tracker's real-world malformed rows: rows with
    EXTRA fields (un-quoted commas in old hand-written notes) land under DictReader's
    restkey — fold them back into Notes so a rewrite can't drop data or crash
    (csv.DictWriter refuses unknown keys; found live on the first test run)."""
    with open(path, newline="", encoding="utf-8") as f:
        rdr = csv.DictReader(f, restkey="_extra", restval="")
        rows = []
        for r in rdr:
            extra = r.pop("_extra", None)
            if extra:
                tail = " ".join(_clean(x) for x in extra if _clean(x))
                if tail:
                    r["Notes"] = f"{r.get('Notes') or ''} {tail}".strip()
            rows.append(r)
        return rows, rdr.fieldnames


def find_match(rows, url, company, role):
    """Index of the existing row for this posting, or -1. Canonical URL id first,
    then normalized Company+Role — the same two keys every dedup pass uses."""
    want_ids = canon_ids(url) if url else set()
    pair = (_norm(company), _norm(role))
    for i, r in enumerate(rows):
        if want_ids and (canon_ids(r.get("URL") or "") & want_ids):
            return i
        if pair[0] and pair[1] and (_norm(r.get("Company")), _norm(r.get("Role"))) == pair:
            return i
    return -1


def main():
    a = sys.argv[1:]
    if len(a) < 5:
        print(__doc__)
        return 2
    company, role, source, url, status = (_clean(x) for x in a[:5])
    opts = a[5:]

    def opt(flag, default=""):
        return _clean(opts[opts.index(flag) + 1]) if flag in opts and opts.index(flag) + 1 < len(opts) else default

    date = opt("--date", time.strftime("%Y-%m-%d"))
    nxt = opt("--next")
    notes = opt("--notes")
    tracker = opt("--tracker", _default_tracker())
    proof = opt("--proof")
    force_append = "--append-new" in opts

    if not (company and role and status):
        print("FAIL: Company, Role and Status are required")
        return 2
    if "SID=" in url:
        print("FAIL: refusing to log a session-bound index.cgi?SID=… URL — log the "
              "stable form instead (CSJ: jobs.cgi?jcode=<id>; see sites/civilservicejobs/NOTES.md)")
        return 2

    # HARD RULE: Status "Applied" requires a real confirmation artifact. See module
    # docstring. Unconfirmable submissions must use "Applied?"; no-evidence rows
    # "Unverified". Both bypass this gate.
    if status.strip().lower() == "applied":
        if not proof:
            print("FAIL: Status 'Applied' requires --proof <path> to a confirmation "
                  "screenshot/text (proof the submission went through). Capture it into "
                  "applications/<slug>/confirmation.png first. If the submission cannot be "
                  "confirmed, log Status 'Applied?' instead; if there's no evidence at all, "
                  "'Unverified'.")
            return 2
        if not (os.path.isfile(proof) and os.path.getsize(proof) > 0):
            print(f"FAIL: --proof {proof!r} does not exist or is empty — cannot log 'Applied' "
                  "without a real confirmation artifact. Use 'Applied?' if unconfirmable.")
            return 2
        pnote = f"proof={os.path.basename(proof)}"
        notes = f"{notes + ' ' if notes else ''}{pnote}"

    # A.4: hold the tracker lock across read→decide→write so a concurrent APPEND can't
    # be silently clobbered by another process's full-rewrite (lost-append race). The
    # update path is already atomic (tmp+os.replace); the lock closes append-vs-rewrite.
    with file_lock(tracker):
        try:
            rows, fieldnames = load_rows(tracker)
        except (OSError, csv.Error) as e:
            print(f"FAIL: cannot read tracker {tracker!r}: {e}")
            return 2
        if fieldnames != COLS:
            print(f"FAIL: tracker header {fieldnames} != expected {COLS} — refusing to write")
            return 2

        idx = -1 if force_append else find_match(rows, url, company, role)

        if idx < 0:
            # APPEND — O_APPEND write, no rewrite of existing content.
            row = {"Date": date, "Company": company, "Role": role, "Source": source,
                   "URL": url, "Status": status, "Next Action": nxt, "Notes": notes}
            try:
                with open(tracker, "a", newline="", encoding="utf-8") as f:
                    csv.DictWriter(f, fieldnames=COLS).writerow(row)
            except OSError as e:
                print(f"FAIL: append: {e}")
                return 2
            print(f"APPENDED: {company} | {role} | {status}")
            return 0

        # UPDATE in place (SKILL.md step 8) — keep the existing URL (live dedup key);
        # a different new URL goes into Notes so its id is greppable on the same line.
        r = rows[idx]
        old_status = r.get("Status", "")
        r["Date"], r["Status"] = date, status
        if nxt:
            r["Next Action"] = nxt
        if url and r.get("URL") and url != r["URL"] and not (canon_ids(url) & canon_ids(r["URL"])):
            notes = f"{notes + ' ' if notes else ''}ATS: {url}"
        elif url and not r.get("URL"):
            r["URL"] = url
        if notes:
            r["Notes"] = f"{r['Notes']} | {notes}".strip(" |") if r.get("Notes") else notes

        try:
            fd, tmp = tempfile.mkstemp(dir=os.path.dirname(tracker), suffix=".csv")
            with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=COLS)
                w.writeheader()
                w.writerows(rows)
            os.replace(tmp, tracker)
        except OSError as e:
            print(f"FAIL: rewrite: {e}")
            return 2
        print(f"UPDATED row {idx + 2}: {r['Company']} | {r['Role']} | {old_status or '(blank)'} -> {status}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
