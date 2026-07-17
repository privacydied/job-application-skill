#!/usr/bin/env python3
"""
audit_proofs.py — enforce the "Applied ⇒ provable" invariant on the whole tracker
(feature-roadmap H.2).

WHY THIS EXISTS. `log-application.py` gates NEW `Applied` rows on `--proof <existing file>`,
but SKILL.md documents rows still landing as `Applied` via OTHER paths (a manual csv.writer,
an external/parallel writer, a stale `echo >>`) — and the specific scar where a row cited
`--proof wttj-sent.png` whose file did NOT exist on disk. This driver closes that gap after
the fact: it scans every `Applied` row and verifies a real confirmation artifact exists on
disk; violators are demoted to `Applied?` so the strict `Applied` count keeps meaning
"provably submitted."

A row PASSES if either:
  * its Notes cite `proof=<file>` and that file exists somewhere under applications/ and is
    non-trivial (>1KB for an image, non-empty for text), OR
  * a confirmation artifact (confirmation.png/.txt/.jpg, *sent.png, screenshot*.png, …)
    exists in the row's applications/<slug>/ folder (slug derived from Company+Role).

Two violation CLASSES, treated very differently:
  * cites_missing — the row's Notes cite `proof=<file>` but that file is NOT on disk. This
    is the exact SKILL.md scar (a row citing `wttj-sent.png` that never existed). ACTIONABLE
    and safe to auto-demote: the row claims a proof it can't back up.
  * no_evidence — the row is `Applied` with NO `proof=` cited AND no confirmation artifact in
    its folder. Most of these are legitimate HISTORICAL rows logged before the proof-store
    convention (e.g. LinkedIn EA rows whose confirmation lived elsewhere). Demoting them all
    would be destructive, so they are REPORTED but NOT demoted unless you pass --fix-all.

SAFE: default is a DRY-RUN report. `--fix` demotes ONLY the `cites_missing` class (the real
scar). `--fix-all` also demotes `no_evidence` rows (use only after eyeballing the list).
Demotion is a single locked atomic rewrite (the SKILL.md-blessed "read all rows → mutate
list → writerows in ONE with-open('w') block" pattern; never a write that can throw after
truncate). Always prints the strict before/after count via tracker_stats.

Usage:
  audit_proofs.py               # dry-run: list both classes, print strict count
  audit_proofs.py --fix         # demote ONLY cites-missing-proof rows (the real scar)
  audit_proofs.py --fix-all     # also demote no-evidence historical rows (destructive)
  audit_proofs.py --min-image 1024   # override the non-trivial-image byte threshold
"""
import csv
import os
import re
import sys

_here = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_here)
sys.path.insert(0, os.path.join(_ROOT, "sites", "_common", "scripts"))
import tracker_stats  # noqa: E402
import journal        # noqa: E402  (slugify — same convention drivers save under)
from fsutil import file_lock, atomic_write  # noqa: E402

TRACKER = os.path.join(_ROOT, "application-tracker.csv")
APPS = os.path.join(_ROOT, "applications")
COLS = ["Date", "Company", "Role", "Source", "URL", "Status", "Next Action", "Notes"]

_CONFIRM_RE = re.compile(r"(confirmation|confirm|sent|submitted|screenshot|proof)",
                         re.I)


def _proof_files_index():
    """basename(lower) -> [full paths] for everything under applications/ (one walk)."""
    idx = {}
    for dirpath, _dirs, files in os.walk(APPS):
        for fn in files:
            idx.setdefault(fn.lower(), []).append(os.path.join(dirpath, fn))
    return idx


def _nontrivial(path, min_image):
    try:
        sz = os.path.getsize(path)
    except OSError:
        return False
    ext = os.path.splitext(path)[1].lower()
    if ext in (".png", ".jpg", ".jpeg", ".gif", ".pdf"):
        return sz >= min_image
    return sz > 0


def _slug_dir_has_confirmation(company, role, min_image):
    """A confirmation artifact in the row's applications/<slug>/ folder (any of a few slug
    spellings), non-trivial."""
    slugs = {journal.slugify(company, role), journal.slugify(company),
             journal.slugify(company, role).replace("--", "-")}
    for slug in slugs:
        d = os.path.join(APPS, slug)
        if not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            if _CONFIRM_RE.search(fn) and _nontrivial(os.path.join(d, fn), min_image):
                return True
    return False


