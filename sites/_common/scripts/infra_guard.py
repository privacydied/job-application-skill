#!/usr/bin/env python3
"""infra_guard.py — the ONE home for the "no divergent / duplicate infra" scans.

Shared by the regression tests (tests/test_core.py::TestNoDivergentFormWidgets) AND the loop
preflight (loop-preflight.py::_divergent_infra_guard), so the no-divergent-duplicate rule is
enforced BOTH at build time and at the top of EVERY loop firing — including the concurrent
Hermes loop, which never runs the test suite. This mirrors loop-preflight._scrub_pii_guard: a
convention prose can't hold, enforced in code, surfaced where every firing (both runtimes) sees
it.

Each scanner returns a list of "relpath: reason" offender strings ([] = clean). Add a new
scanner HERE (never inline in a caller) whenever another shared engine gets a single home — so
there is exactly one auditable definition of what "duplicate infra" means, read from one place
by every enforcement point. (Putting the scan in two places would itself be the drift this file
exists to stop.)
"""
import os
import re

# React-select PICK engine signature — a combobox INPUT selector AND an option-MENU iteration in
# the SAME file. That pair = a re-implementation of atsform.combobox_pick. A bare native
# value-setter (`getOwnPropertyDescriptor(...,'value').set`) is deliberately NOT part of this: it
# is a legitimate, ubiquitous idiom (OTP/login/search/CAPTCHA-token/salary fields in ~15 files)
# with nothing to do with dropdown binding — banning it would flag a dozen innocent files.
_COMBO_INPUT = re.compile(r"role=combobox|select__input|aria-autocomplete=list")
_OPTION_PICK = re.compile(r"select__option|\[role=option\]|class\*=option")
_WIDGET_HOME_REL = os.path.join("sites", "_common", "scripts")


def _root():
    d = os.path.dirname(os.path.abspath(__file__))
    while True:
        if os.path.isfile(os.path.join(d, "SKILL.md")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        d = parent


def _iter_py(root):
    for dirpath, _dirs, files in os.walk(root):
        if "__pycache__" in dirpath or f"{os.sep}.git" in dirpath or f"{os.sep}tests" in dirpath:
            continue
        for fn in files:
            if fn.endswith(".py"):
                yield os.path.join(dirpath, fn)


def scan_form_widgets(root=None):
    """Files OUTSIDE sites/_common/scripts/ that re-implement the react-select pick engine
    (combobox input + option-menu iteration) instead of delegating to atsform.combobox_pick."""
    root = root or _root()
    home = os.path.abspath(os.path.join(root, _WIDGET_HOME_REL))
    offenders = []
    for p in _iter_py(root):
        if os.path.abspath(p).startswith(home):
            continue  # the legitimate home of the shared widget engine
        try:
            with open(p, encoding="utf-8", errors="replace") as fh:
                txt = fh.read()
        except OSError:
            continue
        if _COMBO_INPUT.search(txt) and _OPTION_PICK.search(txt):
            offenders.append(f"{os.path.relpath(p, root)}: react-select pick engine "
                             "re-implemented outside sites/_common/scripts/ — delegate to "
                             "atsform.combobox_pick instead of forking it")
    return offenders


# Regex-SPELLINGS of the anti-AI oath. Deliberately the regex forms (`ai[- ]?generated`,
# `\bno ai\b`), not the prose, so a comment that merely discusses the oath is not an offender —
# only a file that re-spells the PATTERN is.
_OATH_RESPELL = re.compile(r"ai\[-\s?\]\?generated|\\bno ai\\b|only my own words")


def scan_anti_ai_oath(root=None):
    """Files OUTSIDE sites/_common/scripts/ that re-spell the anti-AI oath pattern instead of
    calling atsform.is_anti_ai_oath.

    WHY (2026-08-16): `scripts/gen_gh_config.py` kept its own copy, and it had drifted NARROWER
    than the filler's — no `without the use of ai`, no artificial-intelligence/prohibited clause.
    That produced the worst possible split: the GATE cleared a posting as fully answerable while
    the FILLER would have refused the very same field. Twilio's "Candidate AI Responsible Use
    Policy … reflect my own work and experience" slipped past BOTH copies, and three reqs were
    driven that the applicant must sign himself. atsform's own docstring claimed the two "can
    never drift apart"; that only ever held inside atsform. A prose rule did not stop the fork —
    the same lesson as the react-select scan above — so this makes the fork turn the build red."""
    root = root or _root()
    home = os.path.abspath(os.path.join(root, _WIDGET_HOME_REL))
    offenders = []
    for p in _iter_py(root):
        if os.path.abspath(p).startswith(home):
            continue  # atsform.py is the one legitimate home
        try:
            with open(p, encoding="utf-8", errors="replace") as fh:
                txt = fh.read()
        except OSError:
            continue
        if _OATH_RESPELL.search(txt):
            offenders.append(f"{os.path.relpath(p, root)}: anti-AI oath regex re-spelled "
                             "outside sites/_common/scripts/ — call atsform.is_anti_ai_oath "
                             "instead of keeping a second (inevitably narrower) copy")
    return offenders


def scan_all(root=None):
    """Every divergent-infra scanner, keyed by concern. Extend as new shared engines get a home
    (e.g. tracker dedup → precheck.canon_ids, title screen → check_title)."""
    return {"form_widgets": scan_form_widgets(root),
            "anti_ai_oath": scan_anti_ai_oath(root)}


def all_offenders(root=None):
    out = []
    for group in scan_all(root).values():
        out.extend(group)
    return out


if __name__ == "__main__":
    import sys
    offenders = all_offenders()
    for o in offenders:
        print(o)
    print(f"{len(offenders)} offender(s)")
    sys.exit(1 if offenders else 0)
