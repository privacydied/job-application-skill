#!/usr/bin/env python3
"""
search_plan.py — the ONE place that decides "what should this firing do?" from disk
state alone (no browser, no manuals). Both `loop-preflight.py` (the cheap checkpoint
CLI) and `pipeline.py` (the one-call sourcing orchestrator) import `plan()` so the
verdict logic is authored once, never mirrored (see references/maintaining-this-skill.md
on why mirrored policy is a hazard).

INPUTS (all small on-disk CSVs):
  searches.csv        board+query+nav rows the loop hunts
  board-cooldown.csv  which board+query are cooling, until when   (via board_cooldown)
  search-yields.csv   recent fresh-count per search               (via board_cooldown)
  holds.csv           hard-stop holds waiting on the user (captcha/login)
  application-tracker.csv   to count today's confirmed Applied rows

VERDICT (precedence order):
  HOLD  — a non-sanctioned CAPTCHA is held on the user: halt everything.
  DONE  — today's confirmed Applied count already meets the run target: stop, don't
          source (a prior same-day firing may have finished the goal). NEW 2026-07-15,
          folds the old SKILL.md bash grep into the checkpoint so a fresh instance
          learns "already done" without opening a browser.
  WORK  — >=1 search is actionable now (login-walled sites removed). The `clear` list
          is ORDERED BY expected_yield DESC (2026-07-15) so the highest-producing board
          is sourced first within the firing.
  SLEEP — every search is cooling; wake_at = when the earliest lapses.
  ERROR — searches.csv missing/unreadable.

Exit codes (loop-preflight maps these): 0 WORK · 10 SLEEP · 11 HOLD · 12 DONE · 2 ERROR.
"""
import csv
import os
import sys
from datetime import datetime, timedelta

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _here)
import board_cooldown as bc  # noqa: E402

# skill root = …/_common/scripts -> _common -> sites -> root
_ROOT = os.path.abspath(os.path.join(_here, "..", "..", ".."))
SEARCHES = os.path.join(_ROOT, "searches.csv")
HOLDS = os.path.join(_ROOT, "holds.csv")
TRACKER = os.path.join(_ROOT, "application-tracker.csv")
DEFAULT_TARGET = 10


def read_searches(path=SEARCHES):
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        for raw in f:
            if not raw.strip() or raw.lstrip().startswith("#"):
                continue
            parts = next(csv.reader([raw]))
            if parts[0].strip().lower() == "board":  # header
                continue
            board = parts[0].strip()
            query = parts[1].strip() if len(parts) > 1 else ""
            nav = parts[2].strip() if len(parts) > 2 else ""
            if board and query:
                rows.append({"board": board, "query": query, "nav": nav})
    return rows


def read_holds(path=HOLDS):
    """Active hard-stop holds. Format: type,site,role,url,created_at,note
    `type` is 'captcha' (halts everything) or 'login' (blocks only that site).
    Missing file / no rows => none. Delete a row (or the file) to clear it."""
    holds = []
    try:
        with open(path, newline="", encoding="utf-8") as f:
            for raw in f:
                if not raw.strip() or raw.lstrip().startswith("#"):
                    continue
                parts = next(csv.reader([raw]))
                if parts and parts[0].strip().lower() == "type":
                    continue
                if parts and parts[0].strip():
                    holds.append({
                        "type": parts[0].strip().lower(),
                        "site": parts[1].strip() if len(parts) > 1 else "",
                        "role": parts[2].strip() if len(parts) > 2 else "",
                        "url": parts[3].strip() if len(parts) > 3 else "",
                        "note": parts[5].strip() if len(parts) > 5 else "",
                    })
    except FileNotFoundError:
        pass
    return holds


def applied_today(tracker=TRACKER, day=None):
    """Count of rows with Status EXACTLY 'Applied' whose Date is today. Exact-match on
    the Status column (not a substring grep, which would also catch 'Applied?') and
    proper CSV parsing (a Notes field can contain commas). Returns 0 if unreadable."""
    day = day or datetime.now().strftime("%Y-%m-%d")
    n = 0
    try:
        with open(tracker, newline="", encoding="utf-8") as f:
            r = csv.DictReader(f)
            for row in r:
                if (row.get("Status") or "").strip() == "Applied" \
                        and (row.get("Date") or "").strip().startswith(day):
                    n += 1
    except (FileNotFoundError, OSError):
        pass
    return n


