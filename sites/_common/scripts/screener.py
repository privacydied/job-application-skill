#!/usr/bin/env python3
"""
screener.py — a SHARED, persistent, learnable answer bank for application screener
questions (Tier-2 speed lever: keep the model out of the loop for questions we've
already answered once).

WHY. Every ATS asks the same handful of gating questions in slightly different words:
right-to-work, sponsorship, notice, relocation, years-of-X, demographics. apply_ea.py
had a hardcoded LinkedIn-only KNOWN map; atsform had nothing. So the model re-derived
the same answers per posting, and a new phrasing meant a NEEDS_HUMAN bail. This module
makes the answers DATA:
  * screener-answers.csv (skill root) — ordered rows: pattern,kind,answer,source
  * lookup(question) — first matching pattern wins (substring, or /regex/ if wrapped)
  * record(...) — a driver persists a newly-learned answer so it's free forever after

Consumed by apply_ea.py (and any ATS driver): consult lookup() before bailing on an
"unknown" screener; only genuinely-unknown questions become a NEEDS_ANSWER batch for
the model, which then screener.record()s its answer.

pattern: matched against the lowercased, whitespace-collapsed question. A plain string
is a substring test; wrap in /…/ for a regex. kind: text|radio|select|number|boolean
(a hint to the filler for which widget primitive to use). Order = priority: put the
SPECIFIC before the GENERIC ('require sponsorship' before bare 'sponsorship').
"""
import csv
import os
import re
import sys
from functools import lru_cache

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fsutil import file_lock  # noqa: E402  (TOCTOU-safe learn, Tier A.4)

_here = os.path.dirname(os.path.abspath(__file__))
CSV = os.path.join(_here, "..", "..", "..", "screener-answers.csv")
HEADER = ["pattern", "kind", "answer", "source"]

# Seed derived from references/applicant-profile.md + apply_ea's old KNOWN map. This is
# WRITTEN to screener-answers.csv on first use (seed()); edit the CSV, not this, once it
# exists. Specific-before-generic ordering is load-bearing (first match wins).
_SEED = [
    # right to work / sponsorship (UK)
    ("do you require sponsorship", "radio", "No", "profile:edit for your right-to-work"),
    ("require visa sponsorship", "radio", "No", "profile"),
    ("require sponsorship", "radio", "No", "profile"),
    ("need sponsorship", "radio", "No", "profile"),
    ("visa sponsorship", "radio", "No", "profile"),
    ("sponsorship", "radio", "No", "profile"),
    ("legally authorized", "radio", "Yes", "profile:UK RTW"),
    ("authorised to work", "radio", "Yes", "profile"),
    ("authorized to work", "radio", "Yes", "profile"),
    ("right to work", "radio", "Yes", "profile"),
    ("eligible to work", "radio", "Yes", "profile"),
    # relocation / location
    ("willing to relocate", "radio", "No", "profile:edit for your location rules"),
    ("open to relocation", "radio", "No", "profile"),
    ("current location", "select", "London, United Kingdom", "profile"),
    ("where are you based", "text", "London, United Kingdom", "profile"),
    ("city", "select", "London", "profile"),
    ("location", "select", "London", "profile"),
    # availability / notice
    ("notice period", "select", "Immediately", "profile:available immediately"),
    ("available to start", "select", "Immediately", "profile"),
    ("when can you start", "text", "Immediately", "profile"),
    ("earliest start", "text", "Immediately", "profile"),
    # demographics (two disclose exceptions per profile; rest default prefer-not)
    ("pronoun", "select", "Prefer not to say", "profile:edit for your situation"),
    ("/age|how old|date of birth|d\\.?o\\.?b/", "text", "Prefer not to say", "profile:edit for your situation"),
    ("gender", "select", "Prefer not to say", "profile:edit for your situation"),
    ("/ethnic|ethnicity/", "select", "Prefer not to say", "profile:edit for your situation"),
    ("disability", "select", "No", "profile"),
    ("veteran", "select", "No", "profile"),
    ("sexual orientation", "select", "Prefer not to say", "profile:edit for your situation"),
    ("national identity", "select", "Prefer not to say", "profile"),
    # marketing opt-out
    ("/email alert|similar jobs|receive.*(job|relevant)/", "radio", "No", "profile:opt out"),
    # years of experience (profile years-of-X table; generic falls to ~5). These are
    # REGEX (/…/) so "years ... figma" matches across intervening words; specific rows
    # MUST precede the generic "years of experience" catch-all (first match wins).
    ("/years.*figma/", "number", "6", "profile"),
    ("/years.*(research|usability|user research)/", "number", "5", "profile"),
    ("/years.*(product|ux|ui|interaction|\\bdesign)/", "number", "6", "profile"),
    ("/years.*(accessibility|wcag)/", "number", "2", "profile"),
    ("/years.*design system/", "number", "3", "profile"),
    ("/years.*(front.?end|html|css|node|web develop)/", "number", "3", "profile"),
    ("/years.*(docker|ci/cd|devops|linux)/", "number", "3", "profile"),
    ("/years.*(it support|desktop|service desk|technician|help ?desk)/", "number", "2", "profile"),
    ("/years.*(growth|cro|a/b|marketing)/", "number", "3", "profile"),
    ("/years.*(of )?experience/", "number", "5", "profile:generic default"),
    ("how many years", "number", "5", "profile:generic default"),
    # driving (hard screen elsewhere, but answer truthfully if asked)
    ("/full.*driving licen|driving licen|do you drive/", "radio", "No", "profile:provisional only"),
    # clearance
    ("security clearance", "radio", "No", "profile:edit for your clearance status"),
]


