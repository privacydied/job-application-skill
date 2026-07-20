#!/usr/bin/env python3
"""check_title.py — deterministic, code-level title-eligibility check against
references/target-roles.md, so agents don't have to hold ~90 title phrases across
12 tiers in working memory while screening dozens of postings per run.

WHY THIS EXISTS: real gap found live (2026-07-13). LinkedIn search results included
postings titled "Founding Designer / Design Engineer" (Jack & Jill) and "Service
Designer" (Lloyds) and "UX Writer" (AJ Bell) — "Design Engineer" is explicitly Tier A
("his literal positioning"), "Service Designer" is Tier B, "UX Writer" is Tier C, all
genuinely on-profile — but none were ever logged (not Applied, not Skipped, not
Blocked — just silently dropped). Root cause: the "cheap title pre-filter" the loop
docs describe is pure prose judgment with no code checking the full tier list, so an
agent skimming many titles fast (especially the ~14-per-search blank-title cards that
need individually opening) defaults to pattern-matching only the ~7 literal
search-query phrases (Tier A's core design titles) instead of all ~90 phrases across
12 tiers. This makes the check a single deterministic function call instead.

Usage:
  python3 check_title.py "<job title>"
    -> JSON: {"eligible": bool, "tier": "A"|"B"|"C"|null, "matched_phrase": "...",
              "seniority_flag": bool}
       eligible=false + seniority_flag=true  -> off-profile, too senior
       eligible=false + seniority_flag=false -> genuinely not in the tier list, skip
       eligible=true  + seniority_flag=true  -> matched a role BUT title also carries
                                                 a seniority word (e.g. "Senior Product
                                                 Designer") -- still off-profile on
                                                 seniority grounds; tier match alone
                                                 does not override the seniority rule.
       eligible=true  + seniority_flag=false -> genuinely on-profile, screen the JD normally
  python3 check_title.py --self-test
    -> dumps every (tier, phrase) pair parsed from target-roles.md, so after editing
       that file you can eyeball that the parse still looks sane.

Exit code is always 0 (advisory, not a hard gate) — read the JSON / act on it.
"""
import json
import os
import re
import sys
from functools import lru_cache

_here = os.path.dirname(os.path.abspath(__file__))
# scripts -> _common -> sites -> root -> references/target-roles.md
# Your real target-roles.md is gitignored; a fresh clone ships only target-roles.example.md.
# Fall back to it so title screening works (with generic tiers) until you create your own.
_REFS = os.path.join(_here, "..", "..", "..", "references")
TARGET_ROLES = os.path.join(_REFS, "target-roles.md")
if not os.path.exists(TARGET_ROLES) and os.path.exists(os.path.join(_REFS, "target-roles.example.md")):
    TARGET_ROLES = os.path.join(_REFS, "target-roles.example.md")

SENIORITY_WORDS = ("senior", "lead", "principal", "staff", "director", "head", "manager",
                    "vp", "vice president", "chief", "founding")

# DISCIPLINE FALSE-COGNATE GUARD (real gap found live 2026-07-15): "Design Engineer"
# is Tier A (Jane's literal positioning), but LinkedIn returns literal
# "Electrical / ICT / Mechanical / CAD / RF / Systems Design Engineer" postings —
# industrial/CAD roles that merely CONTAIN the substring "design engineer" and so
# passed the naive `phrase in title` match with eligible=true, seniority_flag=false.
# Applying to them violates the core "never pad the count with off-profile roles"
# rule and is real-world harm (spamming employers, misrepresenting the applicant).
# Fix is deliberately NARROW: only "design engineer" carrying an industrial modifier
# AND no UX/creative signal is excluded — bare "Design Engineer" (Tier A), IT
# "field service engineer" (Tier C), and "ICT Support" are all untouched. Widen the
# modifier list at the `_DESIGN_ENG_INDUSTRIAL` tuple below (the single source of truth)
# rather than per-orchestrator. (There used to be a SECOND, shorter _DESIGN_ENG_INDUSTRIAL
# defined right here that the fuller one below silently shadowed — a maintainer widening
# THIS list would have had the edit discarded and leaked an off-profile industrial title.)
# Unambiguous UX/creative signals — if present alongside "design engineer", it's a
# genuine hybrid (keep on-profile). These are the ONLY tokens that rescue an
# industrial modifier; ambiguous tokens (frontend/web/digital/brand) do NOT, because
# e.g. "Frontend ASIC Design Engineer" is an ASIC/FPGA hardware role, not frontend-web.
_DESIGN_ENG_UX_STRONG = (
    "ux", "ui", "product", "creative", "technologist", "prototyp", "interaction",
    "graphic",
)
# Industrial modifiers that condemn a "design engineer" title to off-profile (CAD/MEP/
# hardware). Word-boundary matched. Bare "Design Engineer" (no modifier) stays Tier A.
_DESIGN_ENG_INDUSTRIAL = (
    "electrical", "electronic", "electronics", "mechanical", "hardware", "civil",
    "structural", "ict", "embedded", "cad", "rf", "hvac", "chemical", "aerospace",
    "automotive", "mechatronic", "pcb", "firmware", "optical", "thermal", "acoustic",
    "instrumentation", "telecoms", "telecommunication", "manufacturing", "process",
    "controls", "systems", "hydraulic", "piping", "geotechnical", "asic", "fpga",
    "building services", "renewable", "heat pump", "mep", "structural", "civil",
    "project design", "project",
)


