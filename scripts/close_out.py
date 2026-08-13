#!/usr/bin/env python3
"""
close_out.py — RECONCILE a run's report against what's actually on disk, before you report it.

WHY THIS EXISTS (the 2026-07-24 scar). A close-out report claimed "Miro → logged Blocked
(Ashby driver gap)", "0 new verified submissions this run", and "only 1 of 323 Applied rows has
a confirmation artifact". Disk said otherwise: Miro's own
`applications/miro-content-editor/confirmation.txt` read "Your application was successfully
submitted", OakNorth had a green success screenshot (and was never mentioned at all), and 150
rows had proof cited AND on disk. Every error ran in the same direction — understating progress
— because the report was written from the agent's mid-run narrative instead of from disk. The
auto-submit path (atsform.apply submits + logs + captures proof when the form is clean) makes
that failure mode systemic: the orchestrator can finish an application AFTER the agent has
concluded "blocked" from step-level errors it saw earlier.

So: never hand-write a close-out summary. Run this, paste its GROUND TRUTH block, and resolve
every CONFLICT first.

WHAT IT ADDS over `audit_proofs.py` (which it REUSES, never re-implements — see AGENTS.md
§no-divergent-duplicate). audit_proofs answers "does every Applied row have a proof artifact?"
across the whole tracker. It deliberately only scans `Applied` rows and only checks that an
artifact EXISTS and is non-trivial. This adds the two directions it cannot see:
  1. REVERSE — a Blocked/Skipped/Unverified row whose artifact says the submission SUCCEEDED
     (the Miro case: a real submission reported as a failure, so it never counts and gets
     re-driven later).
  2. CONTENT — actually READ the .txt confirmation and classify success vs failure, so an
     artifact that says "We couldn't submit your application" (Lendable) is not mistaken for
     proof just because the file exists and is >1KB.
Plus date scoping (a close-out covers THIS run, not all history) and orphan detection
(an artifact folder written today with no tracker row at all).

Usage:
  close_out.py                      # reconcile TODAY, human report
  close_out.py --date 2026-07-24    # a specific day
  close_out.py --all                # every dated row (slow; whole-tracker sweep)
  close_out.py --json               # machine-readable

Exit codes: 0 clean · 3 CONFLICTS found (your report would be wrong — fix before reporting) · 2 error
"""
import argparse
import csv
import json
import os
import re
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_ROOT, "sites", "_common", "scripts"))
import audit_proofs as AP   # noqa: E402  (REUSE its artifact index/scoping helpers)
import journal              # noqa: E402  (slugify — the applications/<slug>/ convention)
import scrub_pii            # noqa: E402  (PII self-heal — see main()'s call, 2026-08-13)

TRACKER = os.path.join(_ROOT, "application-tracker.csv")
APPS = os.path.join(_ROOT, "applications")

# Text a confirmation artifact carries when the submission REALLY went through. Kept broad
# because every ATS words it differently (Ashby "successfully submitted", WTTJ "rooting for
# you", Butternut "we will review your application").
_SUCCESS_RE = re.compile(
    r"successfully submitted|application (?:was|has been)\s+(?:successfully\s+)?(?:submitted|received|sent)"
    r"|thank you for (?:your interest|applying)|we(?:'| wi)ll (?:be in touch|contact you|review your application)"
    r"|rooting for you|application (?:complete|received)|we have received your application", re.I)
# Text that means the submit FAILED even though an artifact exists (Lendable's red banner).
_FAILURE_RE = re.compile(
    r"couldn'?t submit|could not submit|unable to submit|failed to submit|not (?:been )?submitted"
    r"|please submit again|please try again|something went wrong|error submitting", re.I)

_TEXT_EXT = (".txt", ".md", ".html", ".json")


def _is_applied(status):
    return (status or "").strip().lower().startswith("applied")


