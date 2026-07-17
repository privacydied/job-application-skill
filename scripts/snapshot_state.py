#!/usr/bin/env python3
"""
snapshot_state.py — timestamped local backups of the fragile run-state files
(feature-roadmap H.5).

WHY THIS EXISTS. `searches.csv` is NOT git-tracked and has NO backup — SKILL.md records it
being corrupted and rebuilt from `loop-preflight.py` output once already. The tracker has
its own truncate-on-throw data-loss scar. These files are regenerated/edited live and a
single bad write loses uncommitted work. This is one-evening insurance against that whole
class: copy the state files to `state-backups/<timestamp>/` on a schedule, rotate old
snapshots, done.

NB on git: the state files (application-tracker.csv, searches.csv, screener-answers.csv, …)
are ALL gitignored by design (the config-routing PII model — see AGENTS.md §PII). So this
tool does NOT `git add -f` them (that would defeat the PII model and .gitignore). The
timestamped local copies under state-backups/ (also gitignored) ARE the insurance. If you
want off-box durability, sync state-backups/ to your own storage out of band.

Files backed up (each if present):
    application-tracker.csv  searches.csv  screener-answers.csv  board-cooldown.csv
    apply-stats.csv  salary-cache.csv  search-yields.csv  queue.jsonl
    accounts-needed.csv  blockers.jsonl  outcome-stats.csv

Rotation: keep the newest --keep-days (default 14) days of snapshot dirs; older ones are
removed. A snapshot dir is named YYYY-MM-DDTHH-MM-SS.

CRON (every 6h; adjust the path):
  0 */6 * * * cd /…/job-application && python3 scripts/snapshot_state.py >> state-backups/snapshot.log 2>&1

Usage: snapshot_state.py [--keep-days N] [--dir <backups dir>]
"""
import os
import shutil
import sys
import time
from datetime import datetime, timedelta

_here = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_here)
BACKUPS = os.path.join(_ROOT, "state-backups")

STATE_FILES = [
    "application-tracker.csv", "searches.csv", "screener-answers.csv",
    "board-cooldown.csv", "apply-stats.csv", "salary-cache.csv",
    "search-yields.csv", "queue.jsonl", "accounts-needed.csv",
    "blockers.jsonl", "outcome-stats.csv",
]


def snapshot(backups_dir=BACKUPS, now=None):
    now = now or datetime.now()
    stamp = now.strftime("%Y-%m-%dT%H-%M-%S")
    dest = os.path.join(backups_dir, stamp)
    os.makedirs(dest, exist_ok=True)
    copied = []
    for name in STATE_FILES:
        src = os.path.join(_ROOT, name)
        if os.path.isfile(src):
            try:
                shutil.copy2(src, os.path.join(dest, name))
                copied.append(name)
            except OSError as e:
                print(f"WARN: could not copy {name}: {e}", file=sys.stderr)
    if not copied:
        # nothing to snapshot — don't leave an empty dir lying around
        try:
            os.rmdir(dest)
        except OSError:
            pass
    return dest, copied


def rotate(backups_dir=BACKUPS, keep_days=14, now=None):
    """Remove snapshot dirs older than keep_days. Robust to non-snapshot entries."""
    now = now or datetime.now()
    cutoff = now - timedelta(days=keep_days)
    removed = 0
    try:
        entries = os.listdir(backups_dir)
    except OSError:
        return 0
    for name in entries:
        path = os.path.join(backups_dir, name)
        if not os.path.isdir(path):
            continue
        try:
            when = datetime.strptime(name, "%Y-%m-%dT%H-%M-%S")
        except ValueError:
            continue  # not a snapshot dir
        if when < cutoff:
            try:
                shutil.rmtree(path)
                removed += 1
            except OSError:
                pass
    return removed


def main():
    argv = sys.argv[1:]

    def opt(flag, default):
        return argv[argv.index(flag) + 1] if flag in argv and argv.index(flag) + 1 < len(argv) else default

    backups_dir = opt("--dir", BACKUPS)
    try:
        keep_days = int(opt("--keep-days", "14"))
    except ValueError:
        keep_days = 14

    os.makedirs(backups_dir, exist_ok=True)
    dest, copied = snapshot(backups_dir)
    removed = rotate(backups_dir, keep_days=keep_days)
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
    if copied:
        print(f"{stamp} snapshot -> {os.path.basename(dest)} ({len(copied)} files: "
              f"{', '.join(copied)}); rotated {removed} old snapshot(s), keep_days={keep_days}")
    else:
        print(f"{stamp} nothing to snapshot (no state files present); rotated {removed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
