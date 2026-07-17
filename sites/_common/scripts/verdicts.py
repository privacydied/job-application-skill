#!/usr/bin/env python3
"""
verdicts.py — health-fingerprinted terminal verdicts (feature-roadmap H.1).

WHY THIS EXISTS. SKILL.md's CONTAMINATION META-RULE is a whole paragraph of prose asking a
future agent to REMEMBER that a degraded camofox backend (blank renders, title='',
innerText.length=0, eval hangs) mints FALSE terminal verdicts — "exhausted", "external
route", "wedge", "NO APPLY BUTTON" — that have reversed on a healthy backend and cost whole
sessions (2026-07-16: +35 applications recovered after re-verification). Prose can't enforce
itself. This turns it into an invariant:

  * stamp(kind, target, reason, …) records EVERY terminal negative together with a
    cfx.health_fingerprint() taken at verdict time, into verdicts.jsonl.
  * If the fingerprint says the backend was DEGRADED (or blank-rendering when the verdict
    implies a real page was loaded), the verdict is written suspect=true AND enqueued to
    revalidate.jsonl.
  * After the backend recovers, `pending()` lists the suspects to re-test; a driver re-runs
    each and calls resolve(id, outcome) — confirming a genuine block or reversing a false one.

So the driver stamps at the moment of the negative; the quarantine + re-test is automatic.
The META-RULE paragraph can then shrink to "stamp terminal negatives via verdicts.py".

Files (skill root, gitignored run-state):
  verdicts.jsonl    append-only audit log of every terminal negative + its fingerprint
  revalidate.jsonl  the suspects queue: {id, kind, target, reason, url, posting, fp,
                    created, resolved?, outcome?}

Best-effort throughout: a verdict-stamp must never break the apply loop.

CLI:
  verdicts.py stamp <kind> <target> "<reason>" [--url u] [--posting id] [--degraded]
  verdicts.py pending                 # suspects awaiting re-test on a healthy backend
  verdicts.py resolve <id> <confirmed|reversed> ["note"]
  verdicts.py fingerprint             # print a live health fingerprint (needs CFX_KEY)
"""
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fsutil import locked_append, file_lock, atomic_write  # noqa: E402

_here = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_here, "..", "..", ".."))
VERDICTS = os.path.join(_ROOT, "verdicts.jsonl")
REVALIDATE = os.path.join(_ROOT, "revalidate.jsonl")

# terminal-negative kinds this is meant to guard (documentary; any string is accepted)
KINDS = ("exhausted", "external-route", "no-apply-button", "wedge", "stuck",
         "loop-end", "blocked", "0-fresh")


def _fingerprint():
    """Best-effort cfx.health_fingerprint(); {} if cfx/browser unavailable."""
    try:
        import cfx
        return cfx.health_fingerprint()
    except Exception:  # noqa: BLE001
        return {}


def _is_suspect(kind, fp):
    """A verdict is suspect when the backend was provably degraded at verdict time, OR the
    page was blank-rendering for a verdict that implies a real page had loaded (external
    route / no-apply-button / wedge / stuck all mean 'I looked at a loaded page')."""
    if not fp:
        return False  # health unknown — can't claim degraded; recorded, not quarantined
    if fp.get("degraded") is True:
        return True
    page_verdicts = {"external-route", "no-apply-button", "wedge", "stuck", "loop-end"}
    if fp.get("blank_render") and kind in page_verdicts:
        return True
    return False


def stamp(kind, target, reason="", url="", posting="", fp=None, now=None):
    """Record a terminal negative with a health fingerprint. Returns a dict:
      {id, suspect, fp}. If suspect, it's also enqueued to revalidate.jsonl. Best-effort."""
    now = now or datetime.now()
    if fp is None:
        fp = _fingerprint()
    suspect = _is_suspect(kind, fp)
    vid = f"{now.strftime('%Y%m%dT%H%M%S')}-{(target or 'x')[:24]}"
    rec = {"id": vid, "ts": now.strftime("%Y-%m-%dT%H:%M:%S"), "kind": kind,
           "target": target, "reason": reason, "url": url, "posting": posting,
           "suspect": suspect, "fp": fp}
    try:
        locked_append(VERDICTS, lambda f: f.write(json.dumps(rec, ensure_ascii=False) + "\n"))
    except OSError:
        pass
    if suspect:
        q = {"id": vid, "kind": kind, "target": target, "reason": reason, "url": url,
             "posting": posting, "fp": fp, "created": rec["ts"],
             "resolved": False, "outcome": ""}
        try:
            locked_append(REVALIDATE, lambda f: f.write(json.dumps(q, ensure_ascii=False) + "\n"))
        except OSError:
            pass
    return {"id": vid, "suspect": suspect, "fp": fp}


def _read_jsonl(path):
    out = []
    try:
        with open(path, encoding="utf-8") as f:
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


def pending():
    """Unresolved suspect verdicts awaiting re-test on a healthy backend."""
    return [r for r in _read_jsonl(REVALIDATE) if not r.get("resolved")]


def resolve(vid, outcome, note="", now=None):
    """Mark a suspect resolved. outcome: 'confirmed' (genuine block, keep it) or 'reversed'
    (false verdict — the target is actually workable; re-queue it). Rewrites revalidate.jsonl
    atomically under the lock. Returns True if a row was updated."""
    now = now or datetime.now()
    with file_lock(REVALIDATE):
        rows = _read_jsonl(REVALIDATE)
        hit = False
        for r in rows:
            if r.get("id") == vid and not r.get("resolved"):
                r["resolved"] = True
                r["outcome"] = outcome
                r["resolved_at"] = now.strftime("%Y-%m-%dT%H:%M:%S")
                if note:
                    r["note"] = note
                hit = True
        if not hit:
            return False

        def _w(f):
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        atomic_write(REVALIDATE, _w)
    return True


def _cli(argv):
    cmd = argv[1] if len(argv) > 1 else ""

    def opt(flag, default=""):
        return argv[argv.index(flag) + 1] if flag in argv and argv.index(flag) + 1 < len(argv) else default

    if cmd == "stamp" and len(argv) >= 4:
        reason = argv[4] if len(argv) > 4 and not argv[4].startswith("--") else ""
        fp = {"degraded": True} if "--degraded" in argv else None
        res = stamp(argv[2], argv[3], reason=reason, url=opt("--url"),
                    posting=opt("--posting"), fp=fp)
        print(json.dumps(res, ensure_ascii=False))
        return 0
    if cmd == "pending":
        rows = pending()
        if not rows:
            print("no suspect verdicts pending re-validation.")
            return 0
        print(f"{len(rows)} SUSPECT verdict(s) recorded during a degraded backend — "
              f"re-test each on a HEALTHY backend before trusting it:")
        for r in rows:
            print(f"  {r['id']}  [{r['kind']}] {r['target']}  {r.get('url','')}  "
                  f"— {r.get('reason','')}")
        return 0
    if cmd == "resolve" and len(argv) >= 4:
        note = argv[4] if len(argv) > 4 else ""
        print("resolved" if resolve(argv[2], argv[3], note) else "not-found")
        return 0
    if cmd == "fingerprint":
        print(json.dumps(_fingerprint(), indent=2))
        return 0
    print("Usage: verdicts.py stamp <kind> <target> \"<reason>\" [--url u] [--posting id] "
          "[--degraded] | pending | resolve <id> <confirmed|reversed> [note] | fingerprint",
          file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(_cli(sys.argv))
