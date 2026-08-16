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
import json
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
    # ⛔ RIGHT-TO-WORK OUTRANKS THE BARE `sponsorship` CATCH-ALL (2026-08-16). These rows used
    # to sit BELOW it, so any question mentioning sponsorship matched "No" first — including
    # "Are you legally authorised to work in the UK WITHOUT requiring sponsorship?", whose
    # truthful answer is YES (British citizen, full UK right to work). The bank was answering
    # No to a question about his eligibility: a false statement that reads as a hard fail on
    # the single most common screening gate. The bare row stays as the last-resort catch-all.
    ("legally authorized", "radio", "Yes", "profile:UK RTW"),
    ("authorised to work", "radio", "Yes", "profile"),
    ("authorized to work", "radio", "Yes", "profile"),
    ("right to work", "radio", "Yes", "profile"),
    ("eligible to work", "radio", "Yes", "profile"),
    ("sponsorship", "radio", "No", "profile"),
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
    # ⛔ \b ON BOTH SIDES OF d.o.b (2026-08-16). Unanchored, `d\.?o\.?b` matches the letters
    # d-o-b INSIDE ordinary words — most damagingly "A-dob-e". Every "How many years with Adobe
    # Photoshop?" therefore matched the DATE-OF-BIRTH row and was answered with the DOB answer
    # (in the live bank, a bare number) instead of the years figure. Same class as the `cro`
    # bug below: an abbreviation alternative with no word boundary is a substring landmine.
    ("/\\bage\\b|how old|date of birth|\\bd\\.?o\\.?b\\b/", "text", "Prefer not to say", "profile:edit for your situation"),
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
    # ⛔ NARROWEST FIRST (2026-08-16). These two used to sit BELOW the generic product/design
    # row, which is `\bdesign` with no closing boundary — so it matches "design system(s)" and
    # any "accessibility design" phrasing and won first. "How many years of design systems
    # experience?" was answered 6 instead of 3, and "years of accessibility design" 6 instead
    # of 2: the bank OVERSTATED experience by years on exactly the specialisms a design role
    # screens for. First match wins, so a narrower row is only reachable ABOVE its generic.
    ("/years.*design system/", "number", "3", "profile"),
    ("/years.*(accessibility|wcag)/", "number", "2", "profile"),
    ("/years.*(product|\\bux\\b|\\bui\\b|interaction|\\bdesign)/", "number", "6", "profile"),
    ("/years.*(front.?end|html|css|node|web develop)/", "number", "3", "profile"),
    ("/years.*(docker|ci/cd|devops|linux)/", "number", "3", "profile"),
    ("/years.*(it support|desktop|service desk|technician|help ?desk)/", "number", "2", "profile"),
    # ⛔ \bcro\b (2026-08-16). Unbounded, "cro" matches inside "Mi-cro-soft" and
    # "cro-ss-functional", so "How many years of experience with Microsoft Azure?" was answered
    # with the growth/marketing figure. Bound the abbreviation; spell out the long form too.
    ("/years.*(growth|\\bcro\\b|conversion rate|a/b|marketing)/", "number", "3", "profile"),
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


# ⛔ POLARITY GUARD (2026-08-16 — caught in a SUBMITTED application). The bank is substring
# matched and completely polarity-blind, so an INVERTED phrasing of a known question got the
# known answer, which is then the opposite of the truth. Live example, submitted to Mozilla
# before this existed: "would you be able to fill the position … WITHOUT relocation assistance"
# matched the `relocation assistance -> No` row, stating he could NOT do a Europe role from
# London without relocation support. Probing the rest of the bank found the same trap on the
# most consequential question there is — "are you able to work WITHOUT sponsorship?" -> No.
#
# The discriminator is WHERE the negation sits relative to the match:
#   "…able to work [without] sponsorship"          -> cue directly before the matched token,
#                                                     the answer inverts  -> REFUSE
#   "…[authorised to work] without sponsorship"    -> match is the earlier phrase; the cue
#                                                     qualifies a later word -> answer stands
# So: refuse only when a negation cue immediately precedes the match. Refusing leaves the
# field unanswered, which blocks the submit and asks for a human — the same trade the
# closed-set radio guard already makes, and the right one for a yes/no eligibility claim.
# Up to three short intervening words, so "without REQUIRING sponsorship" and "without ANY NEED
# for sponsorship" are caught as readily as "without sponsorship". This stays safe for the
# other side of the discriminator because the test is applied to the text before the MATCH
# START: in "authorised to work without sponsorship" the match begins at "authorised", so the
# later "without" is never in the searched window at all.
_NEGATION_CUE = re.compile(r"(?:\bwithout\b|\bnot\b|\bno longer\b|\bunable to\b|"
                           r"\bunwilling to\b|\bother than\b|\bexcept\b|\bexcluding\b)"
                           r"(?:\s+[a-z]{1,12}){0,3}[\s,]*$")


