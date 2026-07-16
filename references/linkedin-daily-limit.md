# LinkedIn daily submission limit — detect, save, switch boards

LinkedIn caps Easy Apply submissions per day ("You've reached the daily limit … to
prevent bots / maintain quality"). Submitting past the cap can't land, so the loop stops
LinkedIn and works other boards instead. Handling is automatic in `apply_queue.py`; the
logic lives in `sites/linkedin/scripts/ratelimit.py`. Same pattern applies to any board
that grows a daily cap.

## What happens (4 steps)
1. **Detect** — after any non-success `apply_ea` result, `ratelimit.detect(cfx)` scans the
   Easy Apply modal / toast / alert (scoped — not the whole JD, so a JD sentence can't
   false-trip) for a daily/weekly limit banner (`looks_rate_limited`).
2. **Save** — the in-flight posting is appended to `deferred-applications.jsonl`
   (`ratelimit.defer`, dedup by url) so it is applied later, not lost.
3. **Trip** — `ratelimit.trip()` marks a board-wide cooldown
   (`board_cooldown.mark_daily_limit`, default 18h ≈ clears next day) under the reserved
   key `__daily_submit_limit__`. `search_plan.plan` then skips every LinkedIn search
   (surfaced as `rate_limited` in the plan) and `pipeline`/sourcing shift to CSJ / Indeed /
   welcometothejungle etc.
4. **Switch** — `apply_queue` stops the LinkedIn drain and reports `rate_limited: true`.

## Apply later
On a later run, once the cooldown lapses, `apply_queue` re-injects the deferred postings
FIRST (dropping any already applied since) and prunes the store as they land. Inspect:

    python3 sites/linkedin/scripts/ratelimit.py status

## Tuning / extending
- Cooldown length: `mark_daily_limit(board, hours=…)`. The cap is per-day/rolling; if still
  limited next run, a failed submit re-trips it.
- Banner wording: extend `_SIGNALS` in `ratelimit.py` if LinkedIn rewords the notice. Each
  entry is an AND-set of lowercase tokens; keep them specific so normal copy can't match.
- Detection never auto-retries a submit (double-submit risk) — only sourcing/queue state is
  touched.