def _flat(s):
    """Slug with separators stripped, for drift-tolerant comparison: drivers save
    `rightmove-product-designer-dataservices` while the tracker's Role yields
    `…-data-services`. Comparing flattened forms makes those the same folder instead of a
    phantom 'unlogged application' (false positives are how a checker gets ignored)."""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _slug_match(folder, slug):
    """True if `folder` is THIS row's application folder, tolerating the real drift seen on
    disk: an extra location/id suffix (`figma-designer-advocate-london-united-kingdom` for
    `figma-designer-advocate`), a `-2` disambiguation suffix, or separator drift. Prefix in
    EITHER direction — the folder may be longer (suffix) or shorter (truncated role)."""
    if not folder or not slug:
        return False
    f, s = _flat(folder), _flat(slug)
    if not f or not s:
        return False
    return f == s or f.startswith(s) or s.startswith(f)


def _row_dirs(company, role):
    """This row's application folder(s), matched drift-tolerantly. Still SCOPED to the row —
    never a tree-wide basename match, which would let one row's confirmation.png vouch for
    another's (the hole audit_proofs._proof_in_row_dir closed)."""
    if not os.path.isdir(APPS):
        return []
    slugs = [journal.slugify(company, role)]
    if role:
        slugs.append(journal.slugify(company))
    out = []
    for folder in sorted(os.listdir(APPS)):
        d = os.path.join(APPS, folder)
        if not os.path.isdir(d):
            continue
        # company+role match is authoritative; a company-only match is accepted only when it
        # isn't ambiguous with a different role's folder.
        if _slug_match(folder, slugs[0]):
            out.append(d)
    return out


def _row_artifacts(company, role):
    """Every confirmation artifact in THIS row's own applications/<slug>/ folder(s)."""
    out = []
    for d in _row_dirs(company, role):
        for fn in sorted(os.listdir(d)):
            p = os.path.join(d, fn)
            if os.path.isfile(p) and AP._CONFIRM_RE.search(fn):
                out.append(p)
    return out


def classify_artifacts(paths, min_image=1024):
    """-> (verdict, evidence). verdict: 'success' | 'failure' | 'exists_unreadable' | 'none'.

    TEXT WINS: a .txt/.html confirmation is read and matched, so an artifact whose content says
    the submit failed is never counted as proof. An image-only artifact can't be read here, so
    it is 'exists_unreadable' — presence is corroboration, NOT a success claim. That distinction
    is the whole point: it stops both false-positive proof and false-negative 'blocked'."""
    if not paths:
        return "none", ""
    unreadable = False
    for p in paths:
        if os.path.splitext(p)[1].lower() in _TEXT_EXT:
            try:
                with open(p, encoding="utf-8", errors="replace") as fh:
                    txt = fh.read(4000)
            except OSError:
                continue
            flat = re.sub(r"\s+", " ", txt).strip()
            if _FAILURE_RE.search(flat):
                return "failure", f"{os.path.relpath(p, _ROOT)}: {_FAILURE_RE.search(flat).group(0)!r}"
            if _SUCCESS_RE.search(flat):
                return "success", f"{os.path.relpath(p, _ROOT)}: {_SUCCESS_RE.search(flat).group(0)!r}"
        elif AP._nontrivial(p, min_image):
            unreadable = True
    if unreadable:
        return "exists_unreadable", ", ".join(os.path.relpath(p, _ROOT) for p in paths[:3])
    return "none", ""


