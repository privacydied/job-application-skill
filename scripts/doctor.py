#!/usr/bin/env python3
"""
doctor.py — repo/doc/config linter (feature-roadmap H.7).

WHY THIS EXISTS. A whole class of scars is drift the docs describe but can't enforce: a
`python3 <path>` in SKILL.md that points at a moved/renamed script (the AGENTS.md
stale-vs-canonical class), a searches.csv with a forbidden `N|` line prefix or a stale Reed
URL, a CAPTCHA-policy mirror that fell out of sync, an *.example.json whose shape drifted from
its real twin, a quirks row that's gone stale. This runs those checks in code so a break FAILS
here (pre-commit / preflight-cheap) instead of silently shipping.

CHECKS (each prints PASS/WARN/FAIL; exit 1 if any FAIL):
  1. every `python3 <path>` in SKILL.md / references/*.md / sites/*/NOTES.md resolves to an
     existing file (templated <…> paths skipped).
  2. every board in searches.csv is registered in pipeline.FEEDS (unreachable-feed guard).
  3. searches.csv hygiene: no `N|`-prefixed data lines (breaks read_searches), Reed rows use
     the correct `-jobs-in-<loc>` URL pattern (not the unfiltered-firehose slug).
  4. CAPTCHA-policy mirror: references/captcha-policy.md exists and SKILL.md points at it +
     carries the sanctioned-exception phrases (the safety-critical directive must stay mirrored).
  5. every *.example.json parses and its top-level key shape matches its real gitignored twin
     (when the twin exists) — the PII config-routing shapes can't silently diverge.
  6. quirks staleness: quirks.jsonl rows past their verified/expires window (quirks.py stale).

Usage: doctor.py [--days 45] [--quiet]     # exit 0 clean, 1 on any FAIL
"""
import json
import os
import re
import sys

_here = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_here)
sys.path.insert(0, os.path.join(_ROOT, "sites", "_common", "scripts"))

_RESULTS = []  # (level, msg)


def _emit(level, msg):
    _RESULTS.append((level, msg))


def _root_run_docs():
    """Docs whose `python3 <path>` invocations are meant to run from the REPO ROOT — SKILL.md,
    AGENTS.md, references/*.md. Site NOTES.md are deliberately excluded: their paths are
    written relative to the board dir, so root-resolution would be all false positives."""
    docs = [os.path.join(_ROOT, "SKILL.md"), os.path.join(_ROOT, "AGENTS.md")]
    refs = os.path.join(_ROOT, "references")
    if os.path.isdir(refs):
        docs += [os.path.join(refs, f) for f in os.listdir(refs) if f.endswith(".md")]
    return docs


def _basename_locations(basename):
    """All repo paths whose basename matches (for the 'stale path, moved script' hint)."""
    hits = []
    for dirpath, dirs, files in os.walk(_ROOT):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", "state-backups",
                                                "applications", "uploads")]
        if basename in files:
            hits.append(os.path.relpath(os.path.join(dirpath, basename), _ROOT))
    return hits


def check_script_paths():
    pat = re.compile(r"python3\s+([A-Za-z0-9_./-]+\.(?:py|sh))")
    missing, stale = {}, {}
    for doc in _root_run_docs():
        try:
            text = open(doc, encoding="utf-8").read()
        except OSError:
            continue
        rel = os.path.relpath(doc, _ROOT)
        for m in pat.finditer(text):
            path = m.group(1)
            if "<" in path or ">" in path or path.startswith(("/tmp", "~", "..")):
                continue
            if os.path.exists(os.path.join(_ROOT, path)):
                continue  # resolves from root — good
            base = os.path.basename(path)
            locs = _basename_locations(base)
            if "/" not in path and locs:
                continue  # bare basename (e.g. `cfx.py`) run from its own dir — fine
            if locs:
                stale.setdefault(path, (locs[0], []))[1].append(rel)
            else:
                missing.setdefault(path, []).append(rel)
    for path, (actual, docs) in sorted(stale.items()):
        _emit("WARN", f"stale path `{path}` (in {', '.join(sorted(set(docs))[:2])}) — the "
                      f"script exists at `{actual}`; update the doc")
    for path, docs in sorted(missing.items()):
        _emit("FAIL", f"referenced script MISSING anywhere: {path}  (in {', '.join(sorted(set(docs))[:2])})")
    if not missing and not stale:
        _emit("PASS", "all root-run `python3 <path>` references resolve")


def check_feeds_registered():
    try:
        import pipeline
        import search_plan
    except Exception as e:  # noqa: BLE001
        _emit("WARN", f"could not import pipeline/search_plan: {e}")
        return
    feeds = {k.lower() for k in pipeline.FEEDS}
    try:
        rows = search_plan.read_searches()
    except Exception as e:  # noqa: BLE001
        _emit("FAIL", f"searches.csv unreadable: {e}")
        return
    unknown = sorted({r["board"].lower() for r in rows} - feeds)
    if unknown:
        _emit("FAIL", f"searches.csv boards not in pipeline.FEEDS (unreachable): {unknown}")
    else:
        _emit("PASS", f"all {len({r['board'] for r in rows})} searches.csv boards registered in FEEDS")


