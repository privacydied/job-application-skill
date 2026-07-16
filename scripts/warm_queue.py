#!/usr/bin/env python3
"""
warm_queue.py — keep queue.jsonl warm between model firings (Tier-3 async). Run by cron
(code only, no model), it does the browser-bound sourcing so a model firing can start at
TAILOR with a ready, freshly-screened work list instead of spending its first ~30 turns
sourcing. Cooldown lapses get exploited the moment they happen, not at the next firing.

SAFE BY CONSTRUCTION:
  * It just calls pipeline.py, which self-gates on the checkpoint verdict — on SLEEP/
    DONE/HOLD it sources nothing and exits. So a warm run during a CAPTCHA hold or a
    finished day is a cheap no-op.
  * Default `--no-screen`: it only runs the FEEDS (the same navigations the loop does)
    and writes a metadata queue — it does NOT open individual JD pages, so it can't wade
    into a mid-application CAPTCHA. Pass `--screen` to also JD-screen (more complete
    queue, slightly more browser exposure) only when you trust the session.
  * One tab, serialized (pipeline's constraint). Never fans out.

It appends one line per run to warm-queue.log and leaves queue.jsonl in place for the
next firing. It requires CFX_KEY (and a tab) in the environment — the cron line sources
.jobenv first (see the crontab example below) and warm_queue ensures a live tab.

CRON (hourly; sources env, ensures perms, warms the queue — adjust the path):
  0 * * * * cd /…/job-application && . ./.jobenv 2>/dev/null; \
            python3 scripts/warm_queue.py >> warm-queue.log 2>&1

Usage: warm_queue.py [--screen] [--target N] [--boards a,b] [--once]
"""
import os
import subprocess
import sys
import time

_here = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_here)
sys.path.insert(0, os.path.join(_ROOT, "sites", "_common", "scripts"))

PIPELINE = os.path.join(_ROOT, "sites", "_common", "scripts", "pipeline.py")
LOG = os.path.join(_ROOT, "warm-queue.log")


def _stamp():
    # No Date.now-style forbidden calls here (plain script, not a workflow) — time is fine.
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _logline(msg):
    line = f"{_stamp()} {msg}"
    print(line)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def main():
    argv = sys.argv[1:]
    if not os.environ.get("CFX_KEY"):
        _logline("SKIP: no CFX_KEY in env (source .jobenv before running)")
        return 0

    # Ensure a live tab (camofox drops tabs between runs). Best-effort; bail cleanly.
    try:
        import cfx
        cfx.set_tab(cfx.ensure_tab(persist=False))
    except Exception as e:  # noqa: BLE001
        _logline(f"SKIP: could not ensure a tab ({e})")
        return 0

    cmd = [sys.executable, PIPELINE]
    if "--screen" not in argv:
        cmd.append("--no-screen")
    for flag in ("--target", "--boards"):
        if flag in argv:
            i = argv.index(flag)
            if i + 1 < len(argv):
                cmd += [flag, argv[i + 1]]
    if "--force" in argv:
        cmd.append("--force")

    t0 = time.time()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, cwd=_ROOT,
                           env=os.environ, timeout=1800)
    except subprocess.TimeoutExpired:
        _logline("ERROR: pipeline timed out after 1800s")
        return 0
    dt = time.time() - t0
    # pipeline's last stderr line is its own summary; surface it + its exit code.
    tail = (p.stderr or "").strip().splitlines()[-1:] or ["(no summary)"]
    _logline(f"pipeline rc={p.returncode} in {dt:.0f}s :: {tail[0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