def reconcile(date=None, all_rows=False, min_image=1024):
    """Cross-check tracker rows against on-disk artifacts, BOTH directions.

    Returns a dict with `counts`, `conflicts` (report-breaking; each is a dict with cls/row/
    detail) and `review` (needs a human eyeball, non-fatal — e.g. an image-only artifact on a
    non-Applied row, which we cannot read and must not auto-judge)."""
    try:
        with open(TRACKER, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    except (OSError, csv.Error) as e:
        return {"error": f"cannot read tracker: {e}"}

    if not all_rows:
        date = date or time.strftime("%Y-%m-%d")
        scope = [r for r in rows if (r.get("Date") or "").strip() == date]
    else:
        date, scope = "(all)", rows

    counts = {"scope_rows": len(scope), "applied": 0, "applied_q": 0, "blocked": 0,
              "skipped": 0, "other": 0, "verified_success": 0}
    conflicts, review = [], []

    for r in scope:
        status = (r.get("Status") or "").strip()
        low = status.lower()
        if low == "applied":
            counts["applied"] += 1
        elif low.startswith("applied"):
            counts["applied_q"] += 1
        elif low == "blocked":
            counts["blocked"] += 1
        elif low == "skipped":
            counts["skipped"] += 1
        else:
            counts["other"] += 1

        company, role = r.get("Company") or "", r.get("Role") or ""
        who = f"{company[:30]} | {role[:40]}"
        arts = _row_artifacts(company, role)
        verdict, evidence = classify_artifacts(arts, min_image)

        if verdict == "success":
            counts["verified_success"] += 1

        # (1) REVERSE — the Miro scar: reported as not-applied, but the artifact says it went in.
        if verdict == "success" and not _is_applied(status):
            conflicts.append({"cls": "UNDER_REPORTED", "status": status, "who": who,
                              "detail": f"artifact says SUBMITTED but row is {status!r} — a real "
                                        f"submission is being reported as a failure. {evidence}"})
        # (2) OVER-REPORTED — logged Applied but the artifact says the submit failed.
        elif verdict == "failure" and _is_applied(status):
            conflicts.append({"cls": "OVER_REPORTED", "status": status, "who": who,
                              "detail": f"row is {status!r} but artifact says the submit FAILED. "
                                        f"{evidence}"})
        # (3) Applied with nothing on disk at all.
        elif _is_applied(status) and verdict == "none":
            conflicts.append({"cls": "NO_ARTIFACT", "status": status, "who": who,
                              "detail": f"{status!r} with no confirmation artifact in "
                                        f"applications/{journal.slugify(company, role)}/ — "
                                        f"capture proof or downgrade to 'Applied?'/'Unverified'."})
        # (4) proof exists but the row never cites it (audit_proofs would later call this
        #     'no_evidence' and a --fix-all sweep could demote a REAL submission).
        elif _is_applied(status) and verdict in ("success", "exists_unreadable") \
                and "proof=" not in (r.get("Notes") or ""):
            review.append(f"UNCITED_PROOF  {status:9s} {who} — artifact on disk but Notes has no "
                          f"proof= citation ({evidence[:80]})")
        # (5) image-only artifact on a non-applied row: cannot read it, must not auto-judge.
        elif verdict == "exists_unreadable" and not _is_applied(status):
            review.append(f"CHECK_IMAGE    {status:9s} {who} — artifact exists but is image-only; "
                          f"open it to confirm this really failed ({evidence[:80]})")

    # (6) ORPHANS — an artifact folder no tracker row points at, i.e. a submission that was
    # made but NEVER logged (it can't count, and it'll be re-driven). Matched drift-tolerantly
    # against EVERY row in the whole tracker (not just this date) so a folder from an older row
    # isn't reported as unlogged.
    known = set()
    for r in rows:
        known.add(journal.slugify(r.get("Company") or "", r.get("Role") or ""))
        if (r.get("Role") or "").strip():
            known.add(journal.slugify(r.get("Company") or ""))
    known.discard("")
    known.discard("unknown")
    if os.path.isdir(APPS):
        for slug in sorted(os.listdir(APPS)):
            d = os.path.join(APPS, slug)
            if not os.path.isdir(d) or any(_slug_match(slug, k) for k in known):
                continue
            arts = [os.path.join(d, fn) for fn in os.listdir(d) if AP._CONFIRM_RE.search(fn)]
            v, ev = classify_artifacts(arts, min_image)
            if v != "success":
                continue
            # Only artifacts written ON the reconciled date are a close-out conflict. Older
            # unmatched folders are almost always COMPANY-ABBREVIATION drift, not unlogged work
            # (`co-motion-designer` = Cabinet Office, `dfe-…` = Department for Education,
            # `aisi-…` = AI Safety Institute — all logged under the full name). Reporting those
            # every run would bury the one line that matters; they surface under --all as review.
            same_day = any(time.strftime("%Y-%m-%d", time.localtime(os.path.getmtime(p))) == date
                           for p in arts if os.path.exists(p))
            if all_rows:
                review.append(f"ORPHAN_DIR     (no row)  {slug} — confirmation says submitted but "
                              f"no tracker row matches (often just company-abbreviation drift)")
            elif same_day:
                conflicts.append({"cls": "ORPHAN_SUCCESS", "status": "(no row)", "who": slug,
                                  "detail": f"confirmation written {date} says SUBMITTED but NO "
                                            f"tracker row matches — an UNLOGGED application "
                                            f"(it won't count and will be re-driven). {ev}"})

    return {"date": date, "counts": counts, "conflicts": conflicts, "review": review}


def _print_report(res):
    c = res["counts"]
    print("===== CLOSE-OUT GROUND TRUTH (read from disk — paste this, don't hand-write it) =====")
    print(f"date={res['date']} rows={c['scope_rows']}")
    print(f"Applied={c['applied']} Applied?={c['applied_q']} Blocked={c['blocked']} "
          f"Skipped={c['skipped']} other={c['other']}")
    print(f"verified_success={c['verified_success']}  "
          f"(rows whose OWN confirmation artifact text says the submission went through)")
    if res["conflicts"]:
        print(f"\n----- {len(res['conflicts'])} CONFLICT(S): your report would be WRONG -----")
        for x in res["conflicts"]:
            print(f"  [{x['cls']}] {x['who']}\n      {x['detail']}")
    if res["review"]:
        print(f"\n----- {len(res['review'])} needing a human eyeball (non-fatal) -----")
        for x in res["review"]:
            print("  " + x)
    if not res["conflicts"]:
        print("\nOK: no conflicts — the tracker matches the artifacts on disk.")
    else:
        print("\nFIX THE CONFLICTS BEFORE REPORTING. An UNDER_REPORTED row means a REAL "
              "submission is being reported as a failure (it won't count, and it'll be re-driven).")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--date", default=None, help="YYYY-MM-DD (default: today)")
    ap.add_argument("--all", action="store_true", help="every row, not just one date")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--min-image", type=int, default=1024)
    a = ap.parse_args()

    # PII self-heal (2026-08-13): SKILL.md step 11 makes THIS script mandatory before ANY
    # report, for every drive shape (full loop or an ad hoc "drive these N roles" session) and
    # for either agent — unlike scrub_pii's other call site (loop-preflight.py), which only
    # fires for the full autonomous loop. Piggybacking it on the one gate both agents already
    # must run closes the "Hermes never saw the CLAUDE.md-only PII rule" class of leak without
    # depending on either agent's prompt to remember it.
    try:
        scrubbed = scrub_pii.scrub()
        if scrubbed:
            n = sum(scrubbed.values())
            print(f"[close_out] scrub_pii: scrubbed {n} PII occurrence(s) in "
                  f"{len(scrubbed)} tracked file(s): {', '.join(sorted(scrubbed))}", file=sys.stderr)
    except Exception as e:   # never let the PII sweep block a close-out from running
        print(f"[close_out] scrub_pii self-heal skipped (non-fatal): {e}", file=sys.stderr)

    res = reconcile(date=a.date, all_rows=a.all, min_image=a.min_image)
    if res.get("error"):
        print(f"ERROR: {res['error']}", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps(res, indent=2))
    else:
        _print_report(res)
    return 3 if res["conflicts"] else 0


if __name__ == "__main__":
    sys.exit(main())