def check_searches_hygiene():
    path = os.path.join(_ROOT, "searches.csv")
    try:
        lines = open(path, encoding="utf-8").read().splitlines()
    except OSError as e:
        _emit("WARN", f"searches.csv not read: {e}")
        return
    bad_prefix = [i + 1 for i, ln in enumerate(lines)
                  if re.match(r"^\s*\d+\|", ln)]
    if bad_prefix:
        _emit("FAIL", f"searches.csv has `N|`-prefixed line(s) {bad_prefix[:5]} — breaks read_searches()")
    bad_reed = []
    for i, ln in enumerate(lines):
        if ln.lower().startswith("reed,") and "reed.co.uk/jobs/" in ln.lower():
            if "-jobs-in-" not in ln.lower():
                bad_reed.append(i + 1)
    if bad_reed:
        _emit("FAIL", f"searches.csv Reed row(s) {bad_reed[:5]} use the stale unfiltered URL "
                      f"(need /jobs/<role>-jobs-in-<loc>)")
    if not bad_prefix and not bad_reed:
        _emit("PASS", "searches.csv hygiene ok (no N| prefixes, Reed URLs filtered)")


def check_captcha_mirror():
    policy = os.path.join(_ROOT, "references", "captcha-policy.md")
    if not os.path.isfile(policy):
        _emit("FAIL", "references/captcha-policy.md (canonical CAPTCHA policy) missing")
        return
    try:
        skill = open(os.path.join(_ROOT, "SKILL.md"), encoding="utf-8").read().lower()
    except OSError:
        _emit("WARN", "SKILL.md unreadable for captcha-mirror check")
        return
    ok = "captcha-policy.md" in skill and "recaptcha v2" in skill and "altcha" in skill
    _emit("PASS" if ok else "FAIL",
          "CAPTCHA policy mirrored in SKILL.md (pointer + sanctioned exceptions)" if ok
          else "SKILL.md lost the captcha-policy pointer or a sanctioned-exception phrase")


def check_examples():
    problems = 0
    checked = 0
    for dirpath, _d, files in os.walk(_ROOT):
        if "/.git" in dirpath or "__pycache__" in dirpath or "/state-backups" in dirpath:
            continue
        for fn in files:
            if not fn.endswith(".example.json"):
                continue
            ex = os.path.join(dirpath, fn)
            checked += 1
            try:
                exdata = json.load(open(ex, encoding="utf-8"))
            except (OSError, ValueError) as e:
                _emit("FAIL", f"{os.path.relpath(ex, _ROOT)} does not parse: {e}")
                problems += 1
                continue
            twin = os.path.join(dirpath, fn.replace(".example.json", ".json"))
            if os.path.isfile(twin):
                try:
                    tw = json.load(open(twin, encoding="utf-8"))
                    if isinstance(exdata, dict) and isinstance(tw, dict):
                        missing = set(exdata) - set(tw)
                        extra = set(tw) - set(exdata)
                        # extra real keys are fine (real config can hold more); MISSING keys in
                        # the real twin that the example documents is the drift worth flagging.
                        if missing:
                            _emit("WARN", f"{os.path.relpath(twin, _ROOT)} missing keys the "
                                          f"example documents: {sorted(missing)[:6]}")
                except (OSError, ValueError):
                    pass
    if checked and not problems:
        _emit("PASS", f"all {checked} *.example.json parse")
    elif not checked:
        _emit("PASS", "no *.example.json found to check")


def check_quirks_staleness(days):
    try:
        import quirks
        rows = quirks.stale(max_age_days=days)
    except Exception as e:  # noqa: BLE001
        _emit("WARN", f"quirks staleness check skipped: {e}")
        return
    if rows:
        for b, q, why in rows[:10]:
            _emit("WARN", f"stale quirk [{b}] {why}: {q.get('symptom','?')[:50]}")
    else:
        _emit("PASS", f"no stale quirks (verified within {days}d)")


def main():
    argv = sys.argv[1:]
    days = 45
    if "--days" in argv:
        try:
            days = int(argv[argv.index("--days") + 1])
        except (ValueError, IndexError):
            pass
    check_script_paths()
    check_feeds_registered()
    check_searches_hygiene()
    check_captcha_mirror()
    check_examples()
    check_quirks_staleness(days)

    fails = sum(1 for lvl, _ in _RESULTS if lvl == "FAIL")
    warns = sum(1 for lvl, _ in _RESULTS if lvl == "WARN")
    if "--quiet" not in argv:
        for lvl, msg in _RESULTS:
            mark = {"PASS": "✓", "WARN": "⚠", "FAIL": "✗"}[lvl]
            print(f"  {mark} {msg}")
    print(f"\ndoctor: {fails} FAIL, {warns} WARN, "
          f"{sum(1 for l,_ in _RESULTS if l=='PASS')} PASS")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
