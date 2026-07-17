#!/usr/bin/env python3
"""
outcomes.py — the outcome feedback loop (feature-roadmap M.3).

WHY THIS EXISTS. apply_rank + fit_score optimize for SUBMITTING; the real objective is
INTERVIEWS. Nothing today flows back from what happens AFTER a submit — response emails
(rejection / assessment / interview / offer) are read by a human, if at all, and the tracker's
post-Applied statuses are updated by hand. This closes the loop:
  * apply(events) — takes classified response events (from email_ingest.py responses) and
    updates the matching tracker row's Status (Applied -> Phone screen / Interview / Rejected /
    Offer), via log-application.py so the write stays dedup-safe + atomic.
  * aggregate() — computes per-family / per-board / per-ATS conversion (applied -> any positive
    response) into outcome-stats.csv, so sourcing effort and the fit-score weighting can lean
    toward what actually GENERATES interviews, not just what submits.

This also kills the manual tracker-status upkeep the loop never really did.

outcome-stats.csv (skill root) columns: dimension,key,applied,responses,positive,rate,updated
  dimension  one of family|board|ats
  key        e.g. design | reed | greenhouse
  applied    tracker rows for this key that reached >= Applied
  responses  rows with any post-Applied status (screen/interview/offer/rejected)
  positive   rows with a POSITIVE post-Applied status (screen/interview/offer)
  rate       positive / applied

Status ladder (SKILL.md): Saved < Applied < Phone screen < Interview < Offer; Rejected is
terminal-negative. This never DOWNGRADES a row (an Interview row stays Interview even if a
later "unfortunately" email arrives for a different role at the same company — matched by
company+role, and positive-forward only).

CLI:
  outcomes.py apply <events.json|->     # apply classified response events to the tracker
  outcomes.py aggregate                 # recompute outcome-stats.csv + print the table
  outcomes.py rates [family|board|ats]  # print conversion rates for a dimension
"""
import csv
import json
import os
import subprocess
import sys
from datetime import datetime

_here = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_here, "..", "..", ".."))
sys.path.insert(0, _here)
from precheck import _norm  # noqa: E402
import pipeline  # noqa: E402  (family_of + ats_hint — one classifier, no divergence)

TRACKER = os.path.join(_ROOT, "application-tracker.csv")
STATS = os.path.join(_ROOT, "outcome-stats.csv")
LOG_APP = os.path.join(_here, "log-application.py")

# post-Applied statuses and their rank (higher = further along). Rejected is negative.
_POSITIVE = {"phone screen": 2, "interview": 3, "offer": 4}
_STATUS_RANK = {"applied": 1, "phone screen": 2, "interview": 3, "offer": 4, "rejected": 1}
# email_ingest status -> tracker Status
_MAP = {"Interview": "Interview", "Offer": "Offer", "Assessment": "Phone screen",
        "Rejected": "Rejected"}


