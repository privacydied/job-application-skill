#!/usr/bin/env python3
"""audit_board.py — "what's live on this WHOLE board, and what have I already applied to?"
in ONE shipped command, across ALL of the board's searches.csv families.

WHY THIS EXISTS. The AUDIT (unlike the queue) needs the already-tracked rows shown, not
dropped — merge_sources drops them, so `apply_queue.py --refresh` / `pipeline.run()` cannot
answer it, and the loop doc only documented a SINGLE-family one-liner (`feed.py --what "<fam>"
--all | precheck.py -`). Faced with "audit the whole board", agents therefore hand-rolled
`/tmp/<board>_audit.py` wrappers that loop the families, grep the JSON out of feed stdout, and
re-parse it — the exact FORBIDDEN `for kw in <families>` + `raw.find('[')` pattern (it broke on
the feed's leading summary line and got rewritten 3×). This closes that tool gap: it reads the
board's families from searches.csv (the canonical `search_plan.read_searches`), runs each through
the shipped feed with `--all` via `pipeline.run_feed` (which owns the stdout parsing + tab-death
retry — no grepping), dedups by canonical id (`merge_sources`), and screens once with the
canonical `precheck.precheck`. Same tools the funnel uses; zero re-implementation.

Output = the whole board in one shot:
  · FRESH  — on-profile and NOT yet applied  (the new work list)
  · TRACKED— already in application-tracker.csv (what you've applied to / blocked)
  · other drops are counted (title/location/seniority rejects), shown with --verbose.

Usage:
    python3 scripts/audit_board.py <board> [--json] [--fresh-only] [--verbose]
      <board>       a searches.csv board token (csj, nhs, linkedin, indeed, guardian, …).
      --json        machine output {board, families, fresh:[…], tracked:[…], counts}.
      --fresh-only  print only the FRESH work list (skip the tracked/other sections).
      --verbose     also list the other-drop rejects with their reason.

Exit: 0 ok · 2 no searches.csv families for that board (add rows) / bad usage.
"""
import json
import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_here, "..", "sites", "_common", "scripts"))
import board_cooldown as bc   # noqa: E402
import merge_sources         # noqa: E402
import pipeline              # noqa: E402
import precheck              # noqa: E402
import search_plan           # noqa: E402


def _is_tracked(entry):
    return "already tracked" in (entry.get("verdict_reason") or "").lower()


def audit(board):
    """Returns (families, fresh, tracked, other, per_family, sourced_total)."""
    fams = [r for r in search_plan.read_searches() if bc.norm(r["board"]) == bc.norm(board)]
    if not fams:
        return None
    all_posts = []
    per_family = {}
    for r in fams:
        q = r["query"]
        posts, err = pipeline.run_feed(r["board"], r.get("nav", ""), force=True,
                                       query=q, extra=["--all"])
        for p in posts:
            if isinstance(p, dict):
                p.setdefault("_family", q)
        per_family[q] = {"sourced": len(posts), "err": err}
        all_posts.extend(posts)
        print(f"  sourced {q:<22} {len(posts):>3} cards" + (f"  ERR: {err}" if err else ""),
              file=sys.stderr)
    # dedup within the board by canonical id (a vacancy can appear under >1 family keyword);
    # drop_tracked=False so precheck — not the merge — owns the tracker verdict (and can label it).
    merged, _ = merge_sources.merge_lists(all_posts, drop_tracked=False, cross_board=False)
    res = precheck.precheck(merged)
    fresh = res.get("keep", []) + res.get("review", [])
    tracked = [e for e in res.get("drop", []) if _is_tracked(e)]
    other = [e for e in res.get("drop", []) if not _is_tracked(e)]
    return {"families": fams, "fresh": fresh, "tracked": tracked, "other": other,
            "per_family": per_family, "sourced_total": len(all_posts), "unique": len(merged)}


def _row(e):
    return (f"  {(e.get('id') or '—')!s:>10} | {(e.get('title') or '')[:44]:<44} | "
            f"{(e.get('company') or '')[:24]}")


def main():
    argv = sys.argv[1:]
    boards = [a for a in argv if not a.startswith("-")]
    if not boards:
        print(__doc__)
        return 2
    board = boards[0]
    as_json = "--json" in argv
    fresh_only = "--fresh-only" in argv
    verbose = "--verbose" in argv

    a = audit(board)
    if a is None:
        print(f"audit_board: no searches.csv families for board {board!r} — add "
              f"`{board},<family>,<nav>` rows first (that is the sanctioned knob).",
              file=sys.stderr)
        return 2

    if as_json:
        def slim(e):
            return {k: e.get(k) for k in ("id", "title", "company", "url", "_family",
                                          "verdict_reason")}
        print(json.dumps({
            "board": board,
            "counts": {"families": len(a["families"]), "sourced": a["sourced_total"],
                       "unique": a["unique"], "fresh": len(a["fresh"]),
                       "tracked": len(a["tracked"]), "other_drop": len(a["other"])},
            "fresh": [slim(e) for e in a["fresh"]],
            "tracked": [slim(e) for e in a["tracked"]],
        }, ensure_ascii=False, indent=1))
        return 0

    print(f"\n=== audit {board} — {len(a['families'])} families · {a['sourced_total']} sourced · "
          f"{a['unique']} unique ===")
    print(f"FRESH (on-profile, NOT yet applied): {len(a['fresh'])}  |  "
          f"already TRACKED: {len(a['tracked'])}  |  other drops: {len(a['other'])}\n")

    print(f"FRESH — the work list ({len(a['fresh'])}):")
    for e in a["fresh"] or []:
        print(_row(e) + f"  {e.get('url') or ''}")
    if not a["fresh"]:
        print("  (none — every on-profile role on this board is already tracked or screened out)")

    if not fresh_only:
        print(f"\nALREADY TRACKED on this board's live listings ({len(a['tracked'])}):")
        for e in a["tracked"]:
            print(_row(e) + f"  [{(e.get('verdict_reason') or '').split('(')[-1].rstrip(')')}]")
        if verbose:
            print(f"\nOTHER DROPS (title/location/seniority) ({len(a['other'])}):")
            for e in a["other"]:
                print(_row(e) + f"  {e.get('verdict_reason') or ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
