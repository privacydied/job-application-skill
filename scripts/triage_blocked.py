#!/usr/bin/env python3
"""
triage_blocked.py — surface retryable `Blocked` rows as a re-appliable queue (Tier-5
nightly auto-triage). When an ATS driver fix lands, the postings that were Blocked on
that ATS become applyable again — but nothing re-finds them because a `Blocked` row is
deliberately NOT dismissed on the board and NOT re-sourced. This groups the tracker's
Blocked rows by inferred ATS so a run (or a human) can re-queue the ones whose blocker
is now fixed.

It does NOT mutate the tracker (that stays the log of record) — it EMITS a queue.jsonl-
shaped retry list (same schema pipeline.py writes) that the apply loop can consume, and
prints a per-ATS Blocked tally.

Usage:
  triage_blocked.py                      # print the per-ATS Blocked tally
  triage_blocked.py --ats greenhouse     # emit retry rows for one ATS (whose fix landed)
  triage_blocked.py --all -o retry.jsonl # emit ALL Blocked rows as a retry queue
"""
import csv
import json
import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_here)
sys.path.insert(0, os.path.join(_ROOT, "sites", "_common", "scripts"))
import pipeline  # noqa: E402  — reuse ats_hint/family_of so retry rows match queue.jsonl
import board_cooldown as bc  # noqa: E402
import precheck  # noqa: E402  — classify_blocked/retry_pool: "Blocked" is TWO statuses in one

TRACKER = os.path.join(_ROOT, "application-tracker.csv")


def blocked_rows():
    rows = []
    try:
        with open(TRACKER, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if (row.get("Status") or "").strip() == "Blocked":
                    rows.append(row)
    except (FileNotFoundError, OSError):
        pass
    return rows


def _as_retry(row):
    url = (row.get("URL") or "").strip()
    board = bc.norm(row.get("Source") or "")
    hint = pipeline.ats_hint(url, board)
    title = row.get("Role") or ""
    return {
        "url": url, "title": title, "company": row.get("Company") or "",
        "board": row.get("Source") or "", "verdict": "keep",
        "verdict_reason": "retry: was Blocked — " + (row.get("Notes") or "")[:120],
        "family": pipeline.family_of(title), "ats_hint": hint,
        "apply_rank": pipeline.apply_rank(hint, pipeline._load_apply_stats()),
        "was_blocked": True,
    }


def main():
    argv = sys.argv[1:]
    ats = argv[argv.index("--ats") + 1] if "--ats" in argv and argv.index("--ats") + 1 < len(argv) else None
    want_all = "--all" in argv
    out = argv[argv.index("-o") + 1] if "-o" in argv and argv.index("-o") + 1 < len(argv) else None

    rows = blocked_rows()
    tally = {}
    for r in rows:
        h = pipeline.ats_hint((r.get("URL") or ""), bc.norm(r.get("Source") or ""))
        tally[h] = tally.get(h, 0) + 1

    if not ats and not want_all:
        print(f"{len(rows)} Blocked row(s) by inferred ATS:")
        for h, n in sorted(tally.items(), key=lambda kv: -kv[1]):
            print(f"  {n:>3}  {h}")
        print("\nRe-queue one ATS after its driver fix: "
              "triage_blocked.py --ats <ats> -o retry.jsonl", file=sys.stderr)
        return 0

    selected = rows if want_all else [
        r for r in rows if pipeline.ats_hint((r.get("URL") or ""), bc.norm(r.get("Source") or "")) == ats]

    # ⛔ A `Blocked` ROW IS NOT AUTOMATICALLY RETRYABLE (2026-08-17). `precheck.retry_pool` /
    # `classify_blocked` were built for exactly this ("Blocked means BOTH 'retry this' and
    # 'never retry this'"), and this emitter — the main producer of retry queues — never
    # called them. So a pool built here re-drives postings a previous run correctly judged
    # TERMINAL: off-profile, an anti-AI oath the applicant must sign himself, a truthful
    # eligibility gate. Live tonight: Monzo "Platform Engineer", whose own row reads
    # "Off-profile: production Kubernetes/Envoy/service-mesh … not a truthful match at this
    # level", was re-queued and driven TWICE on the single serial tab.
    #
    # DEFAULT: drop TERMINAL, keep UNKNOWN. Measured on this tracker, greenhouse's Blocked
    # rows are 72 unknown / 4 terminal — most carry no note at all — so excluding unknown by
    # default (retry_pool's own default) would empty the queue and make this tool useless.
    # The valuable half is dropping the 4 that a previous run explicitly judged dead. Pass
    # --retryable-only for retry_pool's stricter default, or --no-classify for the old
    # everything-goes sweep.
    if "--no-classify" not in argv:
        before = len(selected)
        selected = precheck.retry_pool(selected, include_unknown="--retryable-only" not in argv)
        if before != len(selected):
            print(f"  classify_blocked: dropped {before - len(selected)} row(s) a previous run "
                  f"judged terminal, of {before} (--no-classify to keep them)",
                  file=sys.stderr)

    retry = [_as_retry(r) for r in selected if (r.get("URL") or "").strip()]
    retry.sort(key=lambda x: x["apply_rank"])
    blob = "\n".join(json.dumps(r, ensure_ascii=False) for r in retry)
    if out:
        with open(out, "w", encoding="utf-8") as f:
            f.write(blob + ("\n" if blob else ""))
        print(f"wrote {len(retry)} retry row(s) -> {out}"
              + (f" (ATS {ats})" if ats else " (all)"), file=sys.stderr)
    else:
        print(blob)
    return 0


if __name__ == "__main__":
    sys.exit(main())
