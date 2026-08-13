#!/usr/bin/env python3
"""
known_wall.py — "have we already solved this wall?" lookup. MANDATORY before logging `Blocked`.

This repo carries ~130 `references/*.md` pitfall docs + per-board `sites/*/NOTES.md`, and a
large share of them exist precisely because a wall LOOKED structural and wasn't. An agent that
rediscovers a wall from scratch and logs `Blocked` without checking them throws away the most
expensive knowledge in the repo.

Worked example of the failure this closes (2026-08-13): a run reported "WTTJ /login redirects
to home — zombie session, not logged in" as a verified structural block. The session was in
fact logged in — the redirect away from /login IS the logged-in signal — and
`references/wttj-checklogin-false-negative.md` had said exactly that since 2026-07-14, with
the dashboard/user-menu probe that disproves it.

Usage:
  known_wall.py "wttj login redirects to home"     # symptom lookup
  known_wall.py --ats greenhouse "combobox won't open"
  known_wall.py --list-resolved                    # every doc holding a false-negative/fix

Exit codes:  0 = candidate docs found (READ THEM before concluding blocked)
             1 = nothing known (a genuinely new wall — logging Blocked is defensible)
"""
import argparse
import os
import re
import sys

_here = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_here)

# Phrases that mark a doc as carrying a RESOLUTION (false negative, workaround, fix) rather
# than merely recording a dead end. Matches rank these first — they're the ones that unblock.
_RESOLVED = (
    "false negative", "false-negative", "not a blocker", "is not a stop", "≠ stop",
    "reality check", "## rule", "## fix", "verified fix", "workaround", "disproves",
    "do not treat", "don't treat", "normal, not", "is normal", "instead of concluding",
)
_STOP = {
    "the", "a", "an", "is", "it", "to", "on", "in", "of", "and", "or", "for", "with", "at",
    "this", "that", "was", "are", "be", "been", "not", "no", "but", "from", "by", "as", "i",
    "wont", "cant", "doesnt", "didnt", "my", "we", "you", "its", "so", "then", "when",
}


def _tok(s):
    return [w for w in re.split(r"[^a-z0-9]+", s.lower()) if w and w not in _STOP and len(w) > 1]


def _docs():
    """All searchable knowledge files: references, per-board notes, and SKILL.md itself."""
    out = []
    refs = os.path.join(_ROOT, "references")
    if os.path.isdir(refs):
        out += [os.path.join(refs, f) for f in sorted(os.listdir(refs)) if f.endswith(".md")]
    sites = os.path.join(_ROOT, "sites")
    if os.path.isdir(sites):
        for b in sorted(os.listdir(sites)):
            p = os.path.join(sites, b, "NOTES.md")
            if os.path.isfile(p):
                out.append(p)
    skill = os.path.join(_ROOT, "SKILL.md")
    if os.path.isfile(skill):
        out.append(skill)
    return out


def _read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def _best_excerpt(text, qtok, width=14, cols=150):
    """Return the heading-delimited section richest in query tokens.

    Lines are hard-truncated: SKILL.md carries single ⚠️ bullets thousands of chars long,
    and an untruncated excerpt buries the actual hit under a wall of unrelated prose.
    """
    lines = [ln if len(ln) <= cols else ln[:cols].rstrip() + " …" for ln in text.splitlines()]
    heads = [i for i, ln in enumerate(lines) if ln.startswith("#")] or [0]
    heads.append(len(lines))
    best, best_score = (0, min(width, len(lines))), -1
    for a, b in zip(heads, heads[1:]):
        seg = " ".join(lines[a:b]).lower()
        score = sum(seg.count(t) for t in qtok)
        if score > best_score:
            best_score, best = score, (a, min(b, a + width))
    return "\n".join(lines[best[0]:best[1]]).rstrip()


def search(query, ats=None, limit=5):
    qtok = set(_tok(query) + (_tok(ats) if ats else []))
    if not qtok:
        return []
    # Coverage floor. Without it a single generic token ("board", "form", "login") matches
    # nearly every doc, and a wall of weak hits reads as "this is known" when it isn't —
    # the opposite of the tool's job. Short/precise queries stay matchable on one token.
    min_cov = 1 if len(qtok) <= 2 else max(2, int(round(0.3 * len(qtok))))
    hits = []
    for path in _docs():
        text = _read(path)
        if not text:
            continue
        low = text.lower()
        name = os.path.basename(path).lower()
        # token coverage in body, weighted up for filename and heading hits
        covered = {t for t in qtok if t in low}
        if len(covered) < min_cov:
            continue
        score = len(covered)
        score += 2 * len([t for t in qtok if t in name])
        heads = " ".join(ln for ln in low.splitlines() if ln.startswith("#"))
        score += len([t for t in qtok if t in heads])
        resolved = any(m in low for m in _RESOLVED)
        if resolved:
            score += 3  # a doc with a way THROUGH outranks one that just records a dead end
        hits.append({"path": os.path.relpath(path, _ROOT), "score": score,
                     "resolved": resolved, "excerpt": _best_excerpt(text, qtok)})
    hits.sort(key=lambda h: (-h["score"], h["path"]))
    return hits[:limit]


def list_resolved():
    out = []
    for path in _docs():
        low = _read(path).lower()
        if any(m in low for m in _RESOLVED):
            out.append(os.path.relpath(path, _ROOT))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Check a wall against known pitfalls before logging Blocked.")
    ap.add_argument("symptom", nargs="*", help="what you actually observed")
    ap.add_argument("--ats", default=None, help="board/ATS name to weight the search")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--list-resolved", action="store_true",
                    help="list every doc carrying a false-negative/workaround")
    a = ap.parse_args(argv)

    if a.list_resolved:
        docs = list_resolved()
        print(f"{len(docs)} doc(s) carry a false-negative or workaround:")
        for d in docs:
            print(f"  {d}")
        return 0

    q = " ".join(a.symptom).strip()
    if not q:
        ap.error("give the symptom you observed, e.g. \"login redirects to home\"")

    hits = search(q, ats=a.ats, limit=a.limit)
    if not hits:
        print(f"known_wall: NOTHING KNOWN for {q!r}"
              + (f" (ats={a.ats})" if a.ats else ""))
        print("→ No prior art. A genuinely new wall; logging `Blocked` is defensible.")
        print("→ If you do solve it, WRITE IT UP in references/ so the next run doesn't re-pay this.")
        return 1

    print(f"known_wall: {len(hits)} candidate doc(s) for {q!r}"
          + (f" (ats={a.ats})" if a.ats else ""))
    print("⛔ READ THESE BEFORE CONCLUDING THE WALL IS STRUCTURAL.\n")
    for h in hits:
        flag = "★ HAS A WAY THROUGH" if h["resolved"] else "  (records a dead end)"
        print(f"── {h['path']}  [score {h['score']}] {flag}")
        for ln in h["excerpt"].splitlines():
            print(f"   {ln}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