def _polarity_inverted(pattern, q):
    """True when a negation cue sits immediately before where `pattern` matched in `q`."""
    p = pattern.strip()
    try:
        if len(p) >= 2 and p.startswith("/") and p.endswith("/"):
            rx = _compiled(p[1:-1])
            m = rx.search(q) if rx else None
        else:
            m = _bounded(p.lower()).search(q)
    except Exception:  # noqa: BLE001 — a guard must never break a lookup
        return False
    if not m:
        return False
    return bool(_NEGATION_CUE.search(q[:m.start()]))


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
            # Only YES/NO claims invert dangerously; a free-text or numeric answer ("London",
            # "6", "Immediately") is not made false by a nearby negation, and refusing those
            # would block forms for no gain.
            if (r["answer"] or "").strip().lower() in ("yes", "no") \
                    and _polarity_inverted(r["pattern"], q):
                print(f"screener: REFUSING {r['pattern']!r} -> {r['answer']!r} for a NEGATED "
                      f"phrasing ({q[:60]!r}) — answering would state the opposite of the "
                      f"truth; leaving it for a human.", file=sys.stderr)
                return None
            return {"answer": r["answer"], "kind": r["kind"],
                    "source": r["source"], "pattern": r["pattern"]}
    return None


def _write(rows):
    """Atomic rewrite of the whole bank (tmp + os.replace). Callers hold the file lock."""
    tmp = CSV + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        for r in rows:
            w.writerow([r["pattern"], r["kind"], r["answer"], r["source"]])
    os.replace(tmp, CSV)


