#!/usr/bin/env python3
"""
stagetimer.py — lightweight per-stage wall-clock instrumentation for the apply loop.

WHY THIS EXISTS: "speed up inference" is only worth doing if inference is actually
the bottleneck. A run's wall-clock is split across sourcing, tailoring, PDF render,
form fill, and the browser's deliberate anti-detection pacing (cfx.sh/cfx.py inject
human-timing jitter + orientation dwells on every action). Before optimizing model
round-trips, measure where the seconds go. This records stage durations to
`run-timings.csv` at the skill root and reports the breakdown.

ON BY DEFAULT (2026-07-15) — a record is one appended CSV row (microseconds, a few
bytes), so it is left on so every real run self-instruments and `report` always has
fresh data. Disable only in an ultra-lean/CI context with STAGETIMER=0 (also: false/
no/off). It is safe wired into feed.py / make-pdf.sh / atsform.py: the row write is
best-effort and can never change timing or break a run.

Stages captured AUTOMATICALLY (no agent discipline needed — the
duration includes that stage's own browser/cfx pacing, which is the whole point):
  - source : one feed.py enumeration pass (LinkedIn/Indeed/WTTJ)
  - pdf    : one make-pdf.sh render+verify
  - fill   : one atsform.py `apply` (upload -> fill -> select -> radios -> review)

Stages the agent brackets by hand (model-driven, not a single process):
  - tailor : resume clone + cover-letter generation for one posting
  - any custom label (e.g. `screen`, `browser-wait`) via start/stop

CLI:
  stagetimer.py record <stage> <seconds> [meta]   append one measured row
  stagetimer.py start  <stage>                     mark a stage's start (marker file)
  stagetimer.py stop   <stage> [meta]              measure since start, record, clear
  stagetimer.py time   <stage> -- <cmd> [args...]  run cmd, time it, record its duration
  stagetimer.py report [run_id]                    per-stage totals / mean / median / p90 / %
  stagetimer.py reset                              delete run-timings.csv and any markers

Python use (inside a stage-owning script):
  import stagetimer
  with stagetimer.timed("fill"):
      ...                       # anything raised still records the elapsed time

Env:
  STAGETIMER       recording is ON unless set to 0/false/no/off (unset = ON)
  STAGETIMER_RUN   run id stamped on each row (default "adhoc") — set per profiling run
                   so `report <run_id>` can isolate one run's rows
"""
import csv
import os
import subprocess
import sys
import time

CSV_HEADER = ["ts", "run_id", "stage", "seconds", "meta"]


def enabled():
    """ON BY DEFAULT (2026-07-15 — timing rows are cheap and the data is what tells us
    where to optimize). Recording is a no-op ONLY when explicitly disabled:
    STAGETIMER in {0,false,no,off,""-set-empty}. Unset => enabled. This keeps a normal
    run self-instrumenting so `stagetimer.py report` always has fresh data, while an
    ultra-lean/CI context can still opt out with STAGETIMER=0."""
    v = os.environ.get("STAGETIMER")
    if v is None:
        return True
    return v.strip().lower() not in ("", "0", "false", "no", "off")


