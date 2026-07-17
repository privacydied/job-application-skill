#!/usr/bin/env python3
"""
status_dashboard.py — maintain status.json, the glance-able session dashboard
(feature-roadmap X.4).

WHY. Session start = one read instead of a dozen probes; and it's the artifact a human
glances at between sessions ("where's the queue, what's blocked, what's the count?"). The
daemon (warm_queue/sentinel cron) refreshes it; a human runs it ad-hoc. It just serializes
state_view.compute() to status.json (atomic write) and prints a compact human summary.

CRON (append to the warm/sentinel cron, or run standalone every 15 min):
  */15 * * * * cd /…/job-application && python3 scripts/status_dashboard.py --quiet >> status.log 2>&1

Usage:
  status_dashboard.py            # write status.json + print the summary
  status_dashboard.py --health   # also probe backend health (needs CFX_KEY)
  status_dashboard.py --quiet    # write only, no stdout summary
  status_dashboard.py --json     # print the full JSON
"""
import json
import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_here)
sys.path.insert(0, os.path.join(_ROOT, "sites", "_common", "scripts"))
import state_view  # noqa: E402
from fsutil import file_lock, atomic_write  # noqa: E402

STATUS = os.path.join(_ROOT, "status.json")


def main():
    argv = sys.argv[1:]
    status = state_view.compute(with_health="--health" in argv)
    try:
        with file_lock(STATUS):
            atomic_write(STATUS, lambda f: f.write(json.dumps(status, ensure_ascii=False, indent=2)))
    except OSError as e:
        print(f"WARN: could not write status.json: {e}", file=sys.stderr)

    if "--json" in argv:
        print(json.dumps(status, ensure_ascii=False, indent=2))
        return 0
    if "--quiet" in argv:
        return 0

    q = status["queue"]
    print(f"── job-apply status @ {status['generated_at']} ──")
    print(f"Applied (strict): {status['applied_strict']}  (today {status['applied_today']})  "
          f"| tracker rows {status['tracker_rows']}")
    print(f"Queue: {q['depth']} rows  by ATS {q['by_ats']}  by family {q['by_family']}")
    cds = status["cooldowns_active"]
    if cds:
        soon = ", ".join(f"{c['board']}({c['hours_left']}h)" for c in cds[:5])
        print(f"Cooldowns active: {len(cds)}  soonest: {soon}")
    if status["blockers_open"]:
        print(f"⚠️ OPEN BLOCKERS ({len(status['blockers_open'])}): "
              + "; ".join(f"{b['kind']}@{b['site']}" for b in status["blockers_open"][:4]))
    if status["suspect_verdicts"]:
        print(f"⚠️ SUSPECT verdicts to re-validate: {len(status['suspect_verdicts'])} "
              f"(run verdicts.py pending)")
    if status["accounts_needed_top"]:
        top = status["accounts_needed_top"][0]
        print(f"➤ Top account wall: {top['ats']} ({top['blocked']} blocked, "
              f"~{top['est_inventory']} inventory) — accounts.py ranked")
    if status.get("canary"):
        cv = status["canary"]
        print(f"Canary: {cv.get('verdict', '?')} @ {cv.get('checked_at', '?')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
