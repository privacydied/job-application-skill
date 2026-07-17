#!/usr/bin/env python3
"""
state_view.py — compute a single live-state snapshot from all the on-disk run-state
(feature-roadmap X.4 substrate; also feeds X.2 brief.py).

WHY THIS EXISTS. Session start today means a dozen separate probes — count the tracker, read
cooldowns, check the queue, look for blockers, guess at session health. This composes all of
it into ONE dict so `status.json` (a glance-able dashboard) and `brief.py` (the per-task
context compiler) both read live state from one place instead of each re-deriving it.

Pure-ish: reads only small on-disk state (no browser unless `with_health=True`, which does a
best-effort cfx.health_fingerprint). Never raises — a missing file degrades to a zero/empty
field.
"""
import json
import os
import sys
from collections import Counter
from datetime import datetime

_here = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_here, "..", "..", ".."))
sys.path.insert(0, _here)
import tracker_stats  # noqa: E402
import board_cooldown as bc  # noqa: E402

QUEUE = os.path.join(_ROOT, "queue.jsonl")
CANARY = os.path.join(_ROOT, "canary-status.json")


def _queue_summary():
    rows = []
    try:
        with open(QUEUE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except ValueError:
                        continue
    except (FileNotFoundError, OSError):
        pass
    return {
        "depth": len(rows),
        "by_ats": dict(Counter(r.get("ats_hint") or "unknown" for r in rows)),
        "by_family": dict(Counter(r.get("family") or "?" for r in rows)),
        "by_verdict": dict(Counter(r.get("verdict") or "?" for r in rows)),
        "top_fit": sorted(
            ({"title": r.get("title"), "company": r.get("company"),
              "fit": r.get("fit_score"), "ats": r.get("ats_hint")}
             for r in rows if r.get("fit_score") is not None),
            key=lambda x: -(x["fit"] or 0))[:5],
    }


def _cooldowns(now=None):
    now = now or datetime.now()
    rows = bc._read_rows()
    active = []
    for r in rows:
        board, query = r[0], r[1]
        rem = bc.remaining_hours(board, query, now=now, rows=rows)
        if rem > 0:
            active.append({"board": board, "query": query, "hours_left": round(rem, 1),
                           "daily_limit": query == bc.DAILY_LIMIT_KEY})
    active.sort(key=lambda x: x["hours_left"])
    return active


def _blockers():
    try:
        import blockers
        return [{"id": b["id"], "kind": b["kind"], "site": b.get("site"),
                 "what": b.get("what")} for b in blockers.pending()]
    except Exception:  # noqa: BLE001
        return []


def _suspects():
    try:
        import verdicts
        return [{"id": v["id"], "kind": v["kind"], "target": v.get("target")}
                for v in verdicts.pending()]
    except Exception:  # noqa: BLE001
        return []


def _accounts_top():
    try:
        import accounts
        r = accounts.ranked()
        return [{"ats": x["ats"], "blocked": int(x["blocked_count"]),
                 "est_inventory": int(x["est_inventory"])} for x in r[:3]]
    except Exception:  # noqa: BLE001
        return []


def _canary():
    try:
        with open(CANARY, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, OSError, ValueError):
        return None


def compute(with_health=False, now=None):
    now = now or datetime.now()
    ts = tracker_stats.stats(day=now.strftime("%Y-%m-%d"))
    status = {
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%S"),
        "applied_strict": ts["applied"],
        "applied_today": ts["applied_today"],
        "tracker_rows": ts["total_rows"],
        "by_status": ts["by_status"],
        "queue": _queue_summary(),
        "cooldowns_active": _cooldowns(now=now),
        "blockers_open": _blockers(),
        "suspect_verdicts": _suspects(),
        "accounts_needed_top": _accounts_top(),
        "canary": _canary(),
    }
    if with_health:
        try:
            import cfx
            status["backend_health"] = cfx.health_fingerprint()
        except Exception:  # noqa: BLE001
            status["backend_health"] = None
    return status