def _industrial_design_engineer(title_l):
    """True iff the title is an off-profile industrial 'design engineer' compound
    (electrical/ICT/mechanical/CAD/building-services/ASIC/...). Bare 'Design
    Engineer' returns False (stays Tier A). A genuine UX/creative signal (ux/ui/
    product/creative/graphic/...) keeps it on-profile; ambiguous tokens (frontend/
    web/digital/brand) do NOT rescue an industrial modifier (2026-07-18 fix:
    'Frontend ASIC Design Engineer' is hardware, and 'ui' substring matched inside
    'building')."""
    if "design engineer" not in title_l:
        return False
    _ux_re = re.compile(r"\b(" + "|".join(re.escape(s) for s in _DESIGN_ENG_UX_STRONG) + r")\b")
    if _ux_re.search(title_l):
        return False
    return any(re.search(r"\b" + re.escape(w) + r"\b", title_l)
               for w in _DESIGN_ENG_INDUSTRIAL)

_TIER_RE = re.compile(r"\(([ABC](?:/[ABC])*)\b")
_SECTION_TIER_RE = re.compile(r"\(Tier ([ABC])")


_NUMBERED_SECTION_RE = re.compile(r"^## \d+\.")

# Splitting synonym lists on "/" can over-split a compound like "UX/UI Designer" or
# "CRO ... Specialist / Analyst" into a dangerously generic bare fragment ("ux",
# "analyst", "manager", "engineer"...) that would false-positive-match all sorts of
# unrelated, often senior, titles. A minimum-2-word phrase filter (below) catches
# most of these; this denylist catches the handful of 2-word survivors/near-misses
# worth naming explicitly if the file ever grows a new one like them.
_DENYLIST = {"digital analyst", "web analyst"}


def parse_target_roles(path=TARGET_ROLES):
    """Memoized wrapper: parses target-roles.md at most once per (path, mtime).
    check_title() runs once PER candidate (precheck screens whole feeds — 370+ in a
    real CSJ run) and per posting in jd.py; without this, that markdown file was
    re-opened and fully re-regexed on every call. Keyed on mtime so an edit to the
    file still re-parses. Returns an immutable tuple (shared cached result — callers
    iterate, never mutate)."""
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = None
    return _parse_target_roles_cached(path, mtime)


@lru_cache(maxsize=8)
def _parse_target_roles_cached(path, mtime):
    """Returns a tuple of (phrase_lowercase, tier) pairs — one per synonym split on
    " / " — extracted from every `- ` bullet line under every numbered `## N. ...`
    role heading (the "## Search strategy notes" tail section is prose, not a role
    list, and is deliberately excluded). A bullet with no explicit "(A/B/C ...)" of
    its own inherits its section heading's tier (e.g. "## 1. ... (Tier A)"), which is
    how a line like "Interaction Designer (his exact NHS title)" — no tier marker at
    all — still resolves to Tier A from its section.

    Single-word phrases are dropped (word-count >= 2 required) — naive splitting on
    every "/" in a line (needed for genuine synonym lists like "Product Designer /
    UX Designer") also fragments compound abbreviations ("UX/UI Designer" ->
    "UX"+"UI Designer") and multi-word terms ("... Specialist / Analyst" ->
    "Specialist"+"Analyst"), and every single-word survivor found on a real title
    audit (2026-07-13) was a generic job-family noun ("manager", "analyst", "ux",
    "engineer", "marketing", "web") that would false-positive-match all sorts of
    unrelated — often senior — titles. No genuine target-roles.md entry is a single
    word, so this costs nothing real."""
    entries = []
    section_tier = None
    in_role_section = False
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        return ()
    for line in lines:
        line = line.rstrip("\n")
        if line.startswith("## "):
            in_role_section = bool(_NUMBERED_SECTION_RE.match(line))
            m = _SECTION_TIER_RE.search(line)
            section_tier = m.group(1) if m else None
            continue
        if not in_role_section or not line.startswith("- "):
            continue
        body = line[2:]
        m = _TIER_RE.search(body)
        tier = m.group(1).split("/")[0] if m else section_tier
        phrase_part = body[:m.start()] if m else body
        # Strip any OTHER parenthetical commentary on the line (e.g. "(his exact NHS
        # title)", "(any of the above AT music companies)") that isn't the tier marker.
        phrase_part = re.sub(r"\([^)]*\)", "", phrase_part)
        for phrase in phrase_part.split("/"):
            phrase = phrase.strip(" -–:").lower()
            if phrase and len(phrase.split()) >= 2 and phrase not in _DENYLIST:
                entries.append((phrase, tier))
    return tuple(entries)


def check_title(title):
    title_l = (title or "").lower()
    seniority_flag = any(re.search(r"\b" + re.escape(w) + r"\b", title_l) for w in SENIORITY_WORDS)
    discipline_flag = _industrial_design_engineer(title_l)
    best = None  # (tier, phrase) -- prefer the highest tier (A > B > C) on multiple matches
    for phrase, tier in parse_target_roles():
        if phrase and phrase in title_l:
            if best is None or (tier or "Z") < (best[0] or "Z"):
                best = (tier, phrase)
    # A tier phrase match is overridden when the title is an off-profile industrial
    # 'design engineer' (electrical/ICT/mechanical/CAD/...) — see _DESIGN_ENG_INDUSTRIAL.
    return {
        "eligible": best is not None and not discipline_flag,
        "tier": best[0] if best else None,
        "matched_phrase": best[1] if best else None,
        "seniority_flag": seniority_flag,
        "discipline_flag": discipline_flag,
    }


def _cli():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    if sys.argv[1] == "--self-test":
        for phrase, tier in parse_target_roles():
            print(f"{tier or '?'}\t{phrase}")
        return 0
    title = " ".join(sys.argv[1:])
    print(json.dumps(check_title(title)))
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
