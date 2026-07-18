#!/usr/bin/env python3
"""
brief.py — per-task context compiler (feature-roadmap X.2).

WHY THIS EXISTS. SKILL.md is ~46KB loaded EVERY firing, plus a 45-reference corpus — and a
fresh instance re-derives the toolset from prose every time, which is precisely why shipped
tools keep getting re-implemented (perf-roadmap root cause #2: discoverability doesn't scale).
This compiles a SMALL, TASK-SCOPED briefing on demand: the relevant task→tool manifest rows,
the target board's verified quirks, and the LIVE state — so a firing reads ~2k tokens of
exactly-what-it-needs instead of the whole corpus. SKILL.md can then shrink toward: identity,
hard rules (CAPTCHA/integrity/PII), decision tree, and "run brief.py".

Input: an intent string — a free-form task like "apply reed", "source csj", "triage blocked",
"drain queue". brief.py picks the matching manifest rows + board (if named) and prints:
  1. the shipped tools for this task (from references/tool-manifest.md — never re-implement),
  2. the target board's quirks (sites/<board>/quirks.jsonl if present, else NOTES.md head),
  3. LIVE state (queue depth by ATS, active cooldowns, strict count, open blockers, top
     account wall) via state_view — so the briefing reflects NOW, not a stale note.

Usage:
  brief.py "apply reed"
  brief.py "source csj" --health
  brief.py --list-boards
"""
import json
import os
import re
import sys

_here = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_here)
sys.path.insert(0, os.path.join(_ROOT, "sites", "_common", "scripts"))
import state_view  # noqa: E402

MANIFEST = os.path.join(_ROOT, "references", "tool-manifest.md")
SITES = os.path.join(_ROOT, "sites")

# board token -> site dir (a subset of the important ones; falls back to a fuzzy dir match)
BOARD_DIRS = {
    "reed": "reed.co.uk", "csj": "civilservicejobs", "linkedin": "linkedin",
    "indeed": "indeed.com", "hackney": "hackney", "adzuna": "adzuna.co.uk",
    "wttj": "welcometothejungle", "cvlibrary": "cv-library.co.uk", "greenhouse": "greenhouse",
    "ashby": "ashbyhq", "workday": "myworkdayjobs", "remotive": "remotive.com",
    "jobicy": "jobicy.com", "hn": "news.ycombinator.com", "wellfound": "wellfound.com",
    "nhs": "jobs.nhs.uk", "guardian": "jobs.theguardian.com",
    "applicationtrack": "applicationtrack.com", "mi5": "applicationtrack.com",
    "mi6": "applicationtrack.com", "gchq": "applicationtrack.com",
}


def _manifest_rows(intent):
    """Return the tool-manifest table rows most relevant to the intent's keywords."""
    try:
        lines = open(MANIFEST, encoding="utf-8").read().splitlines()
    except OSError:
        return []
    words = set(re.findall(r"[a-z]+", intent.lower()))
    # expand a few intent synonyms to manifest vocabulary
    syn = {"apply": {"apply", "fill", "form", "submit", "drive"},
           "source": {"source", "sourcing", "feed", "board", "funnel"},
           "screen": {"screen", "title", "precheck", "jd"},
           "triage": {"blocked", "triage", "retry"},
           "drain": {"queue", "drive", "apply"},
           "log": {"log", "tracker", "row"}}
    for w in list(words):
        words |= syn.get(w, set())
    rows = []
    for ln in lines:
        if ln.startswith("|") and "|" in ln[1:] and "---" not in ln:
            cells = [c.strip() for c in ln.strip("|").split("|")]
            if len(cells) >= 2 and cells[0].lower() not in ("i need to…", "i need to..."):
                hay = ln.lower()
                if any(w in hay for w in words if len(w) > 3):
                    rows.append((cells[0], cells[1]))
    return rows[:12]


def _board_from_intent(intent):
    low = intent.lower()
    for token in BOARD_DIRS:
        if re.search(r"\b" + re.escape(token) + r"\b", low):
            return token
    return None


def _board_quirks(board):
    d = os.path.join(SITES, BOARD_DIRS.get(board, board))
    quirks = os.path.join(d, "quirks.jsonl")
    out = []
    if os.path.isfile(quirks):
        try:
            for line in open(quirks, encoding="utf-8"):
                line = line.strip()
                if line:
                    q = json.loads(line)
                    out.append(f"  • {q.get('symptom','?')} → {q.get('fix','?')}"
                               + (f"  (verified {q.get('verified')})" if q.get("verified") else ""))
        except (OSError, ValueError):
            pass
    if out:
        return "quirks.jsonl:\n" + "\n".join(out[:10])
    notes = os.path.join(d, "NOTES.md")
    if os.path.isfile(notes):
        try:
            head = [ln.rstrip() for ln in open(notes, encoding="utf-8").read().splitlines()
                    if ln.strip()][:18]
            return "NOTES.md (head):\n" + "\n".join("  " + ln for ln in head)
        except OSError:
            pass
    return "(no board notes found)"


def main():
    argv = sys.argv[1:]
    if "--list-boards" in argv:
        print(" ".join(sorted(BOARD_DIRS)))
        return 0
    intent = next((a for a in argv if not a.startswith("--")), "")
    if not intent:
        print("Usage: brief.py \"<intent e.g. apply reed>\" [--health]", file=sys.stderr)
        return 2

    print(f"═══ BRIEF: {intent!r} ═══\n")

    rows = _manifest_rows(intent)
    if rows:
        print("SHIPPED TOOLS for this task (use these — never re-implement):")
        for task, tool in rows:
            print(f"  • {task}  →  {tool}")
        print()

    board = _board_from_intent(intent)
    if board:
        print(f"BOARD {board}:")
        print(_board_quirks(board))
        print()

    st = state_view.compute(with_health="--health" in argv)
    q = st["queue"]
    print("LIVE STATE:")
    print(f"  Applied strict {st['applied_strict']} (today {st['applied_today']}); "
          f"queue {q['depth']} rows by ATS {q['by_ats']}")
    if st["cooldowns_active"]:
        print(f"  cooldowns: {len(st['cooldowns_active'])} active "
              f"(soonest {st['cooldowns_active'][0]['board']} "
              f"{st['cooldowns_active'][0]['hours_left']}h)")
    if st["blockers_open"]:
        print(f"  ⚠️ {len(st['blockers_open'])} open blocker(s)")
    if st["suspect_verdicts"]:
        print(f"  ⚠️ {len(st['suspect_verdicts'])} suspect verdict(s) to re-validate")
    if st["accounts_needed_top"]:
        t = st["accounts_needed_top"][0]
        print(f"  ➤ top account wall: {t['ats']} ({t['blocked']} blocked)")
    if "--health" in argv and st.get("backend_health"):
        h = st["backend_health"]
        print(f"  backend: degraded={h.get('degraded')} "
              f"connected={h.get('browser_connected')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
