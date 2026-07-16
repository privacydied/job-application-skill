#!/usr/bin/env python3
"""
board_cooldown.py — Python twin of board-cooldown.sh, so the feed.py scripts can
enforce the board+query exhaustion cooldown IN CODE instead of relying on the calling
agent to remember two soft prompt steps (`board-cooldown.sh check` before sourcing and
`board-cooldown.sh mark` after).

WHY THIS EXISTS (the leak it closes): per-posting dedup (application-tracker.csv +
board-native hide) already stops a single posting being re-screened twice. And
board-cooldown.csv already remembers "this whole board+query was confirmed dry." BUT
the cooldown was only ever consulted by a soft instruction in the loop prompt — a fresh
bot instance was *told* to check it before calling feed.py and mark it after. A fresh
instance carrying a huge SKILL.md routinely skipped those steps and just ran
`feed.py --nav <search>`, which navigates the browser, waits, re-enumerates every card
and re-filters the same already-declined postings — paying the full fetch+filter cost
for zero new information every single loop firing. That is the "new instance loads up,
goes over the same declined applications, then turns off" symptom.

This module lets feed.py:
  1. check() the cooldown BEFORE navigating — and bail instantly (no browser cost) if
     the combo is still dry, and
  2. mark() the cooldown automatically when a pass yields zero fresh candidates —
so neither step depends on the agent remembering. Same CSV, same format, same
normalization as board-cooldown.sh, so the two interoperate freely (the bash CLI is
still there for humans / ad-hoc use).

CSV: board,query,checked_at,cooldown_until  (ISO8601, local time), one row per key.
Key = f"{norm(board)}|{norm(query)}"; last matching row wins.
"""
import csv
import os
import re
from datetime import datetime, timedelta

from fsutil import file_lock, atomic_write  # shared lock + atomic write (Tier A)

_here = os.path.dirname(os.path.abspath(__file__))
# …/_common/scripts -> _common -> sites -> skill root
LOG = os.path.join(_here, "..", "..", "..", "board-cooldown.csv")
_FMT = "%Y-%m-%dT%H:%M:%S"
_HEADER = ["board", "query", "checked_at", "cooldown_until"]


def norm(s):
    """Cooldown-key normalizer: lowercase, strip a cosmetic `(easy apply)` annotation,
    collapse whitespace, spaces->'_'. WHY strip the label: searches.csv labels its
    Easy-Apply LinkedIn rows ` (Easy Apply)` in the `query` column, but the nav URL's
    `keywords=` (what `feed.py` marks cooldown under, via query_from_url) does NOT — Easy
    Apply is the `f_AL=true` nav param, not a keyword. Without stripping it, preflight (which
    reads the query column) checks a DIFFERENT cooldown key than the feed marks → every such
    board silently re-sources even when dry. Stripping it in the ONE key normalizer makes both
    sides agree regardless of the label (board-cooldown.sh delegates here, so it inherits this)."""
    s = re.sub(r"\(\s*easy\s*apply\s*\)", " ", (s or "").lower())
    return "_".join(s.split())


def _key(board, query):
    return f"{norm(board)}|{norm(query)}"


def _read_rows():
    """Every data row (board,query,checked_at,cooldown_until). Skips the header
    wherever it appears — NOT blindly the first line, so a header-less file (or one
    hand-appended without a header) doesn't silently lose its first real row."""
    rows = []
    try:
        with open(LOG, newline="", encoding="utf-8") as f:
            for row in csv.reader(f):
                if len(row) < 4:
                    continue
                if row[0].strip().lower() == "board" and row[1].strip().lower() == "query":
                    continue  # header line
                rows.append(row[:4])
    except FileNotFoundError:
        pass
    return rows


def remaining_hours(board, query, now=None, rows=None):
    """Hours left on this board+query's cooldown, or 0.0 if clear/expired/absent.
    Last matching row wins (mirrors the awk in board-cooldown.sh). G.3: pass pre-parsed
    `rows` (from _read_rows()) to avoid re-reading board-cooldown.csv once PER search when a
    caller like search_plan.plan() checks all 50 searches — read once, thread it in."""
    now = now or datetime.now()
    until_ts = None
    k = _key(board, query)
    for row in (rows if rows is not None else _read_rows()):
        if f"{norm(row[0])}|{norm(row[1])}" == k:
            until_ts = row[3]
    if not until_ts:
        return 0.0
    try:
        until = datetime.strptime(until_ts.strip(), _FMT)
    except ValueError:
        return 0.0
    delta = (until - now).total_seconds() / 3600.0
    return delta if delta > 0 else 0.0