def record(pattern, answer, kind="text", source="learned", update=False, sample=None):
    """Persist a learned answer (idempotent on exact pattern), INSERTED AT ITS CORRECT
    PRIORITY rather than blindly appended. Ensures the file exists (seeds first).

    ⛔ WHY NOT A PLAIN APPEND (2026-08-15). Order in this file IS priority — `lookup` takes
    the FIRST matching pattern, and the module docstring says "put the SPECIFIC before the
    GENERIC". But `record` appended to the end, so a learned SPECIFIC rule could never
    outrank a seeded GENERIC one that already matched. Concretely: teaching
    `right to work status -> British` had no effect at all, because the seeded row
    `right to work -> Yes` sits at line 11 and won every lookup. Greenhouse's
    "Please select your right to work status" (options: British or Irish Citizen / EU
    Settled Status / …) therefore kept coming back UNANSWERED_REQUIRED on every Canonical
    and Graphcore posting — "Yes" is not on that list — while the CSV appeared to contain
    the answer. A learn that silently cannot take effect is worse than no learn.

    Fix: insert the new row immediately BEFORE the first existing row that is strictly more
    GENERIC than it — i.e. whose plain (non-regex) pattern is a substring of the new one.
    That is exactly the overlap that would otherwise shadow it. Everything else keeps its
    order, so no existing precedence changes."""
    if not pattern or answer is None:
        return False
    # ⛔ PROVE THE RULE CAN ACTUALLY FIRE, USING `sample` AS THE ORACLE (2026-08-16).
    # `_matches` treats a bare pattern as a WORD-BOUNDED SUBSTRING and compiles a regex ONLY
    # when it is /slash-wrapped/. So banking `ai notetaker|notetakers to transcribe` stores a
    # literal containing a pipe — a string no question ever contains — and the row silently
    # never fires. That happened the same day, to a consent answer the USER had just supplied:
    # the CSV looked perfectly correct and the answer was inert. Exactly the failure the
    # docstring above names: "a learn that silently cannot take effect is worse than no learn."
    #
    # Do NOT try to infer regex-intent from metacharacters. `location (city)` is a REAL, WORKING
    # row whose parentheses are literal (they are escaped by `_bounded`), and `Preferred Name |
    # What would you like us to call you?` is a REAL Lever label containing a literal pipe — so
    # a metacharacter scan would auto-wrap working rows into broken ones. The only sound test is
    # empirical: if the caller passed the question this rule was learned from, the rule must
    # match it. Slash-wrapping is tried only as a REPAIR when the literal reading fails.
    if sample:
        _p, _s = pattern.strip(), norm(sample)
        if not _matches(_p, _s):
            _wrapped = "/" + _p.strip("/") + "/"
            if _matches(_wrapped, _s):
                print(f"screener: {pattern!r} does not match its own sample as a literal; "
                      f"banking it as {_wrapped!r} (regex) instead.", file=sys.stderr)
                pattern = _wrapped
            else:
                print(f"screener: REFUSED {pattern!r} — it does not match the sample it was "
                      f"learned from ({sample[:60]!r}), so it could never fire.",
                      file=sys.stderr)
                return False
    if not os.path.exists(CSV):
        seed()
    # A.4: dup-check + insert under the lock so two drivers learning the same phrasing
    # concurrently can't both pass the check and double-write the row (TOCTOU).
    with file_lock(CSV):
        rows = _read()
        new = pattern.strip().lower()
        for r in rows:
            if r["pattern"].strip().lower() == new:
                # ⛔ DON'T REFUSE A CORRECTION IN SILENCE (2026-08-16). Returning False for an
                # existing pattern conflates "already correct, nothing to do" with "you asked
                # to change this answer and I ignored you". The second is how a WRONG banked
                # answer becomes permanent: the operator re-teaches the right one, sees a
                # falsy return that reads as a no-op dedup, and the bad answer keeps shipping.
                if (r["answer"] or "") == (answer or ""):
                    return False            # genuinely already known
                if not update:
                    print(f"screener: REFUSED to change {pattern!r} from {r['answer']!r} to "
                          f"{answer!r} — pass update=True to correct a banked answer.",
                          file=sys.stderr)
                    return False
                r["kind"], r["answer"], r["source"] = kind, answer, source
                _write(rows)
                _rows_cached.cache_clear()
                return True
        at = len(rows)
        # ⛔ A REGEX NEW ROW CANNOT BE PLACED BY TEXT (2026-08-16). The scan below asks "does
        # an existing row match the NEW PATTERN's text?", which works when the new pattern is
        # a plain substring but is meaningless when it is a /regex/ — you cannot match one
        # regex against another. So a new regex row was always APPENDED, i.e. below every
        # existing catch-all, i.e. inert. Live consequence: teaching
        # /years.*(software engineering|…)/ -> 3 landed under /years.*(of )?experience/ -> 5,
        # so "How many years of software engineering experience?" kept answering 5 — the row
        # was not merely ignored, it left an OVERSTATED figure in place.
        #
        # Rather than guess at regex generality, let the caller hand over a real question the
        # new row is meant to answer. Then "which existing row would beat me?" is answered by
        # running the actual matcher against an actual question — no inference at all.
        if sample:
            q = norm(sample)
            for i, r in enumerate(rows):
                if _matches(r["pattern"], q):
                    at = i
                    break
            rows.insert(at, {"pattern": pattern, "kind": kind,
                             "answer": answer, "source": source})
            _write(rows)
            _rows_cached.cache_clear()
            return True
        for i, r in enumerate(rows):
            p = r["pattern"].strip().lower()
            # ⛔ A /regex/ ROW SHADOWS TOO (2026-08-16). This used to `continue` past every
            # regex row, on the theory that a regex's breadth "isn't inferable from its text".
            # It is inferable the only way that matters: RUN IT. If the regex matches the new
            # pattern's own text, that row will match every question the new row was meant to
            # catch and, sitting above it, will always win — so the learn is inert on arrival.
            # That is precisely the silent-no-op failure this function's docstring claims to
            # have fixed, still live for the ~15 regex rows in the seed table (the years-of-X
            # block, where a wrong number is an overstated-experience answer).
            if p.startswith("/"):
                # _matches is the SAME predicate lookup() uses, so "would this row shadow the
                # new one?" is answered by the real matcher, not a reimplementation of it.
                if not new.startswith("/") and _matches(p, new):
                    at = i
                    break
                continue
            if new.startswith("/"):
                continue
            if p and p in new and p != new:
                at = i
                break
        rows.insert(at, {"pattern": pattern, "kind": kind, "answer": answer, "source": source})
        _write(rows)
    _rows_cached.cache_clear()   # mtime-keyed, but clear anyway so a same-second
                                 # learn+lookup in one process sees the new row
    return True


