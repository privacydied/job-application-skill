# gh_apply re-drive integrity — never downgrade Applied → Blocked

**Symptom (2026-07-24, verified live):** re-driving a Greenhouse role that was ALREADY
`Applied` in a prior run caused `gh_apply.py` to log the row as `Blocked` — destroying the
real prior submission history. `gh_apply.main()` calls `_log(..., "Blocked", ...)` on ANY
submit failure (CODE_MISSING / required-field bounce) WITHOUT first checking whether the
tracker row is already `Applied`. A failed re-drive is treated as a fresh failure and
overwrites a good `Applied` with a bad `Blocked` (and even appends a false `| proof=...`
note when a stale `confirmation.png` exists in the slug dir).

**Root cause — TWO gaps that let a re-drive happen at all:**
1. `gh_apply` does not short-circuit when the target (Company, Role, URL) is already `Applied`.
   It re-navigates + re-submits, and on the (very common) headless react-select wall logs Blocked.
2. `convertible_pool.classify_strict` + `convertible_preaudit.py` fail to flag already-applied
   Greenhouse roles as `tracked` because of a **URL + title normalization mismatch**:
   - Feed URLs from `feed.py` are `https://boards.greenhouse.io/<co>/jobs/<N>` (NO `?gh_jid=`).
     Tracker URLs carry `?gh_jid=<N>`. `classify_strict` checks `url in tracked_urls` → the
     bare feed URL is NOT a substring/prefix match of the `?gh_jid=` tracker URL → not tracked.
   - `tracked_cr` is `(company.lower(), role.lower())`. Feed titles embed location:
     `"Designer Advocate (London, United Kingdom)"` vs stored `"Designer Advocate"` → exact
     tuple mismatch → not tracked. Result: Figma "Designer Advocate" was classified `convertible`
     and re-driven, downgrading a real `Applied`.

**Fix (apply both):**
- In `gh_apply.main()`, BEFORE `cfx.goto`, check the tracker for an existing `Applied` row
  matching `url.split('?')[0]` (prefix) OR `(company.lower(), role.lower() sans " (...)" suffix)`.
  If found, `print("ALREADY_APPLIED skip")` and `return 0` — never re-drive an applied role.
- `classify_strict` dedup must normalize: strip `?gh_jid=...` from BOTH feed and tracker URLs
  before the `url in tracked_urls` check, AND compare `role` after stripping a trailing
  ` (...)` location suffix (or compare on `company + first 3 words of title`). This closes the
  Figma-class miss where the same role is re-surfaced as "fresh".
- **Restore-on-catch (if a re-drive already downgraded a row):** do NOT hand-edit with an
  inline `open('w')`. Reconcile by re-reading `applications/<slug>/confirmation.png` proof files
  and restoring any `Blocked` row whose slug has a real `confirmation.png` AND whose
  company/role matches a proven prior apply. The 2026-07-24 session restored Figma this way
  (proof at `applications/figma-designer-advocate-london-united-kingdom/confirmation.png`).

**Verification gate (run after EVERY drive batch):** capture the pre-run `tracker_stats.py
--count`, then re-run it. A *drop* means a row was wrongly downgraded — investigate (the
count tool has no guard against Applied→Blocked downgrades) before reporting. This caught the
Figma incident: the tool printed 367 pre-run and the downgraded file read 366 `Status==Applied`
with Figma flipped to `Blocked`.
