#!/usr/bin/env python3
"""
loop-preflight.py — the CHEAP CHECKPOINT run at the very top of every loop firing.

THE PROBLEM IT SOLVES. A /loop firing is a brand-new model instance with no memory of
prior firings; all state is on disk. Without a checkpoint, every firing re-derives
situational awareness the expensive way: read GOAL.md + the big SKILL.md, open a
browser, run every board feed, discover each is on cooldown / has nothing fresh, and
only THEN conclude "no new roles — stop." That full reasoning instance costs thousands
of tokens to reach a conclusion already knowable from a few small CSV files.

This CLI reads that state cheaply (no browser, no manuals) and prints a one-line
VERDICT plus the exact actionable searches. The decision logic lives in
`sites/_common/scripts/search_plan.py` (imported, never duplicated) so pipeline.py
shares it. This file is just the human/loop-facing CLI: verdict lines + exit codes.

  * WORK  — boot the full context and source ONLY the listed clear searches (ordered
            highest expected-yield first), or
  * DONE  — today's confirmed Applied count already meets the target: stop, don't source
            (a prior same-day firing finished the goal), or
  * SLEEP — every search cooling; reschedule the next wake for `wake_at`, or
  * HOLD  — a non-sanctioned CAPTCHA is waiting on the user.

Exit codes (so a shell/loop can branch without parsing text):
  0  WORK · 10 SLEEP · 11 HOLD · 12 DONE · 2 ERROR

Usage: loop-preflight.py [--target N]   (default target 10; also reads APPLY_TARGET env)

Output is human-readable lines PLUS `key=value` machine lines (verdict=, wake_at=,
clear=, cooling=, hold=, applied_today=) for easy scripting.
"""
import os
import sys
from datetime import datetime

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_here, "sites", "_common", "scripts"))
import search_plan as sp  # noqa: E402

PROFILE = os.path.join(_here, "references", "applicant-profile.md")
# Name-agnostic marker: the profile heading is "# Applicant Profile — <Your Name>".
# We check the stable prefix (so this works for anyone) and separately reject the
# un-personalised template (placeholder name still in place).
CANONICAL_MARKER = "# Applicant Profile"
_PLACEHOLDER_NAMES = ("Jane Doe", "[Your Name]", "Your Name")


def assert_canonical_dir():
    """Gate two failure modes before the loop runs against the wrong person:
      1. references/applicant-profile.md is missing → you haven't created your profile
         yet (copy references/applicant-profile.example.md and fill it in), or you're in
         the wrong directory.
      2. the profile is still the shipped TEMPLATE (placeholder name) → personalise it
         first, or you'd apply as "Jane Doe"."""
    try:
        with open(PROFILE, encoding="utf-8", errors="replace") as f:
            first = f.readline().strip()
    except FileNotFoundError:
        first = None
    if not first or not first.startswith(CANONICAL_MARKER):
        print("verdict=ERROR")
        print(f"ERROR: references/applicant-profile.md missing or not a profile (line 1 "
              f"is {first!r}). Copy references/applicant-profile.example.md to "
              f"references/applicant-profile.md and fill in your details, then retry.")
        return False
    if any(p in first for p in _PLACEHOLDER_NAMES):
        print("verdict=ERROR")
        print("ERROR: references/applicant-profile.md is still the template (placeholder "
              "name in the heading). Personalise it before running.")
        return False
    return True


def _target(argv):
    if "--target" in argv:
        try:
            return int(argv[argv.index("--target") + 1])
        except (IndexError, ValueError):
            pass
    env = os.environ.get("APPLY_TARGET")
    if env:
        try:
            return int(env)
        except ValueError:
            pass
    return sp.DEFAULT_TARGET


