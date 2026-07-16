#!/usr/bin/env python3
"""ratelimit.py — LinkedIn daily-submission rate-limit: detect, save, switch boards.

LinkedIn caps Easy Apply submissions per day ("You've reached the daily limit … to
prevent bots / maintain quality"). Once hit, no further LinkedIn submissions land, so
grinding the queue just wastes attempts. The correct response, split across the loop:

  1. DETECT the limit banner (`detect(cfx)` / `looks_rate_limited(text)`).
  2. SAVE the in-flight posting to `deferred-applications.jsonl` (`defer(row)`) so it is
     applied later, not lost — independent of whether it is re-sourced.
  3. TRIP the board-wide cooldown (`trip()` → `board_cooldown.mark_daily_limit`) so
     `search_plan.plan` and `pipeline` skip LinkedIn until it clears.
  4. SWITCH boards — the caller (`apply_queue.py`) stops the LinkedIn drain; the next
     sourcing pass sources CSJ / Indeed / welcometothejungle etc. instead.

On the next run, once the cooldown clears, `apply_queue` re-injects the deferred rows
first, and each is pruned when it lands (tracker dedup). No submit is ever retried on a
mutating POST here — only sourcing/queue state is touched.
"""
import json
import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.join(_here, "..", "..", "..")
sys.path.insert(0, os.path.join(_here, "..", "..", "_common", "scripts"))
import board_cooldown as bc  # noqa: E402
import fsutil                # noqa: E402

BOARD = "linkedin"
DEFERRED = os.path.join(_ROOT, "deferred-applications.jsonl")

# Each tuple is an AND-set: all tokens must appear in the banner text. Kept deliberately
# small + specific so a normal JD sentence can't trip it (detect() also scopes the DOM read
# to the modal/toast, not the whole page).
_SIGNALS = (
    ("reached", "limit"),
    ("daily", "limit"),
    ("weekly", "limit"),
    ("too many", "appl"),
    ("maximum", "appl"),
    ("limit", "submission"),
    ("limit", "per day"),
    ("limit", "bots"),
)


def looks_rate_limited(text):
    """True if `text` reads like a daily/weekly application-limit notice."""
    low = (text or "").lower()
    return any(all(tok in low for tok in combo) for combo in _SIGNALS)


# DOM scan scoped to the Easy Apply modal + LinkedIn toasts / alert dialogs — NOT the whole
# page, so a JD paragraph mentioning "limit" can't false-trip. Returns candidate banner text.
_SCAN_JS = r"""
(() => {
  const sel = '.artdeco-modal, .artdeco-toast-item, .jobs-easy-apply-content,' +
              ' [role=alertdialog], [role=alert], .ip-fuse-limit-reached';
  const scopes = [...document.querySelectorAll(sel)];
  for (const el of (scopes.length ? scopes : [])) {
    const t = (el.innerText || '').replace(/\s+/g, ' ').trim();
    if (/limit|too many|maximum number/i.test(t)) return t.slice(0, 400);
  }
  return '';
})()
"""


def detect(cfx):
    """Read the visible modal/toast text via `cfx` and return True iff it's a rate limit.
    Best-effort: any browser error → False (never block the loop on a flaky read)."""
    try:
        t = cfx.evaluate(_SCAN_JS)
    except Exception:
        return False
    return looks_rate_limited(t if isinstance(t, str) else "")


def trip(board=BOARD, hours=18):
    """Mark the board-wide daily-submit cooldown; returns cooldown_until."""
    return bc.mark_daily_limit(board, hours=hours)


def active(board=BOARD):
    """True while the board is under its daily-submit cooldown."""
    return bc.daily_limit_active(board)


# ---- deferred store: "save the application, apply later" ---------------------------------

def _url(row):
    return (row or {}).get("url") or ""


def load_deferred():
    """Rows saved for later (dedup by url, last-wins). Missing file → []."""
    seen = {}
    try:
        with open(DEFERRED, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if _url(r):
                    seen[_url(r)] = r
    except FileNotFoundError:
        pass
    return list(seen.values())


def defer(row):
    """Append `row` to the deferred store (locked, dedup-safe). No-op without a url."""
    if not _url(row):
        return False
    existing = {_url(r) for r in load_deferred()}
    if _url(row) in existing:
        return True

    def _w(f):
        f.write(json.dumps(row, ensure_ascii=False) + "\n")

    fsutil.locked_append(DEFERRED, _w)
    return True


def rewrite_deferred(rows):
    """Replace the deferred store with `rows` (used to prune landed postings). Empties the
    file when `rows` is empty."""
    def _w(f):
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    fsutil.atomic_write(DEFERRED, _w)


if __name__ == "__main__":
    # tiny CLI: `ratelimit.py status` — show cooldown + deferred count
    if len(sys.argv) > 1 and sys.argv[1] == "status":
        rem = bc.remaining_hours(BOARD, bc.DAILY_LIMIT_KEY)
        print(f"linkedin daily-limit: {'ACTIVE ' + f'{rem:.1f}h left' if rem > 0 else 'clear'}"
              f" · deferred={len(load_deferred())}")
    else:
        print("Usage: ratelimit.py status")
