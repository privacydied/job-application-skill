#!/usr/bin/env python3
"""
sentinel.py — browser-free continuous sourcing over the keyless HTTP feeds
(feature-roadmap N.1).

WHY THIS EXISTS. The scarce, serialized resource in this skill is the ONE camofox tab —
every browser-driven feed and every apply competes for it. But a whole class of feeds needs
NO browser at all: the keyless JSON/RSS APIs (Remotive, Jobicy, Himalayas, Escape the City,
Third Sector, MBW, HN Who-is-hiring). Those can be polled continuously in the background, on
a cron, with zero contention for the apply tab. So sourcing becomes CONTINUOUS instead of
"whatever the next firing has time to do first," and fresh postings enter the queue at poll
time rather than next-run time (early applications convert measurably better).

This is the browser-free sibling of warm_queue.py: where warm_queue runs the WHOLE pipeline
(browser feeds included) and needs a live tab, sentinel restricts to the HTTP-only boards and
needs NO tab. It calls the SAME importable funnel (pipeline.run) — it does NOT re-implement
sourcing/merge/precheck (that parallel-orchestrator re-implementation is the documented root
cause of the check_title-divergence bug class). It just scopes the funnel to browser-free
boards and runs often.

Safe by construction:
  * pipeline.run self-gates on the checkpoint (SLEEP/DONE/HOLD -> sources nothing).
  * HTTP-only boards never touch the tab, so a sentinel poll can NEVER wade into a
    mid-application CAPTCHA or wedge the apply session.
  * It writes the SAME queue.jsonl (atomic+locked) the loop reads.

Default board set = the keyless, browser-free feeds. Key-gated HTTP feeds (adzuna/reedapi/
jooble/careerjet) are included ONLY when their credential row is present (each feed self-
guards and exits 2 otherwise, which the funnel tolerates).

CRON (every 2h; browser-free so no .jobenv/tab needed — though sourcing env is harmless):
  0 */2 * * * cd /…/job-application && python3 scripts/sentinel.py >> sentinel.log 2>&1

Usage: sentinel.py [--boards a,b] [--target N] [--screen] [--once] [-o queue.jsonl]
  --screen  also JD-screen survivors (still browser-free for these API boards — the JD ships
            in the API row for most, so screening is cheap HTTP). Default: no-screen metadata
            queue (fastest; the loop screens at apply time).
"""
import os
import sys
import time

_here = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_here)
sys.path.insert(0, os.path.join(_ROOT, "sites", "_common", "scripts"))
import pipeline      # noqa: E402
import httpfeed      # noqa: E402  (creds_row — gate key-based feeds on their credential row)

LOG = os.path.join(_ROOT, "sentinel.log")

# Keyless, browser-free feeds (fetch="http", no login). Safe to poll continuously.
KEYLESS_HTTP = ["remotive", "jobicy", "himalayas", "hn", "escapecity", "thirdsector", "mbw"]

# Key-gated HTTP feeds: included only when their ats-credentials.csv row exists.
KEY_GATED = {
    "adzuna": "adzuna-api",
    "reedapi": "reed.co.uk",
    "jooble": "jooble",
    "careerjet": "careerjet",
}


def _available_key_gated():
    out = []
    for board, row_prefix in KEY_GATED.items():
        email, pw = httpfeed.creds_row(row_prefix)
        if email or pw:
            out.append(board)
    return out


def default_boards():
    return KEYLESS_HTTP + _available_key_gated()


def _logline(msg):
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {msg}"
    print(line)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def main():
    argv = sys.argv[1:]

    def opt(flag, default=None):
        return argv[argv.index(flag) + 1] if flag in argv and argv.index(flag) + 1 < len(argv) else default

    boards_arg = opt("--boards")
    boards = boards_arg.split(",") if boards_arg else default_boards()
    target = opt("--target")
    out_path = opt("-o")
    no_screen = "--screen" not in argv

    t0 = time.time()
    try:
        result, code = pipeline.run(
            target=int(target) if (target and target.isdigit()) else None,
            no_screen=no_screen,
            force=False,
            only_boards=boards,
            out_path=out_path,
        )
    except Exception as e:  # noqa: BLE001 — a sentinel poll must never crash the cron
        _logline(f"ERROR: pipeline.run raised: {e}")
        return 0

    verdict = result.get("verdict")
    if verdict != "WORK":
        _logline(f"verdict={verdict} (nothing sourced) in {time.time()-t0:.0f}s")
        return 0
    c = result.get("counts", {})
    _logline(f"sourced {c.get('sourced', 0)} from {sorted(boards)} -> "
             f"{c.get('queued', 0)} queued ({c.get('keep', 0)} keep, {c.get('review', 0)} "
             f"review); {len(result.get('errors', []))} feed err(s) in {time.time()-t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