def main():
    now = datetime.now()
    if not assert_canonical_dir():
        return 2
    try:
        searches = sp.read_searches()
    except FileNotFoundError:
        print("verdict=ERROR")
        print(f"ERROR: {sp.SEARCHES} not found — cannot decide what to source.")
        return 2

    # Config self-check (WARNING ONLY): for a URL-keyed search, the `query` column MUST
    # equal what the feed extracts from its nav URL, or preflight and the feed check
    # DIFFERENT cooldown keys and a dry board looks "clear" (silent re-sourcing).
    import board_cooldown as bc  # noqa: E402
    for s in searches:
        from_url = bc.query_from_url(s["nav"]) if s.get("nav") else ""
        if from_url and bc.norm(from_url) != bc.norm(s["query"]):
            print(f"WARN config: searches.csv {s['board']!r} 'query' column != its nav URL's "
                  f"keyword param — preflight and the feed will use DIFFERENT cooldown keys "
                  f"(silent re-sourcing of a dry board). Align them.", file=sys.stderr)

    r = sp.plan(now=now, target=_target(sys.argv), searches=searches)
    v = r["verdict"]

    if v == "ERROR":
        print("verdict=ERROR")
        print(f"ERROR: {r.get('error')}")
        return 2

    if v == "HOLD":
        h = r["captcha_hold"]
        print("verdict=HOLD")
        print(f"hold=captcha site={h['site']} role={h['role']!r}")
        print(f"HOLD: a CAPTCHA is waiting on the user ({h['site']} — "
              f"{h['role'] or 'held application'}). The loop halts until it's solved. "
              f"Do NOT source or open a browser. Remind the user via VNC "
              f"(http://nasirjones:6080/vnc.html) and end the turn.")
        if h["url"]:
            print(f"held_url={h['url']}")
        return 11

    if v == "DONE":
        print("verdict=DONE")
        print(f"applied_today={r['applied_today']} target={r['target']}")
        print(f"DONE: {r['applied_today']} confirmed Applied row(s) today already meet the "
              f"target of {r['target']}. A prior same-day firing finished the goal. STOP — "
              f"do NOT source or open a browser. Re-verify the tracker if unsure; only a new "
              f"instruction (e.g. 'do 5 more') authorizes further applications.")
        return 12

    login_blocked = r.get("login_blocked") or set()

    if v == "WORK":
        clear, cooling = r["clear"], r["cooling"]
        print("verdict=WORK")
        print(f"clear={len(clear)} cooling={len(cooling)} applied_today={r['applied_today']}")
        print(f"WORK: {len(clear)} search(es) actionable now, {len(cooling)} still "
              f"cooling. Source ONLY these, in this order (highest expected yield first) "
              f"— do not touch the cooling ones:")
        for s in clear:
            nav = s["nav"] or "(wttj home feed — no nav url)"
            print(f"  - [{s['expected_yield']:>5}] {s['board']} :: {s['query']}  ->  {nav}")
        if login_blocked:
            print(f"note: skipping login-walled site(s): {', '.join(sorted(login_blocked))} "
                  f"(see holds.csv)")
        return 0

    # SLEEP
    if r.get("wake_at"):
        s0 = r["soonest"]
        print("verdict=SLEEP")
        print(f"wake_at={r['wake_at']} in_hours={r['in_hours']:.1f} cooling={len(r['cooling'])}")
        print(f"SLEEP: all {len(r['cooling'])} searches are on cooldown — there is provably "
              f"nothing fresh to source. The earliest to reopen is "
              f"{s0['board']}::{s0['query']} in {r['in_hours']:.1f}h.")
        print(f"Reschedule the next firing for {r['wake_at']} and STOP now. Do NOT open a "
              f"browser, read the manuals, or re-run the feeds.")
    else:
        print("verdict=SLEEP")
        print("wake_at= cooling=0")
        print("SLEEP: no actionable searches (all remaining are login-walled). Resolve the "
              "login hold(s) with the user to unblock.")
    if login_blocked:
        print(f"note: {', '.join(sorted(login_blocked))} also login-walled (holds.csv) — "
              f"resolve with the user to unblock sooner.")
    return 10


if __name__ == "__main__":
    sys.exit(main())