def _read_tracker():
    try:
        with open(TRACKER, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except (OSError, csv.Error):
        return []


def apply_events(events, now=None):
    """Update tracker rows from classified response events. Matches by normalized company
    (+ role when the event carries one). Only moves a row FORWARD along the ladder. Uses
    log-application.py so the write is dedup-safe/atomic. Returns (updated, unmatched)."""
    now = now or datetime.now()
    rows = _read_tracker()
    updated, unmatched = [], []
    for ev in events:
        status = _MAP.get(ev.get("status"))
        comp = _norm(ev.get("company"))
        if not status or not comp:
            unmatched.append(ev)
            continue
        # find the applied row(s) for this company (most recent first by list order end)
        cand = [r for r in rows if _norm(r.get("Company")) == comp
                and (r.get("Status") or "").strip().lower() in _STATUS_RANK]
        if ev.get("role"):
            role = _norm(ev["role"])
            cand = [r for r in cand if role in _norm(r.get("Role")) or _norm(r.get("Role")) in role] or cand
        if not cand:
            unmatched.append(ev)
            continue
        r = cand[-1]
        cur_rank = _STATUS_RANK.get((r.get("Status") or "").strip().lower(), 0)
        new_rank = _STATUS_RANK.get(status.lower(), 0)
        # forward-only for positives; a Rejected only applies to a still-Applied row.
        if status == "Rejected":
            if (r.get("Status") or "").strip().lower() != "applied":
                continue
        elif new_rank <= cur_rank:
            continue
        try:
            subprocess.run([sys.executable, LOG_APP, r.get("Company"), r.get("Role"),
                            r.get("Source") or "", r.get("URL") or "", status,
                            "--notes", f"outcome-email {now.strftime('%Y-%m-%d')}"],
                           cwd=_ROOT, env=os.environ, timeout=30,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            updated.append((r.get("Company"), r.get("Role"), status))
        except Exception:  # noqa: BLE001
            unmatched.append(ev)
    return updated, unmatched


def aggregate():
    """Recompute per-family/board/ats conversion from the tracker; write outcome-stats.csv.
    Returns the stats rows."""
    rows = _read_tracker()
    dims = {"family": {}, "board": {}, "ats": {}}

    def bump(dim, key, applied, responded, positive):
        d = dims[dim].setdefault(key, {"applied": 0, "responses": 0, "positive": 0})
        d["applied"] += applied
        d["responses"] += responded
        d["positive"] += positive

    for r in rows:
        st = (r.get("Status") or "").strip().lower()
        if st not in _STATUS_RANK and st not in _POSITIVE and st != "rejected":
            continue
        if st not in _STATUS_RANK:
            continue
        applied = 1
        responded = 1 if st != "applied" else 0
        positive = 1 if st in _POSITIVE else 0
        fam = pipeline.family_of(r.get("Role") or "")
        board = _norm(r.get("Source") or "") or "unknown"
        ats = pipeline.ats_hint(r.get("URL") or "", board)
        bump("family", fam, applied, responded, positive)
        bump("board", board, applied, responded, positive)
        bump("ats", ats, applied, responded, positive)

    out_rows = []
    day = datetime.now().strftime("%Y-%m-%d")
    for dim, keys in dims.items():
        for key, d in sorted(keys.items()):
            rate = round(d["positive"] / d["applied"], 4) if d["applied"] else 0.0
            out_rows.append({"dimension": dim, "key": key, "applied": d["applied"],
                             "responses": d["responses"], "positive": d["positive"],
                             "rate": rate, "updated": day})
    try:
        from fsutil import file_lock, atomic_write
        header = ["dimension", "key", "applied", "responses", "positive", "rate", "updated"]

        def _w(f):
            w = csv.DictWriter(f, fieldnames=header)
            w.writeheader()
            w.writerows(out_rows)
        with file_lock(STATS):
            atomic_write(STATS, _w)
    except OSError:
        pass
    return out_rows


def rates(dimension="family"):
    """{key: rate} for a dimension, from the last aggregate() (recomputes if stale/missing)."""
    if not os.path.exists(STATS):
        aggregate()
    out = {}
    try:
        with open(STATS, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("dimension") == dimension:
                    try:
                        out[row["key"]] = float(row["rate"])
                    except (ValueError, KeyError):
                        pass
    except (OSError, csv.Error):
        pass
    return out


def _cli(argv):
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "apply" and len(argv) >= 3:
        src = argv[2]
        try:
            raw = sys.stdin.read() if src == "-" else open(src, encoding="utf-8").read()
            events = json.loads(raw)
        except (OSError, ValueError) as e:
            print(f"FAIL: {e}", file=sys.stderr)
            return 2
        updated, unmatched = apply_events(events if isinstance(events, list) else [])
        for c, r, s in updated:
            print(f"  {c} | {r} -> {s}")
        print(f"outcomes: updated {len(updated)}, unmatched {len(unmatched)}.")
        aggregate()
        return 0
    if cmd == "aggregate":
        rows = aggregate()
        for r in rows:
            print(f"{r['dimension']:<7} {r['key']:<22} applied={r['applied']:>4} "
                  f"positive={r['positive']:>3} rate={r['rate']:.3f}")
        print(f"\n-> {STATS}")
        return 0
    if cmd == "rates":
        dim = argv[2] if len(argv) > 2 else "family"
        for k, v in sorted(rates(dim).items(), key=lambda kv: -kv[1]):
            print(f"{k:<22} {v:.3f}")
        return 0
    print("Usage: outcomes.py apply <events.json|-> | aggregate | rates [family|board|ats]",
          file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(_cli(sys.argv))