# ── M.4: triage coalescer ────────────────────────────────────────────────────
# WHY: SKILL.md documents a MANUAL recipe — grep every `BLOCKED_UNANSWERED_REQUIRED:` across
# drain logs, sort|uniq -c, then eyeball each to decide whether to teach it. That recipe was
# re-derived by hand every session. This makes it a tool: aggregate → dedup → CLASSIFY
# (teachable vs never-teach eligibility gate) → emit ONE worksheet the model fills in one
# turn; `teach-batch` then bulk-learns. This preserves the anti-fabrication rule in CODE: an
# eligibility gate (graduation-year / degree-required / "do you currently hold…") is tagged
# never_teach so it can't be padded into a false Yes.

# Never-teach: hard ELIGIBILITY gates whose truthful answer is fixed by facts, not consent.
# Teaching these as Yes would fabricate eligibility (the documented no-fabrication violation).
_NEVER_TEACH = [
    r"recent graduate", r"\bgraduat", r"20(2[4-9]|3\d)\s*graduate", r"class of 20",
    r"currently (hold|have|possess).*(clearance|sc|dv|security)",
    r"active (sc|dv|security clearance)", r"on day one", r"day-one",
    r"\bdegree\b", r"\bphd\b", r"bachelor", r"master'?s degree",
    r"do you have .* years", r"minimum of \d+ years",
]
# Teachable: consent / logistics / location / notice / demographics / true years-of-X.
_TEACHABLE = [
    r"sponsor", r"right to work", r"authori[sz]ed to work", r"eligible to work",
    r"notice period", r"available", r"start", r"relocat", r"commut", r"\bbased\b",
    r"\blocation\b", r"salary", r"expected", r"pronoun", r"gender", r"ethnic",
    r"disab", r"veteran", r"orientation", r"years of experience", r"how many years",
    r"driving licen", r"willing to",
]


def classify_question(q):
    """-> 'never_teach' (eligibility gate — leave needs_human, don't pad the count),
    'teachable' (consent/location/logistics), or 'unknown' (model decides)."""
    ql = norm(q)
    for pat in _NEVER_TEACH:
        if re.search(pat, ql):
            return "never_teach"
    for pat in _TEACHABLE:
        if re.search(pat, ql):
            return "teachable"
    return "unknown"