def is_active(board, query, now=None):
    return remaining_hours(board, query, now=now) > 0


def mark(board, query, hours=12, now=None):
    """Record this board+query exhausted for `hours` (default 12). Rewrites the log
    without any prior row for this key, then appends the fresh one — same as the bash
    cmd_mark. Returns the cooldown_until timestamp string."""
    now = now or datetime.now()
    k = _key(board, query)
    until = now + timedelta(hours=float(hours))
    checked_at = now.strftime(_FMT)
    until_str = until.strftime(_FMT)
    # A.2: hold the lock across read→modify→atomic-write so a concurrent daemon+loop
    # can't lose each other's cooldown marks (both used to snapshot, both os.replace).
    with file_lock(LOG):
        kept = [row for row in _read_rows()
                if f"{norm(row[0])}|{norm(row[1])}" != k]

        def _w(f):
            w = csv.writer(f)
            w.writerow(_HEADER)
            for row in kept:
                w.writerow(row)
            w.writerow([norm(board), norm(query), checked_at, until_str])
        atomic_write(LOG, _w)
    return until_str


# A whole-board DAILY SUBMISSION cap (e.g. LinkedIn Easy Apply's "you've reached the daily
# limit … to prevent bots"). Stored under a reserved query key so it gates EVERY search on
# that board (search_plan.plan skips them) without disturbing per-query cooldowns.
DAILY_LIMIT_KEY = "__daily_submit_limit__"


def mark_daily_limit(board, hours=18, now=None):
    """Trip the board-wide daily-submission cooldown (default 18h ≈ clears next day).
    Returns cooldown_until. Callers: on detecting the platform's rate-limit banner, switch
    to other boards instead of burning attempts that can't land."""
    return mark(board, DAILY_LIMIT_KEY, hours=hours, now=now)


def daily_limit_active(board, now=None, rows=None):
    """True while the board's daily-submission cap is still cooling."""
    return remaining_hours(board, DAILY_LIMIT_KEY, now=now, rows=rows) > 0


# query params that carry the free-text search term, per board
_QUERY_PARAMS = ("q", "keywords", "query", "search")


def query_from_url(url):
    """Best-effort extract the free-text search term from a board search URL
    (Indeed `q=`, LinkedIn `keywords=`, …). Returns '' if none found."""
    from urllib.parse import urlparse, parse_qs, unquote_plus
    try:
        qs = parse_qs(urlparse(url).query)
    except Exception:
        return ""
    for p in _QUERY_PARAMS:
        if qs.get(p):
            return unquote_plus(qs[p][0]).strip()
    return ""


# ── Yield history + adaptive cooldown (2026-07-15) ─────────────────────────────
# WHY: a flat 12h cooldown makes the 27-row search set a flat nav tax — a row that
# is reliably dry gets re-checked as often as one that refills hourly. We log every
# sourcing pass's fresh-count to search-yields.csv and use it two ways:
#   * adaptive_hours() — escalate the cooldown on REPEATED dryness (12h × 2^(dry-1),
#     capped 72h) so a persistently-empty search stops being polled every 12h, but
#     keep a KNOWN high-yield row short (LinkedIn rotates hourly — a hot row that
#     just went dry is worth re-checking in ~6h, not 24–72h).
#   * expected_yield() — preflight orders the actionable searches by recent mean
#     yield, so the highest-value board is sourced first within a firing.
# search-yields.csv columns: ts,board,query,n_fresh  (append-only; one row per pass).
YIELDS = os.path.join(_here, "..", "..", "..", "search-yields.csv")
_YHEADER = ["ts", "board", "query", "n_fresh"]


def _read_yield_rows():
    rows = []
    try:
        with open(YIELDS, newline="", encoding="utf-8") as f:
            for row in csv.reader(f):
                if len(row) < 4:
                    continue
                if row[0].strip().lower() == "ts":
                    continue  # header
                rows.append(row[:4])
    except FileNotFoundError:
        pass
    return rows


