#!/usr/bin/env python3
"""
journal.py — per-posting apply journal (feature-roadmap H.8).

WHY THIS EXISTS. The attempt-cap rule ("2 real attempts, then Blocked") and the
double-submit guard ("no confirmation ⇒ not Applied, but never re-fill a form you already
submitted") are enforced today only by the model remembering what it did this turn. Across
a wedge / tab death / a resumed firing that memory is gone, so a re-entry either re-fills a
form that was already submitted (double-submit risk) or gives up on one that only needed
its confirmation captured. This module makes the per-posting history DURABLE and queryable:
each driver appends step events to `applications/<slug>/journal.jsonl`, and on re-entry a
driver (or the N.3 blocker-resume pass) reads the journal to decide what to do next instead
of starting over.

Event stream (append-only JSONL, one object per line):
    {"ts": "2026-07-17T14:03:22", "event": "opened",   "url": "…"}
    {"ts": …, "event": "filled",    "step": "contact"}
    {"ts": …, "event": "uploaded",  "file": "resume.pdf"}
    {"ts": …, "event": "submitted"}                 # clicked submit; NOT yet confirmed
    {"ts": …, "event": "confirmed",  "proof": "confirmation.png"}
    {"ts": …, "event": "blocked",    "reason": "hCaptcha"}
    {"ts": …, "event": "attempt",    "note": "no forward progress"}

Canonical states (last_state): opened < filled < uploaded < submitted < confirmed, plus the
terminal side-markers blocked / skipped. The two load-bearing queries:
  * is_submitted_unconfirmed(slug) — journal shows `submitted` but no `confirmed` ⇒ on
    re-entry GO VERIFY (capture proof / check the ATS dashboard), NEVER re-fill.
  * attempts(slug) — count of no-progress attempts, so the "2 attempts then Blocked" cap is
    enforceable in code rather than by memory.

Best-effort: a journal write must NEVER break an application, so record() swallows OSError.
Uses fsutil.locked_append so concurrent drivers can't interleave lines.
"""
import json
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fsutil import locked_append  # noqa: E402

_here = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_here, "..", "..", ".."))
APPS = os.path.join(_ROOT, "applications")

# canonical forward-progress ordering (higher = further along)
_ORDER = {"opened": 1, "filled": 2, "uploaded": 3, "submitted": 4, "confirmed": 5}
_TERMINAL = {"confirmed", "blocked", "skipped"}


def slugify(company, role=""):
    """applications/<slug>/ folder name from company[+role] — mirrors the loop's
    `applications/<company>-<role>/` convention (lowercase, non-alnum -> '-')."""
    s = f"{company or ''}-{role or ''}".strip("-")
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s or "unknown"


def _dir(slug):
    return os.path.join(APPS, slug)


def _path(slug):
    return os.path.join(_dir(slug), "journal.jsonl")


def record(slug, event, now=None, **fields):
    """Append one event to applications/<slug>/journal.jsonl (creating the dir). Extra
    kwargs become event fields. Best-effort — never raises."""
    if not slug or not event:
        return False
    obj = {"ts": (now or datetime.now()).strftime("%Y-%m-%dT%H:%M:%S"), "event": event}
    for k, v in fields.items():
        if v is not None:
            obj[k] = v
    try:
        os.makedirs(_dir(slug), exist_ok=True)
        locked_append(_path(slug), lambda f: f.write(json.dumps(obj, ensure_ascii=False) + "\n"))
        return True
    except OSError:
        return False


def events(slug):
    """All journal events for a slug, in order. [] if none."""
    out = []
    try:
        with open(_path(slug), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    except (FileNotFoundError, OSError):
        pass
    return out


def last_state(slug):
    """The furthest-along forward-progress state reached (opened…confirmed), or a terminal
    side-marker if the last meaningful event was blocked/skipped, or None if no journal."""
    evs = events(slug)
    if not evs:
        return None
    best, best_rank = None, 0
    terminal = None
    for e in evs:
        ev = e.get("event")
        if ev in _TERMINAL and ev != "confirmed":
            terminal = ev
        elif ev in _ORDER:
            # A later forward-progress event clears a stale terminal marker, so a posting
            # that was blocked/skipped and then retried into progress reports its forward
            # state — honouring the docstring's "if the LAST meaningful event was
            # blocked/skipped" rather than making a once-seen `blocked` permanently sticky.
            terminal = None
        r = _ORDER.get(ev, 0)
        if r > best_rank:
            best, best_rank = ev, r
    if best == "confirmed":
        return "confirmed"
    return terminal or best


def is_submitted_unconfirmed(slug):
    """True iff a `submitted` event exists with NO later `confirmed` — the re-entry state
    that means 'go verify / capture proof, do NOT re-fill' (double-submit guard)."""
    submitted = confirmed = False
    for e in events(slug):
        if e.get("event") == "submitted":
            submitted = True
        elif e.get("event") == "confirmed":
            confirmed = True
    return submitted and not confirmed


def is_confirmed(slug):
    return any(e.get("event") == "confirmed" for e in events(slug))


def attempts(slug):
    """Number of recorded no-forward-progress `attempt` events (the 2-attempt cap counter)."""
    return sum(1 for e in events(slug) if e.get("event") == "attempt")


def _cli(argv):
    cmd = argv[1] if len(argv) > 1 else ""

    def opt(flag, default=""):
        return argv[argv.index(flag) + 1] if flag in argv and argv.index(flag) + 1 < len(argv) else default

    if cmd == "record" and len(argv) >= 4:
        extra = {}
        for flag in ("--url", "--step", "--file", "--reason", "--proof", "--note"):
            v = opt(flag)
            if v:
                extra[flag.lstrip("-")] = v
        print("ok" if record(argv[2], argv[3], **extra) else "FAIL")
        return 0
    if cmd == "state" and len(argv) >= 3:
        print(last_state(argv[2]) or "(none)")
        return 0
    if cmd == "check" and len(argv) >= 3:
        slug = argv[2]
        print(f"slug={slug} state={last_state(slug)} "
              f"submitted_unconfirmed={is_submitted_unconfirmed(slug)} "
              f"attempts={attempts(slug)}")
        return 0
    if cmd == "show" and len(argv) >= 3:
        for e in events(argv[2]):
            print(json.dumps(e, ensure_ascii=False))
        return 0
    if cmd == "slug" and len(argv) >= 3:
        print(slugify(argv[2], argv[3] if len(argv) > 3 else ""))
        return 0
    print("Usage: journal.py record <slug> <event> [--url u --step s --file f --reason r "
          "--proof p --note n] | state <slug> | check <slug> | show <slug> | "
          "slug <company> [role]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(_cli(sys.argv))
