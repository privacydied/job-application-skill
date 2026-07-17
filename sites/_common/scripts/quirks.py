#!/usr/bin/env python3
"""
quirks.py — board quirks as structured, self-serve, staleness-dated DATA (feature-roadmap X.3).

WHY THIS EXISTS. Board quirks live as prose in sites/<board>/NOTES.md — great for humans, but
a driver can't consult them, and their freshness is a vibe ("verified 2026-07-16" buried in a
paragraph) rather than a checkable date. This makes each quirk a row in
sites/<board>/quirks.jsonl:
    {"symptom": "...", "cause": "...", "fix": "...", "verified": "YYYY-MM-DD", "expires": "..."?}
so:
  * drivers self-serve (e.g. atsform can consult the board's quirks before filling),
  * brief.py surfaces them in a task briefing,
  * doctor.py (H.7) flags rows past their `verified`+staleness window (or explicit `expires`)
    for re-check — staleness gets a DATE instead of a vibe, directly serving the "verify live,
    never trust stale notes" rule.
NOTES.md stays the human narrative; quirks.jsonl is the machine-checkable extract.

API:
  get(board) -> [quirk dicts]         # all quirks for a board
  add(board, symptom, fix, cause="", verified="", expires="")  # append one (best-effort)
  stale(board=None, now=None, max_age_days=45) -> [(board, quirk, why)]  # for doctor.py

CLI:
  quirks.py get <board>
  quirks.py add <board> --symptom "..." --fix "..." [--cause ..] [--verified YYYY-MM-DD] [--expires ..]
  quirks.py stale [--days 45]
"""
import json
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fsutil import locked_append  # noqa: E402

_here = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_here, "..", "..", ".."))
SITES = os.path.join(_ROOT, "sites")

# board token -> site dir (kept aligned with brief.BOARD_DIRS / pipeline.FEEDS dirs)
def _board_dir(board):
    # direct match first, then a fuzzy contains-match over the sites/ dirs
    cand = os.path.join(SITES, board)
    if os.path.isdir(cand):
        return cand
    try:
        for d in os.listdir(SITES):
            if board in d or d.split(".")[0] == board:
                return os.path.join(SITES, d)
    except OSError:
        pass
    return cand


def _path(board):
    return os.path.join(_board_dir(board), "quirks.jsonl")


def get(board):
    out = []
    try:
        with open(_path(board), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        continue
    except (FileNotFoundError, OSError):
        pass
    return out


def add(board, symptom, fix, cause="", verified="", expires="", now=None):
    verified = verified or (now or datetime.now()).strftime("%Y-%m-%d")
    rec = {"symptom": symptom, "cause": cause, "fix": fix, "verified": verified}
    if expires:
        rec["expires"] = expires
    d = _board_dir(board)
    try:
        os.makedirs(d, exist_ok=True)
        locked_append(_path(board), lambda f: f.write(json.dumps(rec, ensure_ascii=False) + "\n"))
        return True
    except OSError:
        return False


def _all_boards():
    try:
        return [d for d in os.listdir(SITES)
                if os.path.isfile(os.path.join(SITES, d, "quirks.jsonl"))]
    except OSError:
        return []


def stale(board=None, now=None, max_age_days=45):
    """Quirks past an explicit `expires` date, or older than max_age_days since `verified`.
    Returns [(board, quirk, why)]."""
    now = now or datetime.now()
    boards = [board] if board else _all_boards()
    out = []
    for b in boards:
        for q in get(b):
            exp = q.get("expires")
            if exp:
                try:
                    if datetime.strptime(exp, "%Y-%m-%d") < now:
                        out.append((b, q, f"expired {exp}"))
                        continue
                except ValueError:
                    pass
            ver = q.get("verified")
            if ver:
                try:
                    age = (now - datetime.strptime(ver, "%Y-%m-%d")).days
                    if age > max_age_days:
                        out.append((b, q, f"verified {ver} ({age}d ago > {max_age_days}d)"))
                except ValueError:
                    out.append((b, q, f"unparseable verified={ver!r}"))
            else:
                out.append((b, q, "no verified date"))
    return out


def _cli(argv):
    cmd = argv[1] if len(argv) > 1 else ""

    def opt(flag, default=""):
        return argv[argv.index(flag) + 1] if flag in argv and argv.index(flag) + 1 < len(argv) else default

    if cmd == "get" and len(argv) >= 3:
        for q in get(argv[2]):
            print(json.dumps(q, ensure_ascii=False))
        return 0
    if cmd == "add" and len(argv) >= 3:
        ok = add(argv[2], opt("--symptom"), opt("--fix"), opt("--cause"),
                 opt("--verified"), opt("--expires"))
        print("added" if ok else "FAIL")
        return 0 if ok else 2
    if cmd == "stale":
        days = int(opt("--days", "45"))
        rows = stale(max_age_days=days)
        if not rows:
            print(f"no stale quirks (all verified within {days}d / not expired).")
            return 0
        for b, q, why in rows:
            print(f"[{b}] {why}: {q.get('symptom','?')[:70]}")
        return 0
    print("Usage: quirks.py get <board> | add <board> --symptom .. --fix .. "
          "[--cause --verified --expires] | stale [--days N]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(_cli(sys.argv))