def norm(q):
    return re.sub(r"\s+", " ", (q or "").strip().lower())


def _read():
    rows = []
    try:
        with open(CSV, newline="", encoding="utf-8") as f:
            for row in csv.reader(f):
                if len(row) < 3 or row[0].strip().lower() == "pattern":
                    continue
                rows.append({"pattern": row[0], "kind": row[1] if len(row) > 1 else "text",
                             "answer": row[2] if len(row) > 2 else "",
                             "source": row[3] if len(row) > 3 else ""})
    except FileNotFoundError:
        pass
    return rows


def seed(force=False):
    """Write the seed rows to screener-answers.csv if it doesn't exist (or force)."""
    if os.path.exists(CSV) and not force:
        return False
    with open(CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        for pat, kind, ans, src in _SEED:
            w.writerow([pat, kind, ans, src])
    return True


def _rows():
    """G.2: memoized on the CSV's mtime — `lookup()` runs once PER screener question and
    apply_ea consults the bank in-process per question, so re-opening + re-parsing the file
    every call was wasteful. `record()` appends (changing mtime) → the next call re-reads."""
    try:
        mtime = os.path.getmtime(CSV)
    except OSError:
        mtime = None
    return _rows_cached(mtime)


@lru_cache(maxsize=4)
def _rows_cached(_mtime):
    rows = _read()
    return rows if rows else [{"pattern": p, "kind": k, "answer": a, "source": s}
                              for p, k, a, s in _SEED]


@lru_cache(maxsize=256)
def _compiled(pat):
    """G.2: compile each `/regex/` pattern once (was recompiled every _matches call)."""
    try:
        return re.compile(pat, re.I)
    except re.error:
        return None


@lru_cache(maxsize=256)
def _bounded(pl):
    """LEADING-word-boundary matcher, compiled once. The pattern must START at a word
    boundary — so a short token can't embed as the SUFFIX of a larger word ("city" ⊄
    "ethni-city", "location" ⊄ "re-location", "gender" ⊄ "trans-gender", the false-cognate
    class) — but a trailing suffix is allowed, so a singular pattern still matches its plural
    ("pronoun" → "pronouns"). All observed false cognates are pattern-as-word-suffix, so a
    leading boundary alone kills them without breaking stem/plural matching."""
    return re.compile(r"(?<![a-z0-9])" + re.escape(pl))


def _matches(pattern, q):
    p = pattern.strip()
    if len(p) >= 2 and p.startswith("/") and p.endswith("/"):
        rx = _compiled(p[1:-1])
        return bool(rx.search(q)) if rx else False
    # Word-boundary substring, NOT bare `p in q`: a short plain pattern like "city"/"location"
    # must not match "ethni-city" / "re-location" (false-cognate class — a demographic
    # ethnicity question was being answered "London"). `q` is already lowercased by norm().
    return bool(_bounded(p.lower()).search(q))


def lookup(question):
    """First row whose pattern matches the normalized question, or None. Returns a dict
    {answer, kind, source, pattern}. Order in the CSV is priority (specific first)."""
    q = norm(question)
    if not q:
        return None
    for r in _rows():
        if _matches(r["pattern"], q):
            return {"answer": r["answer"], "kind": r["kind"],
                    "source": r["source"], "pattern": r["pattern"]}
    return None


def record(pattern, answer, kind="text", source="learned"):
    """Append a learned answer (idempotent on exact pattern). Ensures the file exists
    (seeds first) so a driver can persist an answer the model just gave."""
    if not pattern or answer is None:
        return False
    if not os.path.exists(CSV):
        seed()
    # A.4: dup-check + append under the lock so two drivers learning the same phrasing
    # concurrently can't both pass the check and double-write the row (TOCTOU).
    with file_lock(CSV):
        for r in _read():
            if r["pattern"].strip().lower() == pattern.strip().lower():
                return False  # already known — don't duplicate
        with open(CSV, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([pattern, kind, answer, source])
    return True


def _cli(argv):
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "ask" and len(argv) >= 3:
        hit = lookup(" ".join(argv[2:]))
        if hit:
            print(f"{hit['answer']}\t[{hit['kind']}] (pattern={hit['pattern']!r}, {hit['source']})")
            return 0
        print("NEEDS_ANSWER", file=sys.stderr)
        return 1
    if cmd == "learn" and len(argv) >= 4:
        kind = argv[4] if len(argv) > 4 else "text"
        source = argv[5] if len(argv) > 5 else "learned"
        print("recorded" if record(argv[2], argv[3], kind, source) else "already-known")
        return 0
    if cmd == "seed":
        print("seeded" if seed(force="--force" in argv) else "already-exists")
        return 0
    if cmd == "list":
        for r in _rows():
            print(f"{r['pattern']}\t{r['kind']}\t{r['answer']}\t{r['source']}")
        return 0
    print("Usage: screener.py ask <question> | learn <pattern> <answer> [kind] [source] "
          "| seed [--force] | list", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(_cli(sys.argv))
