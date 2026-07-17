#!/usr/bin/env python3
"""
accounts.py — the account-provisioning queue (feature-roadmap N.4).

WHY THIS EXISTS. Every volume saga in SKILL.md ends at the SAME wall: a downstream
employer-ATS / board *account* is needed to submit (amazon.jobs, CVLibrary, TotalJobs,
MoJ, …). Sourcing channels (Adzuna/WTTJ/Dots) enumerate huge on-profile inventories that
then can't be submitted because the account doesn't exist. Today that fact lives only as
prose scattered across references; there is no single answer to the one question that
actually unblocks volume: **"which ONE account-creation session unlocks the most
applications?"**

This module is that ledger. Every time a driver (or the loop) hits an account wall it
calls `record(ats, board=…, url=…, est_inventory=…)`. The ledger accumulates, per
account-target, how many distinct postings were blocked on it and the estimated blocked
inventory. `ranked()` answers the question above; the CLI prints it. A human then does one
batch account session (with SMS/email verification where needed), drops the creds into
ats-credentials.csv, and `scripts/triage_blocked.py` re-queues the blocked rows — the
retry plumbing already exists, this just tells you WHERE to spend the human minute.

accounts-needed.csv (skill root) columns:
    key,ats,board,blocked_count,est_inventory,first_seen,last_seen,signup_url,note
  key            normalized account-target slug (the join key; norm(ats or board))
  ats            the ATS/board family the account is for (amazon-jobs / cvlibrary / …)
  board          the sourcing board that surfaced the wall (adzuna / wttj / indeed / …)
  blocked_count  DISTINCT postings blocked on this account (deduped by canonical id)
  est_inventory  latest estimate of on-profile inventory behind this wall (max seen)
  first_seen     ISO date the wall was first recorded
  last_seen      ISO date last recorded
  signup_url     where to create the account (free-form; filled if known)
  note           short human note (what verification is needed, etc.)

record(...) is best-effort and never raises (a ledger write must never break an apply).
It routes through fsutil's locked atomic RMW, like apply_stats/board_cooldown.

CLI:
  accounts.py record <ats> [--board b] [--url u] [--est N] [--note "…"] [--posting <id/url>]
  accounts.py ranked            # the "spend the human minute here" view
  accounts.py list
  accounts.py resolve <ats>     # drop a row once the account exists (creds in the CSV)
"""
import csv
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fsutil import file_lock, atomic_write  # noqa: E402  (locked atomic RMW, Tier A)

_here = os.path.dirname(os.path.abspath(__file__))
CSV = os.path.join(_here, "..", "..", "..", "accounts-needed.csv")
# a sidecar set of the DISTINCT posting ids counted per key, so blocked_count is a true
# de-duplicated distinct-posting count across firings, not an every-attempt increment.
SEEN = os.path.join(_here, "..", "..", "..", ".accounts-postings.csv")
HEADER = ["key", "ats", "board", "blocked_count", "est_inventory",
          "first_seen", "last_seen", "signup_url", "note"]

# Known signup URLs for the account walls SKILL.md documents — pre-filled so `ranked`
# is directly actionable. Extend as new walls are learned (data, not driver logic).
KNOWN_SIGNUP = {
    "amazon-jobs": "https://www.amazon.jobs/ (create an account to apply)",
    "cvlibrary": "https://www.cv-library.co.uk/register (3-step; mandatory CV upload)",
    "totaljobs": "https://www.totaljobs.com/ (account required to apply)",
    "moj": "https://jobs.justice.gov.uk/ (register — email activation required)",
    "wellfound": "https://wellfound.com/ (login-gated; in-platform quick apply)",
    "workday": "per-employer myworkdayjobs.com account",
}


def _norm(s):
    import re
    return re.sub(r"[^a-z0-9]+", "-", (s or "").strip().lower()).strip("-")