def record_yield(board, query, n_fresh, now=None):
    """Append one sourcing-pass outcome (fresh-candidate count) for this board+query.
    Called by every feed on BOTH the dry path (n=0) and the success path (n>0) so the
    history reflects real productivity, not just failures. Best-effort — never raises."""
    now = now or datetime.now()
    try:
        n = int(n_fresh)
    except (TypeError, ValueError):
        n = 0
    try:
        # A.4: header-existence check + append under the lock so two racing appenders
        # can't double-write the header or interleave a row.
        with file_lock(YIELDS):
            new = not os.path.exists(YIELDS)
            with open(YIELDS, "a", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                if new:
                    w.writerow(_YHEADER)
                w.writerow([now.strftime(_FMT), norm(board), norm(query), n])
    except OSError:
        pass  # yield log is advisory; a write failure must never break sourcing


def yield_history(board, query, yield_rows=None):
    """[(ts_str, n_fresh:int)] for this key in file (chronological) order. G.3: pass
    pre-parsed `yield_rows` (from _read_yield_rows()) to avoid re-reading the append-only
    search-yields.csv once per search in a planning pass."""
    k = _key(board, query)
    out = []
    for row in (yield_rows if yield_rows is not None else _read_yield_rows()):
        if f"{norm(row[1])}|{norm(row[2])}" == k:
            try:
                out.append((row[0], int(row[3])))
            except ValueError:
                continue
    return out


def consecutive_dry(board, query):
    """How many of the MOST RECENT passes in a row yielded 0 fresh (0 if the last
    pass produced, or if there's no history)."""
    n = 0
    for _, cnt in reversed(yield_history(board, query)):
        if cnt == 0:
            n += 1
        else:
            break
    return n


def expected_yield(board, query, lookback=5, yield_rows=None):
    """Mean fresh-count over the last `lookback` passes (0.0 with no history) —
    a cheap 'how much does this search usually produce' signal for ordering. G.3:
    pass pre-parsed `yield_rows` to avoid re-reading search-yields.csv per search."""
    hist = [c for _, c in yield_history(board, query, yield_rows=yield_rows)][-lookback:]
    return (sum(hist) / len(hist)) if hist else 0.0


def adaptive_hours(board, query, base=12.0, cap=72.0, hot=6.0,
                   hot_threshold=3, lookback=6):
    """Cooldown hours to apply when a pass just went dry: 12h × 2^(consecutive_dry-1),
    capped at 72h — EXCEPT a row that just went dry for the first time but has recent
    high-yield history (LinkedIn-style fast refill) is capped at `hot` (6h) so we
    re-check it sooner. Deterministic, no clock use."""
    dry = consecutive_dry(board, query)
    hours = base * (2 ** max(0, dry - 1))
    hours = min(hours, cap)
    recent = [c for _, c in yield_history(board, query)][-lookback:]
    if dry <= 1 and any(c >= hot_threshold for c in recent):
        hours = min(hours, hot)
    return hours


def mark_adaptive(board, query, n_fresh, now=None):
    """The feeds' one-call path: record this pass's yield, then (only if it was dry)
    set an ADAPTIVE cooldown. Returns the cooldown_until string, or "" if not marked
    (a productive pass is not cooled — there may be more fresh work)."""
    record_yield(board, query, n_fresh, now=now)
    if int(n_fresh or 0) > 0:
        return ""
    return mark(board, query, hours=adaptive_hours(board, query), now=now)


def _cli(argv):
    """CLI twin of board-cooldown.sh, with identical output strings — board-cooldown.sh
    delegates here so both share ONE CSV-correct parser (awk -F',' in the old bash
    mis-split quoted queries that contain commas/quotes)."""
    import sys
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "check" and len(argv) >= 4:
        rem = remaining_hours(argv[2], argv[3])
        print("clear" if rem <= 0 else f"cooldown active: {rem:.1f}h remaining")
        return 0
    if cmd == "mark" and len(argv) >= 4:
        try:
            hours = float(argv[4]) if len(argv) > 4 and argv[4] else 12
        except ValueError:
            print(f"ERROR: hours must be a number, got {argv[4]!r}", file=sys.stderr)
            return 2
        until = mark(argv[2], argv[3], hours=hours)
        print(f"marked {norm(argv[2])}/{norm(argv[3])} exhausted until {until}")
        return 0
    if cmd == "yield" and len(argv) >= 5:
        record_yield(argv[2], argv[3], argv[4])
        print(f"recorded {norm(argv[2])}/{norm(argv[3])} yield={argv[4]} "
              f"(dry_streak={consecutive_dry(argv[2], argv[3])}, "
              f"next_cooldown={adaptive_hours(argv[2], argv[3]):.0f}h)")
        return 0
    if cmd == "expected" and len(argv) >= 4:
        print(f"{expected_yield(argv[2], argv[3]):.2f}")
        return 0
    print("Usage: board_cooldown.py check|mark|yield|expected <board> <query> [hours|n]",
          file=sys.stderr)
    return 1


if __name__ == "__main__":
    import sys
    sys.exit(_cli(sys.argv))
