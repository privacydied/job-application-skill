# human-queue-count-integrity.md — the "~N unlocked" must be a SCREENED estimate

## The bug (2026-07-23)
`scripts/human_queue.py` reported `HUMAN BATCH SESSION — 5 action(s), ~203 applications unlocked` by summing `accounts-needed.csv` `est_inventory` hand-typed guesses (tfl=60, bbc=50, parliament=40, guardian=20) and printing them as "applications unlocked" — **without** screening against the applicant's lane / seniority / location. It also double-counted Guardian (a `captcha` item keyed on `jobs.theguardian.com` + an `account` item keyed on `guardian`, never deduped). The real honest number was **~4** (Guardian's on-lane design roles only; TfL/BBC/Parliament were **0 on-lane**).

The user caught it cold: *"I drove all 5 of hermes's 'account unblocks' to ground. The '~203' is fabricated."* — every board was 0 on-lane or double-counted on live inspection.

## The fix (in-tree, verified)
`human_queue.py` now:
- `_screen_inventory(site)` harvests the target's live HTTP-keyless `feed.py` and counts only on-lane junior→mid London/remote postings via `check_title` (lane + seniority + location). The hand-typed `est_inventory` is **NEVER** echoed.
- `_root()` normalises site tokens (drops `jobs.`/`careers.`/`profile.`/`www.` prefix, aliases the Guardian family) so a captcha item and an account item for the same site collapse to **ONE** action.
- Removed the `max(…,1)` floor that manufactured a count from stale ledger rows.
- The print shows `screened=N from live harvest; was est_inventory guess — NOT echoed`.

Verified: `python3 scripts/human_queue.py` → "4 action(s), ~4 applications unlocked"; TfL/BBC/Parliament show ~0 (matching live check). `tests/test_core.py`: 245 passed (1 pre-existing unrelated failure in `inspect_gh_form.py`, untouched).

## Invariant to preserve
NEVER let a headline unlock/ceiling number reach the user that is (a) a stored guess, (b) unscreened against `check_title`, or (c) double-counted across ledgers. When a board's real on-lane inventory is ~0, report ~0 — do not pad with the guess or with off-lane roles. This is the same principle as the SKILL.md RE-HARVEST GUARD and DATA-SCARCITY CEILING: screen every aggregate before reporting it.

## Reusable recipe — verify a board's honest on-lane count headlessly
```
python3 sites/<board>/scripts/feed.py --all --where "" --force > /tmp/harvest/<board>.json
python3 - <<'PY'
import sys, json, re
sys.path.insert(0, 'sites/_common/scripts')
from check_title import check_title
SEN = re.compile(r'\b(senior|staff|principal|lead|head|director|manager|vp|chief|sr\.?)\b', re.I)
LOC = re.compile(r'london|remote|uk|england|emea|europe|home based|ireland', re.I)
rows = json.load(open('/tmp/harvest/<board>.json'))
on = [j for j in rows
      if check_title(j['title']).get('eligible')
      and not SEN.search(j['title'])
      and LOC.search(j['location'] or '')]
print('<board> on-lane junior→mid London/remote:', len(on))
PY
```