def triage(sources):
    """Aggregate distinct unanswered screener questions from drain logs (or plain text),
    with counts + classification + whether the bank ALREADY covers each. `sources` is a list
    of file paths ('-' = stdin). Returns a list of dicts sorted by count desc."""
    import collections
    counts = collections.Counter()
    for src in sources:
        try:
            if src == "-":
                text = sys.stdin.read()
            else:
                with open(src, encoding="utf-8") as _f:
                    text = _f.read()
        except OSError:
            continue
        for m in re.finditer(r"BLOCKED_UNANSWERED_REQUIRED:\s*(.+)", text):
            q = m.group(1).strip().strip('"').strip()
            if q:
                counts[q] += 1
    out = []
    for q, n in counts.most_common():
        hit = lookup(q)
        out.append({"question": q, "count": n, "class": classify_question(q),
                    "already_covered": bool(hit),
                    "current_answer": hit["answer"] if hit else ""})
    return out


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
    if cmd == "triage":
        # screener.py triage <drain.log ...|->  [--json]
        srcs = [a for a in argv[2:] if not a.startswith("--")] or ["-"]
        rows = triage(srcs)
        if "--json" in argv:
            print(json.dumps(rows, ensure_ascii=False, indent=1))
            return 0
        if not rows:
            print("no BLOCKED_UNANSWERED_REQUIRED questions found in the given source(s).")
            return 0
        teachable = [r for r in rows if r["class"] == "teachable" and not r["already_covered"]]
        never = [r for r in rows if r["class"] == "never_teach"]
        unknown = [r for r in rows if r["class"] == "unknown" and not r["already_covered"]]
        covered = [r for r in rows if r["already_covered"]]
        print(f"{len(rows)} distinct unanswered question(s):")
        print(f"\nTEACHABLE ({len(teachable)}) — consent/location/logistics; answer once, "
              f"free forever. Emit a worksheet with:  screener.py triage <logs> --worksheet ws.csv")
        for r in teachable:
            print(f"  [{r['count']:>3}×] {r['question']}")
        if unknown:
            print(f"\nUNKNOWN ({len(unknown)}) — model decides teachable-or-not per profile:")
            for r in unknown:
                print(f"  [{r['count']:>3}×] {r['question']}")
        if never:
            print(f"\n⚠️ NEVER-TEACH ({len(never)}) — hard ELIGIBILITY gates; leave needs_human, "
                  f"do NOT pad the count (no-fabrication rule):")
            for r in never:
                print(f"  [{r['count']:>3}×] {r['question']}")
        if covered:
            print(f"\nALREADY COVERED ({len(covered)}) — the bank answers these; a bail on "
                  f"them is a phrasing/matching miss, not a new question.")
        if "--worksheet" in argv:
            ws = argv[argv.index("--worksheet") + 1]
            with open(ws, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["question", "class", "count", "pattern", "kind", "answer"])
                for r in teachable + unknown:
                    # pre-fill pattern with the question (a substring key) + blank answer to fill
                    w.writerow([r["question"], r["class"], r["count"], "", "text", ""])
            print(f"\nworksheet -> {ws} ({len(teachable)+len(unknown)} rows). Fill `answer` "
                  f"(and optionally a shorter `pattern`/`kind`), then: screener.py teach-batch {ws}")
        return 0
    if cmd == "teach-batch" and len(argv) >= 3:
        # screener.py teach-batch <worksheet.csv> — bulk-learn filled rows. A row with a blank
        # answer is skipped; class=never_teach is ALWAYS skipped (guardrail — even if a human
        # accidentally filled it, teaching an eligibility gate is refused).
        ws = argv[2]
        learned = skipped = 0
        try:
            with open(ws, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    ans = (row.get("answer") or "").strip()
                    cls = (row.get("class") or "").strip()
                    pat = (row.get("pattern") or "").strip() or (row.get("question") or "").strip()
                    if not ans or not pat or cls == "never_teach":
                        skipped += 1
                        continue
                    if record(pat, ans, (row.get("kind") or "text").strip(), "triage-batch"):
                        learned += 1
                    else:
                        skipped += 1
        except OSError as e:
            print(f"FAIL: cannot read worksheet {ws!r}: {e}", file=sys.stderr)
            return 2
        print(f"teach-batch: learned {learned}, skipped {skipped} "
              f"(blank/duplicate/never-teach).")
        return 0
    print("Usage: screener.py ask <question> | learn <pattern> <answer> [kind] [source] "
          "| seed [--force] | list | triage <logs|-> [--worksheet f.csv] [--json] | "
          "teach-batch <worksheet.csv>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(_cli(sys.argv))