def plan(now=None, target=DEFAULT_TARGET, searches=None, holds=None,
         count_applied=True):
    """Pure decision function. Returns a dict with `verdict` and everything a caller
    needs to act, WITHOUT any side effects or I/O beyond the small CSV reads above."""
    now = now or datetime.now()
    if searches is None:
        try:
            searches = read_searches()
        except OSError:
            # Contract (docstring + exit-code 2): a missing/unreadable searches.csv is a
            # clean ERROR verdict, NOT an uncaught traceback escaping pipeline()/autodrain()
            # (read_holds/applied_today already guard their reads; this one was the gap).
            return {"verdict": "ERROR", "error": "searches.csv missing/unreadable"}
    if holds is None:
        holds = read_holds()
    if not searches:
        return {"verdict": "ERROR", "error": "searches.csv has no board,query rows"}

    captcha_hold = next((h for h in holds if h["type"] == "captcha"), None)
    login_blocked = {bc.norm(h["site"]) for h in holds if h["type"] == "login"}

    if captcha_hold:
        return {"verdict": "HOLD", "captcha_hold": captcha_hold,
                "login_blocked": login_blocked}

    done_n = applied_today(day=now.strftime("%Y-%m-%d")) if count_applied else 0
    # NB the DONE gate is evaluated AFTER inventory is computed (below), so a met target can
    # report how much is still actionable instead of masquerading as "every board exhausted"
    # — the footgun where a low default target (10) made a 49-applied day look dry.

    # G.3: parse each cooldown CSV ONCE for the whole pass, not once per search — was
    # O(searches × filesize) (50 searches × a full board-cooldown.csv/append-only
    # search-yields.csv read each). Thread the pre-parsed rows into the per-search checks.
    cd_rows = bc._read_rows()
    y_rows = bc._read_yield_rows()
    # Boards whose DAILY submission cap is still cooling (e.g. LinkedIn Easy Apply hit its
    # "daily limit … to prevent bots") — skip every one of their searches so sourcing shifts
    # to other boards, exactly like login_blocked but self-clearing when the cooldown lapses.
    # Checked once per DISTINCT board (not per search) against the pre-parsed cd_rows.
    rate_limited = {b for b in {bc.norm(s["board"]) for s in searches}
                    if bc.daily_limit_active(b, now=now, rows=cd_rows)}
    clear, cooling = [], []
    for s in searches:
        if bc.norm(s["board"]) in login_blocked:
            continue  # that whole site is login-walled this firing
        if bc.norm(s["board"]) in rate_limited:
            # The board-wide daily cap is SELF-CLEARING, so fold its remaining time into
            # `cooling` — otherwise, when every actionable board is daily-capped, plan()
            # fell through to `SLEEP wake_at=None` and loop-preflight reported a timed,
            # auto-clearing cap as an unrecoverable login wall needing manual intervention
            # (and in the mixed case, wake_at ignored a sooner-lapsing cap).
            rem = bc.remaining_hours(s["board"], bc.DAILY_LIMIT_KEY, now=now, rows=cd_rows)
            if rem > 0:
                cooling.append((s, rem))
            continue  # then switch boards for actual sourcing this firing
        # Cooldown-KEY ROBUSTNESS: derive it from the nav keyword (what the linkedin/indeed
        # feeds mark cooldown under, via query_from_url) with a fallback to the `query` column
        # (the fixed-QUERY boards csj/hackney/wttj have empty nav keywords and their column IS
        # the feed's constant). This makes preflight's key ALWAYS match the feed's mark, so a
        # mangled or `(Easy Apply)`-labelled query column can never make preflight check a
        # different key than the feed marks (the silent-re-sourcing bug). The column is now
        # documentary; its formatting no longer affects cooldown correctness.
        q_key = bc.query_from_url(s.get("nav", "")) or s.get("query", "")
        rem = bc.remaining_hours(s["board"], q_key, now=now, rows=cd_rows)
        if rem > 0:
            cooling.append((s, rem))
        else:
            ey = bc.expected_yield(s["board"], q_key, yield_rows=y_rows)
            clear.append((s, ey))

    # DONE gate, now inventory-aware: distinguishes "you hit your target" from "nothing left".
    if count_applied and target and done_n >= target:
        if clear:
            note = (f"target met ({done_n}/{target}) but NOT exhausted — {len(clear)} "
                    f"search(es) still actionable. Raise APPLY_TARGET to keep sourcing.")
        elif cooling:
            note = (f"target met ({done_n}/{target}); 0 clear, {len(cooling)} cooling. "
                    f"More would need a higher target after cooldowns lapse.")
        else:
            note = (f"target met ({done_n}/{target}); no clear or cooling searches "
                    f"(all login-walled / rate-limited). Genuinely nothing to source.")
        return {"verdict": "DONE", "applied_today": done_n, "target": target,
                "login_blocked": login_blocked, "rate_limited": rate_limited,
                "clear_available": len(clear), "cooling_count": len(cooling), "note": note}

    if clear:
        # Highest expected yield first (stable: preserves file order within a tie).
        clear.sort(key=lambda se: se[1], reverse=True)
        return {"verdict": "WORK",
                "clear": [{**s, "expected_yield": round(ey, 2)} for s, ey in clear],
                "cooling": cooling, "login_blocked": login_blocked,
                "rate_limited": rate_limited,
                "applied_today": done_n, "target": target}

    if cooling:
        cooling.sort(key=lambda cr: cr[1])
        soonest_s, soonest_rem = cooling[0]
        wake_at = (now + timedelta(hours=soonest_rem)).strftime("%Y-%m-%dT%H:%M:%S")
        return {"verdict": "SLEEP", "wake_at": wake_at, "in_hours": soonest_rem,
                "cooling": cooling, "soonest": soonest_s, "login_blocked": login_blocked,
                "rate_limited": rate_limited}

    # No clear searches and nothing cooling => everything is login-walled.
    return {"verdict": "SLEEP", "wake_at": None, "in_hours": None, "cooling": [],
            "soonest": None, "login_blocked": login_blocked}