def _root():
    """Skill root = nearest ancestor of this file containing SKILL.md."""
    d = os.path.dirname(os.path.abspath(__file__))
    while True:
        if os.path.isfile(os.path.join(d, "SKILL.md")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            # fallback: three levels up (sites/_common/scripts -> root)
            return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        d = parent


def _csv_path():
    return os.path.join(_root(), "run-timings.csv")


def _marker_dir():
    d = os.path.join(_root(), ".timings")
    os.makedirs(d, exist_ok=True)
    return d


def _run_id():
    return os.environ.get("STAGETIMER_RUN") or "adhoc"


def _marker_path(stage):
    # Key the marker by run-id ONLY — NOT pid. The documented CLI workflow runs `start` and
    # `stop` as SEPARATE processes (e.g. the agent brackets the `tailor` stage: `stagetimer.py
    # start tailor` … `stagetimer.py stop tailor`), so a pid in the name made `stop`'s path
    # differ from `start`'s and it NEVER found the marker — silently recording nothing for
    # every hand-bracketed stage (on-by-default). Concurrent runs isolate via STAGETIMER_RUN
    # (the run-id); the in-process `timed()` path uses no marker at all, so pid never helped it.
    safe = "".join(c if (c.isalnum() or c in "-_") else "_" for c in stage)
    rid = "".join(c if (c.isalnum() or c in "-_") else "_" for c in _run_id())
    return os.path.join(_marker_dir(), f"{safe}.{rid}.start")


def record(stage, seconds, meta=""):
    """Append one measured stage row. No-op unless STAGETIMER is set."""
    if not enabled():
        return
    path = _csv_path()
    new = not os.path.exists(path)
    try:
        with open(path, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new:
                w.writerow(CSV_HEADER)
            w.writerow([
                time.strftime("%Y-%m-%dT%H:%M:%S"),
                _run_id(),
                stage,
                f"{float(seconds):.3f}",
                (meta or "").replace("\n", " ")[:200],
            ])
    except OSError as e:
        # Instrumentation must never break a real run.
        print(f"[stagetimer] could not write {path}: {e}", file=sys.stderr)


class timed:
    """Context manager: record elapsed wall-clock for `stage`, even on exception."""
    def __init__(self, stage, meta=""):
        self.stage = stage
        self.meta = meta

    def __enter__(self):
        self.t0 = time.time()
        return self

    def __exit__(self, *exc):
        record(self.stage, time.time() - self.t0, self.meta)
        return False  # never suppress


def start(stage):
    if not enabled():
        return
    try:
        with open(_marker_path(stage), "w", encoding="utf-8") as f:
            f.write(str(time.time()))
    except OSError as e:
        print(f"[stagetimer] start failed: {e}", file=sys.stderr)


def stop(stage, meta=""):
    if not enabled():
        return
    mp = _marker_path(stage)
    try:
        with open(mp, encoding="utf-8") as f:
            t0 = float(f.read().strip())
    except (OSError, ValueError):
        print(f"[stagetimer] stop '{stage}' with no matching start — ignored", file=sys.stderr)
        return
    record(stage, time.time() - t0, meta)
    try:
        os.remove(mp)
    except OSError:
        pass


def time_cmd(stage, argv):
    """Run argv, time it, record duration, propagate its exit code."""
    t0 = time.time()
    rc = subprocess.call(argv)
    record(stage, time.time() - t0, meta=" ".join(argv[:1]))
    return rc


def _pctl(sorted_vals, q):
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def report(run_id=None):
    path = _csv_path()
    if not os.path.exists(path):
        print(f"no timings yet ({path} does not exist — run with STAGETIMER=1 set)")
        return 0
    by_stage = {}
    total_all = 0.0
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if run_id and row.get("run_id") != run_id:
                continue
            try:
                secs = float(row["seconds"])
            except (KeyError, ValueError):
                continue
            by_stage.setdefault(row["stage"], []).append(secs)
            total_all += secs
    if not by_stage:
        print(f"no rows{f' for run {run_id}' if run_id else ''} in {path}")
        return 0
    scope = f" (run {run_id})" if run_id else " (all runs)"
    print(f"Stage timings{scope} — total measured wall-clock: {total_all:.1f}s\n")
    print(f"{'stage':<14}{'n':>4}{'total':>10}{'mean':>9}{'median':>9}{'p90':>9}{'% total':>9}")
    print("-" * 64)
    for stage in sorted(by_stage, key=lambda s: -sum(by_stage[s])):
        v = sorted(by_stage[stage])
        tot = sum(v)
        pct = (100 * tot / total_all) if total_all else 0
        print(f"{stage:<14}{len(v):>4}{tot:>9.1f}s{tot/len(v):>8.1f}s"
              f"{_pctl(v, .5):>8.1f}s{_pctl(v, .9):>8.1f}s{pct:>8.1f}%")
    print("\nNote: source/pdf/fill include their own browser/cfx anti-detection pacing —")
    print("a large 'fill' or 'source' is browser wall-clock, not model inference time.")
    return 0


def _reset():
    for p in (_csv_path(),):
        try:
            os.remove(p)
        except OSError:
            pass
    md = os.path.join(_root(), ".timings")
    if os.path.isdir(md):
        for name in os.listdir(md):
            try:
                os.remove(os.path.join(md, name))
            except OSError:
                pass
    print("timings reset")


def main(argv):
    if not argv:
        print(__doc__)
        return 1
    cmd = argv[0]
    if cmd == "record" and len(argv) in (3, 4):
        # record() self-gates on STAGETIMER (no-op when unset), but the seconds arg
        # still has to parse — guard it so a non-numeric value is a clean message,
        # not an uncaught ValueError traceback.
        try:
            secs = float(argv[2])
        except ValueError:
            print(f"record: seconds must be a number, got {argv[2]!r}", file=sys.stderr)
            return 1
        record(argv[1], secs, argv[3] if len(argv) == 4 else "")
        return 0
    if cmd == "start" and len(argv) == 2:
        start(argv[1]); return 0
    if cmd == "stop" and len(argv) in (2, 3):
        stop(argv[1], argv[2] if len(argv) == 3 else ""); return 0
    if cmd == "time" and "--" in argv:
        i = argv.index("--")
        stage = argv[1]
        sub = argv[i + 1:]
        if stage and sub:
            return time_cmd(stage, sub)
    if cmd == "report":
        return report(argv[1] if len(argv) == 2 else None)
    if cmd == "reset":
        _reset(); return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