def audit(rows, min_image=1024):
    """Return list of (index, row, cls, reason) for Applied rows lacking a real proof
    artifact. `cls` is 'cites_missing' (the actionable scar) or 'no_evidence' (historical)."""
    idx = _proof_files_index()
    violations = []
    for i, r in enumerate(rows):
        if (r.get("Status") or "").strip() != "Applied":
            continue
        notes = r.get("Notes") or ""
        m = re.search(r"proof=([^\s|]+)", notes)
        ok = False
        cls = reason = ""
        if m:
            val = m.group(1)
            base = os.path.basename(val).lower()
            # A live-page reconciliation reference (Reed: proof=/account/jobs/applications;
            # any http(s) URL; or a value whose basename has no file extension) is the
            # SANCTIONED batch-verification model in SKILL.md — verified against the board's
            # live Applications page, not a captured file. It passes.
            if val.startswith("/account") or re.match(r"https?://", val) or "." not in base:
                ok = True
            else:
                paths = idx.get(base)
                if paths and any(_nontrivial(p, min_image) for p in paths):
                    ok = True
                else:
                    cls = "cites_missing"
                    reason = f"cites proof={val} but no such non-trivial file on disk"
        if not ok and _slug_dir_has_confirmation(r.get("Company"), r.get("Role"), min_image):
            ok = True
        if not ok:
            if not cls:
                cls = "no_evidence"
                reason = "no proof= cited and no confirmation artifact in its applications/<slug>/"
            violations.append((i, r, cls, reason))
    return violations


def main():
    argv = sys.argv[1:]
    fix_all = "--fix-all" in argv
    do_fix = "--fix" in argv or fix_all
    min_image = 1024
    if "--min-image" in argv:
        try:
            min_image = int(argv[argv.index("--min-image") + 1])
        except (ValueError, IndexError):
            pass

    before = tracker_stats.stats()["applied"]
    print(f"strict Applied before: {before}")

    with file_lock(TRACKER):
        try:
            with open(TRACKER, newline="", encoding="utf-8") as f:
                rdr = csv.DictReader(f)
                fieldnames = rdr.fieldnames
                rows = list(rdr)
        except (FileNotFoundError, OSError) as e:
            print(f"FAIL: cannot read tracker: {e}", file=sys.stderr)
            return 2
        if fieldnames != COLS:
            print(f"FAIL: tracker header {fieldnames} != {COLS}", file=sys.stderr)
            return 2

        violations = audit(rows, min_image=min_image)
        cites = [v for v in violations if v[2] == "cites_missing"]
        noev = [v for v in violations if v[2] == "no_evidence"]
        if not violations:
            print("✓ every Applied row has a real confirmation artifact — nothing to demote.")
            return 0

        if cites:
            print(f"\n⚠️  {len(cites)} Applied row(s) CITE a proof file that is NOT on disk "
                  f"(the real scar — actionable):")
            for i, r, _cls, reason in cites:
                print(f"  row {i + 2}: {r.get('Company')} | {r.get('Role')} — {reason}")
        if noev:
            print(f"\n{len(noev)} Applied row(s) have NO proof cited and no confirmation "
                  f"artifact (mostly historical; NOT demoted unless --fix-all):")
            for i, r, _cls, _reason in noev[:20]:
                print(f"  row {i + 2}: {r.get('Company')} | {r.get('Role')}")
            if len(noev) > 20:
                print(f"  … and {len(noev) - 20} more")

        targets = cites + (noev if fix_all else [])
        if not do_fix:
            print(f"\nDRY-RUN. --fix would demote {len(cites)} cites-missing row(s) "
                  f"(strict {before} -> {before - len(cites)}). "
                  f"--fix-all would also demote {len(noev)} no-evidence row(s) "
                  f"(strict -> {before - len(violations)}).")
            return 0
        if not targets:
            print("\nnothing in the selected class(es) to demote.")
            return 0

        # mutate the list, then ONE atomic writerows (never a throw after truncate).
        for i, _r, cls, _reason in targets:
            rows[i]["Status"] = "Applied?"
            note = rows[i].get("Notes") or ""
            rows[i]["Notes"] = (note + " | " if note else "") + f"audit_proofs: demoted ({cls})"

        def _w(f):
            w = csv.DictWriter(f, fieldnames=COLS)
            w.writeheader()
            w.writerows(rows)
        atomic_write(TRACKER, _w)

    after = tracker_stats.stats()["applied"]
    print(f"\n✓ demoted {len(targets)} rows. strict Applied: {before} -> {after}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
