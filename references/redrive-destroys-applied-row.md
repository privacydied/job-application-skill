# Re-drive destroys an already-Applied row + preaudit Role-suffix dedup gap

**Two related data-integrity traps found 2026-07-24 while driving toward a cumulative
Applied target. Both cost a real prior submission (Figma Designer Advocate) before they
were caught and the row was hand-restored.**

## Trap 1 — `gh_apply.py` re-drive downgrades `Applied` -> `Blocked`

`gh_apply.py main()` ends with `_log(... "Blocked" ...)` whenever submit returns no
confirmation. It does NOT first check whether the (company, role, url) is ALREADY in the
tracker as `Applied`. So re-driving a posting that was genuinely submitted in a prior
session (proof `confirmation.png` on disk) flips it to `Blocked` and leaves a false
`proof=confirmation.png` note pointing at a non-existent/old artifact — destroying the
real submission record.

**Tell:** you ran `gh_apply` on a URL that you KNOW was applied before (the URL pattern
matches an `applications/<slug>/confirmation.png` on disk) and the run ends
`SUBMIT_NO_CONFIRM ... logging Blocked`.

**Fix (do this BEFORE any re-drive):**
1. Grep the tracker for the company+role AND check `applications/*/confirmation.png`
   for a slug containing the company+role tokens. If a real prior `Applied` + proof
   exists, DO NOT drive — skip and note "already Applied (prior run, proven)".
2. If `gh_apply` already downgraded it: restore the row — set `Status=Applied`, strip
   the false `| proof=confirmation.png` and the "duplicate-render / not drivable" note.
   Read-mutate-write the CSV in ONE `with open(...)` block (never `open('w')` then
   mid-write). See SKILL.md §Tracker for the safe pattern.

**Durable guard to add to `gh_apply.py`** (not yet shipped): at top of `main()`, after
loading the tracker, if `log-application.py` already shows `Applied` for this
company+role+url, print `ALREADY_APPLIED skip` and `return 0` instead of driving. Patching
the driver is the real fix; the manual restore above is the recovery.

## Trap 2 — `convertible_preaudit.py` `tracked_cr` misses Role-suffix tracker rows

`classify_strict`'s `tracked_cr` set is built from exactly
`(Company.lower(), Role.lower())`. But feed titles often carry a location/qualifier
suffix the tracker row does NOT — e.g. feed `role="Designer Advocate (London, United
Kingdom)"` vs tracker `Role="Designer Advocate"`. The exact-tuple match misses, so the
posting surfaces as `convertible` -> `REAL-DRIVABLE`, gets driven, and TRAPS 1 fires.

**Tell:** a preaudit `REAL-DRIVABLE` row whose company+role clearly looks already-applied
in the tracker but with a shorter Role string.

**Fix (pre-drive):** never trust the preaudit's `convertible`/`real-drivable` count as the
drive list. Reconcile EVERY candidate against the tracker by **URL prefix**
(`url.split('?')[0].rstrip('/')`) AND a **normalized (role-without-parenthetical-suffix)**
company+role tuple before driving. A helper that does both is worth folding into
`convertible_pool.py` so `tracked_cr` also stores the suffix-stripped role.

## Pre-drive reconciliation checklist (cheap, prevents both traps)

For each `REAL-DRIVABLE` candidate from the preaudit:
1. `url_prefix = url.split('?')[0].rstrip('/').lower()` — match tracker `URL` prefix.
2. `role_base = re.sub(r'\s*\([^)]*\)\s*$','',role).strip().lower()` — drop trailing
   `(London, United Kingdom)` etc. Match tracker `(Company, role_base)`.
3. If either matches an `Applied` tracker row OR a `confirmation.png` slug -> SKIP
   (already applied). Only then drive.

## Verification that the session used

- `python3 scripts/convertible_preaudit.py <fresh.json> ...` -> 30 convertible / 27
  real-drivable. The fresh-file-only run (NOT `/tmp/*.json`, which globs stale harvests
  and inflates the count) is the authoritative number.
- Reconciled the 27 by URL+role_base against `application-tracker.csv` -> only ~8 were
  genuinely NEW, and all hit a truthful wall (greenhouse headless react-select combo /
  academic Degree gate / WTTJ external-only / off-lane). No fabrication to pad a target.