def _read():
    rows = {}
    try:
        with open(CSV, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                k = (row.get("key") or "").strip()
                if not k:
                    continue
                try:
                    row["blocked_count"] = int(row.get("blocked_count") or 0)
                except ValueError:
                    row["blocked_count"] = 0
                try:
                    row["est_inventory"] = int(row.get("est_inventory") or 0)
                except ValueError:
                    row["est_inventory"] = 0
                rows[k] = row
    except (FileNotFoundError, OSError):
        pass
    return rows


def _read_seen():
    """key -> set(posting-id) already counted, so re-hitting the same posting's wall in a
    later firing doesn't double-count blocked_count. Best-effort."""
    seen = {}
    try:
        with open(SEEN, newline="", encoding="utf-8") as f:
            for row in csv.reader(f):
                if len(row) < 2:
                    continue
                seen.setdefault(row[0], set()).add(row[1])
    except (FileNotFoundError, OSError):
        pass
    return seen


def record(ats, board="", url="", est_inventory=None, note="", posting="", now=None):
    """Record (or increment) an account wall for `ats`. `posting` is a stable posting id or
    URL — when given, blocked_count only rises the FIRST time that posting is seen for this
    key (distinct-posting semantics). est_inventory keeps the MAX ever seen. Best-effort."""
    ats = (ats or "").strip()
    if not ats:
        return False
    key = _norm(ats)
    day = (now or datetime.now()).strftime("%Y-%m-%d")
    try:
        with file_lock(CSV):
            rows = _read()
            seen = _read_seen()
            cur = rows.get(key) or {
                "key": key, "ats": ats, "board": _norm(board), "blocked_count": 0,
                "est_inventory": 0, "first_seen": day, "last_seen": day,
                "signup_url": KNOWN_SIGNUP.get(key, ""), "note": note}
            # distinct-posting count
            counted = seen.setdefault(key, set())
            pid = (posting or "").strip().lower()
            newly = False
            if pid:
                if pid not in counted:
                    counted.add(pid)
                    cur["blocked_count"] = int(cur["blocked_count"]) + 1
                    newly = True
            else:
                cur["blocked_count"] = int(cur["blocked_count"]) + 1
                newly = True
            if board and not cur.get("board"):
                cur["board"] = _norm(board)
            if est_inventory is not None:
                try:
                    cur["est_inventory"] = max(int(cur["est_inventory"]), int(est_inventory))
                except (TypeError, ValueError):
                    pass
            if url and not cur.get("signup_url"):
                cur["signup_url"] = url
            elif not cur.get("signup_url"):
                cur["signup_url"] = KNOWN_SIGNUP.get(key, "")
            if note:
                cur["note"] = note
            cur["last_seen"] = day
            rows[key] = cur

            def _w(f):
                w = csv.DictWriter(f, fieldnames=HEADER)
                w.writeheader()
                for r in sorted(rows.values(),
                                key=lambda x: -int(x.get("blocked_count") or 0)):
                    w.writerow({k: r.get(k, "") for k in HEADER})
            atomic_write(CSV, _w)
            if newly and pid:
                # persist the distinct-posting sidecar (append the one new pair)
                try:
                    with open(SEEN, "a", newline="", encoding="utf-8") as f:
                        csv.writer(f).writerow([key, pid])
                except OSError:
                    pass
        return True
    except OSError:
        return False


def ranked():
    """Account targets ordered by leverage: primarily blocked_count, then est_inventory.
    This is the 'spend the human minute here' list."""
    rows = list(_read().values())
    rows.sort(key=lambda r: (int(r.get("blocked_count") or 0),
                             int(r.get("est_inventory") or 0)), reverse=True)
    return rows


def resolve(ats):
    """Drop a row once the account exists (its creds are in ats-credentials.csv). Returns
    True if a row was removed."""
    key = _norm(ats)
    with file_lock(CSV):
        rows = _read()
        if key not in rows:
            return False
        del rows[key]

        def _w(f):
            w = csv.DictWriter(f, fieldnames=HEADER)
            w.writeheader()
            for r in sorted(rows.values(), key=lambda x: -int(x.get("blocked_count") or 0)):
                w.writerow({k: r.get(k, "") for k in HEADER})
        atomic_write(CSV, _w)
    return True


def _cli(argv):
    cmd = argv[1] if len(argv) > 1 else ""

    def opt(flag, default=""):
        return argv[argv.index(flag) + 1] if flag in argv and argv.index(flag) + 1 < len(argv) else default

    if cmd == "record" and len(argv) >= 3:
        est = opt("--est")
        ok = record(argv[2], board=opt("--board"), url=opt("--url"),
                    est_inventory=int(est) if est.isdigit() else None,
                    note=opt("--note"), posting=opt("--posting"))
        print("recorded" if ok else "FAIL")
        return 0 if ok else 2
    if cmd == "ranked":
        rows = ranked()
        if not rows:
            print("no account walls recorded — nothing to provision.")
            return 0
        print(f"{'ATS/ACCOUNT':<18} {'BLOCKED':>7} {'EST_INV':>7}  SIGNUP / NOTE")
        for r in rows:
            tail = r.get("signup_url") or ""
            if r.get("note"):
                tail = f"{tail}  [{r['note']}]" if tail else f"[{r['note']}]"
            print(f"{r['ats']:<18} {int(r['blocked_count']):>7} "
                  f"{int(r['est_inventory']):>7}  {tail}")
        top = rows[0]
        print(f"\n➤ Highest leverage: create the {top['ats']} account "
              f"({int(top['blocked_count'])} postings blocked, ~{int(top['est_inventory'])} "
              f"est inventory). Then: add creds to ats-credentials.csv, run "
              f"scripts/triage_blocked.py, and accounts.py resolve {top['ats']}.")
        return 0
    if cmd == "list":
        for r in sorted(_read().values(), key=lambda x: x["key"]):
            print(f"{r['ats']}\t{r['blocked_count']}\t{r['est_inventory']}\t"
                  f"{r.get('board','')}\t{r.get('last_seen','')}\t{r.get('signup_url','')}")
        return 0
    if cmd == "resolve" and len(argv) >= 3:
        print("resolved" if resolve(argv[2]) else "not-found")
        return 0
    print("Usage: accounts.py record <ats> [--board b] [--url u] [--est N] [--note …] "
          "[--posting id] | ranked | list | resolve <ats>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(_cli(sys.argv))
