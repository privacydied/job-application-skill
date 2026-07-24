# Prior-run "ceiling" notes are non-authoritative — re-source everything, verify live

## Why this exists (2026-07-24 same-day lesson)
A convertible-ceiling note written earlier the same day concluded "0 new drivable." A
later fresh full pass that SAME day RE-CONFIRMED the conclusion (still 324 strict
`Applied`, still 0 new on-lane untracked) — so the ceiling was real. BUT the note was
wrong in three ways that would mislead a future session if copied forward:

1. **Incomplete board coverage.** It sourced only ats-direct / WTTJ / CSJ / Reed /
   LinkedIn. Hackney, NHS, Parliament, TfL, BBC, and Guardian were NEVER sourced in
   that pass — yet they're all configured in `searches.csv` with shipped `feed.py`
   drivers. "0 convertible" was scoped to 5 boards, not the configured universe.
2. **Stale baseline number.** It cited "366 Applied (EA-reconciled)"; `tracker_stats.py
   --count` returned **324** (0 forbidden EA rows). The number had drifted.
3. **Wrong channel-state claim.** It declared WTTJ in-platform a blanket Axeptio/promo
   overlay wall. In fact `loveholidays | Product Designer (12-Month FTC)` was `Applied`
   via WTTJ in-platform on 2026-07-16 (verified in WTTJ My Applications list). The
   in-platform path demonstrably WORKS.

## Corrected method when a prior "ceiling" note exists
Do NOT treat the note as the universe. For each sizing pass:
1. **Re-source EVERY configured board.** `python3 scripts/audit_board.py <board>` for
   each board row in `searches.csv`. The note's board list is NOT the universe — a
   board it didn't mention may hold the only fresh on-lane role.
2. **Re-verify each claimed wall LIVE with the shipped driver** before crediting it:
   - WTTJ in-platform vs external-only → `python3 sites/welcometothejungle/scripts/apply.py start "<url>"`. Authoritative. Prints `EXTERNAL-ONLY` or fills in-platform. (A note saying "WTTJ is a wall" is overridden by a live `Apply with your profile` modal.)
   - Guardian in-platform → `apply.py` fills + uploads + opts-out but Send fires an unpassable reCAPTCHA v2 grid for this camofox fingerprint → human VNC gate (`references/guardian-board-reality.md`), NOT a bot-solvable wall.
   - CSJ TAL → WCN-hform drift, no driver (`references/csj-wcn-hform-drift.md`).
3. **Re-read `python3 sites/_common/scripts/tracker_stats.py --count` fresh** — never reuse a note's number.
4. **Only THEN state a ceiling** — after a fresh full harvest + a real live drive attempt on every on-lane candidate. The re-drive guard in `references/redrive-destroys-applied-row.md` still applies: don't downgrade an `Applied`/`Skipped` row.

## Concrete recipes that emerged this session
- `audit_board.py <board>` output is **PLAIN TEXT, NOT JSON** (leading non-JSON
  header line like `audit <board> — N families · M sourced · K unique`). Parse the
  line `FRESH (on-profile, NOT yet applied): N  |  already TRACKED: …`; do NOT
  `json.load` the file (it raises).
- **gh_apply.py auto-logs `Blocked` on ANY submit bounce** — including an off-lane
  role. Read the JD location FIRST: a US-onsite role with no visa sponsorship (Jane
  has none) is a hard Step-1 `Skipped`, never driver-invoked. The Echo Neurotechnologies
  `Interaction Designer` (San Francisco onsite) was driven, bounced on an empty
  `Country` field, and wrongly logged `Blocked` — corrected to `Skipped` via
  read-mutate-write. **Enforce the location screen before calling the driver.**
- **NHS has NO shipped apply driver.** "Apply" routes to the trust's own ATS
  (Jobtrain / Trac / Oleeo), each a separate account — account-gated, loop-undrivable.
  Log `Skipped` (no driver) or `Blocked` (account wall), never `Applied`.
- WTTJ in-platform is the FASTEST real channel (no PDF, no reCAPTCHA) — prefer it over
  external ATS whenever `apply.py start` reports in-platform. loveholidays proved it.
