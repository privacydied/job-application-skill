# Feature roadmap — inventory, hardening, async, matching (post-perf-roadmap)

Successor to `perf-roadmap.md` (all three of its passes are LANDED). That roadmap
optimized turns/tokens/round-trips. First-principles re-read of the cost model against
the SKILL.md scar record says the binding constraints are now different:

1. **Inventory ceiling** — data scarcity + downstream employer-ATS account walls end
   every volume run, not tooling speed.
2. **Contamination class** — a degraded camofox backend mints false terminal verdicts
   ("exhausted"/"blocked"/"external-route") that cost whole sessions (2026-07-16: +35
   applications recovered only after manual re-verification).
3. **Human-unblock latency** — every wall (login/CAPTCHA/account) serializes the human
   into the loop; parked work has no structured resume path.
4. **Outcome blindness** — apply_rank optimizes submit-rate; the objective is
   interviews. No signal flows back from responses.
5. **Scar re-inflation** — each incident adds ⛔ prose to SKILL.md; the context diet
   erodes one scar at a time.

Guiding rules (same as before, plus one): the model belongs only at judgment points;
**and any rule that CAN be an assertion in code MUST NOT remain prose** — a scar
paragraph is a bug report against a tool that still permits the mistake.

---

## Tier H — hardening (kill the false-verdict + data-loss classes)

- [ ] **H.1 Health-fingerprinted verdicts (the contamination fix, in code).**
      `cfx.py health-fingerprint` → `{browserConnected, blank_render_probe,
      title_len, innerText_len, ts}` on a known-good control URL. EVERY terminal
      negative (`NO_APPLY_BUTTON`, `STUCK`, `wedge`, board "0 fresh", `Blocked`)
      gets stamped with the fingerprint at verdict time. A verdict recorded while
      degraded is written as `suspect=true` and auto-enqueued to a
      `revalidate.jsonl`; a post-recovery pass re-tests suspects before they are
      ever reported or dismissed. This turns the entire ⚠️ CONTAMINATION META-RULE
      paragraph into an invariant the driver enforces — then delete the paragraph.
- [ ] **H.2 Nightly proof audit + strict-count as the ONLY reporting path.**
      `scripts/audit_proofs.py`: every `Applied` row must cite a `--proof` file that
      exists and is non-trivial (>1KB png / non-empty txt); violators auto-demote to
      `Applied?` with a note. `tracker_stats.py` (or `log-application.py --stats`)
      prints the strict-parse count; docs stop describing the grep-vs-strict trap and
      instead say "run the tool". Closes the 269-vs-267 class permanently.
- [ ] **H.3 Tracker primary key = canonical URL/jcode.** `log-application.py`
      matches on (Company, Role) → the documented silent-merge collision. Re-key
      matching on `canon_ids(url)` first, (company, role) as fallback-with-warning.
      Deletes the DEDUP-COLLISION pitfall paragraph.
- [ ] **H.4 One `state.db` (SQLite, WAL) for all shared state.** tracker, queue,
      cooldowns, yields, apply-stats, screener bank, salary/company caches are 8
      CSV/JSONL files + a lock-file zoo, each with its own truncate-on-throw scar.
      One SQLite DB gives transactions (kills the whole Tier-A lock apparatus and the
      `open('w')` data-loss class), cross-table queries ("blocked rows by ATS with
      proof missing"), and history. CSVs become generated read-only exports for human
      eyes. Migration: table-at-a-time behind the existing module APIs
      (`board_cooldown.py`, `apply_stats.py`, … keep their signatures).
- [ ] **H.5 State auto-snapshot.** `searches.csv` is untracked with NO backup and was
      already corrupted-and-rebuilt once. Cron job: timestamped copies of
      searches.csv + tracker + screener bank to `state-backups/` (rotate 14 days) +
      auto-`git commit` of the tracker. One-liner-cheap, whole-class insurance.
- [ ] **H.6 Nightly canary.** `scripts/canary.py`: open fresh tab → explicit nav to a
      stable page → assert innerText>0 → fill a known form (e.g. a saved local HTML
      fixture through atsform) → write `canary-status.json`. Detects backend/selector
      rot BEFORE a live run burns passes misdiagnosing it. Preflight reads the file.
- [ ] **H.7 Doc/config linter `scripts/doctor.py`** (pre-commit + preflight-cheap):
      every `python3 <path>` referenced in SKILL.md/references/NOTES resolves to an
      existing file (the AGENTS.md drift class, automated); CAPTCHA-policy mirror
      audit (the grep in maintaining-this-skill.md, executable); `searches.csv`
      format check (no `N|` prefixes, parseable, reed URL pattern
      `-jobs-in-<loc>`); `*.example.json` shape matches its real gitignored twin.
- [ ] **H.8 Per-posting apply journal (crash-resume + double-submit guard).**
      Drivers append step events (`opened`, `filled`, `uploaded`, `submitted`,
      `confirmed`) to `applications/<slug>/journal.jsonl`. On re-entry: journal says
      `submitted` without `confirmed` → go verify, never re-fill; mid-fill wedge →
      resume at the recorded step. Makes the attempt-cap rule enforceable in code.

## Tier N — asynchronous (take the human and the browser off the critical path)

- [ ] **N.1 Keyless HTTP sourcing sentinel (browser-free, cron).** The HTTP-API
      feeds (adzuna, reedapi, atsdirect, himalayas, jooble/careerjet where keyed)
      need no tab. A cron `scripts/sentinel.py` polls them every few hours through
      `pipeline.run(only_boards=<http-only>)` into the standing inventory — sourcing
      happens continuously in the background; the browser tab is reserved for
      APPLYING. Fresh-posting latency drops from "next run" to "next poll" (early
      applications convert measurably better).
- [ ] **N.2 Unattended code-only drain (extend warm_queue → apply).** The daemon
      currently only keeps the queue warm. Extend: within caps, drain rows whose
      whole path is code-only — `reed-easyapply` (86% submit rate, zero model
      judgment) and EA rows whose screeners are 100% covered by the answer bank.
      Rows needing judgment (novel screeners, essays, borderline titles) are left
      tagged `needs_model`. CAPTCHA policy unchanged: any non-sanctioned CAPTCHA →
      daemon halts drain + notifies, exactly like the loop. A model session then
      becomes: read exceptions bundle → write creative content → answer new
      screeners → done.
- [ ] **N.3 Blocker inbox + push notify + parked-resume.** Structured
      `blockers.jsonl` (site, url, kind: login/captcha/account/sms, what-to-do, VNC
      link, parked application slug) + a push notification at write time. Human
      clears it whenever, marks resolved (`blockers.py resolve <id>`); the next
      firing/daemon pass auto-resumes the PARKED application from its H.8 journal
      instead of relying on the model remembering. Converts human latency from
      serial (loop waits) to parallel (loop continues elsewhere; unblock applied on
      arrival). CAPTCHA keeps its hard-halt semantics — the inbox is the *resume*
      mechanism, not a license to continue past it.
- [ ] **N.4 Account-provisioning queue (attacks the REAL ceiling).**
      `accounts-needed.csv`: every time a run hits a downstream account wall
      (amazon.jobs, CVLibrary, TotalJobs, MoJ, …) it increments that ATS/board row
      with the count + est. blocked inventory. Ranked view answers "which ONE
      account-creation session unlocks the most applications". Human does a batch
      account session (with SMS/email verification where needed) → creds land in
      `ats-credentials.csv` → `triage_blocked.py` already re-queues the blocked rows.
      This is the single highest-leverage feature in this file: every volume saga
      in SKILL.md ends at this wall.
- [ ] **N.5 Email-alert ingestion (push-style sourcing + free dedup).** Register
      each board's native job-alert emails once (they all have them), point them at
      a dedicated address/label, and a cron IMAP parser turns alert emails into
      feed-shaped rows for the funnel. Zero browser cost, zero cooldown burn, and
      postings arrive at publication time. Same parser handles N.6/M.3 inbound.

## Tier M — matching (rank by expected VALUE, learn from outcomes)

- [ ] **M.1 Fit-score ranking.** Local embedding (small sentence-transformers model,
      CPU, code-only) of JD text vs the applicant profile + per-family base
      summaries → `fit_score` per queue row. Order the queue by
      `fit_score × apply_rank` (expected interviews/minute, not submits/minute).
      When a run is time-boxed (they all are), the best-fit roles get applied FIRST
      instead of merely the easiest-ATS ones.
- [ ] **M.2 Cross-board duplicate fingerprint.** `canon_ids` dedups URL variants,
      not the same vacancy on two boards (Reed + Adzuna + LinkedIn each mint their
      own id). Add a fuzzy fingerprint in `merge_sources`:
      (normalized company, normalized title, location bucket, salary band) → same
      vacancy sourced twice collapses to one row, and the tracker check catches
      "already applied via the other board". Real double-apply risk today.
- [ ] **M.3 Outcome feedback loop (change the objective function).** Parse response
      emails (N.5 infra): rejection / assessment / interview invitations →
      auto-update tracker Status + timestamp. Aggregate per family/board/ATS
      conversion into `outcome-stats` → feed back into search ordering and M.1
      weights. Sourcing effort migrates toward what generates interviews. Also
      kills manual tracker status upkeep.
- [ ] **M.4 Screener triage coalescer.** Formalize the manual recipe:
      `screener.py triage <drain.log…>` aggregates every `BLOCKED_UNANSWERED_
      REQUIRED` across logs, dedups, classifies (consent/location = teachable;
      eligibility = never-teach, per the anti-fabrication rule), and emits ONE
      worksheet. Model answers it in ONE turn; `screener.py teach-batch
      <worksheet>` bulk-learns; re-drain harvests. Today this is a prose recipe
      re-derived per session.

## Tier X — context diet, round 2 (docs as data, scars as code)

- [ ] **X.1 Scar-to-code migration (standing policy, not a one-off).** For each ⛔
      paragraph in SKILL.md, ask "can a tool make this mistake impossible?" —
      if yes, move it into the tool and DELETE the paragraph. Ready examples:
      open-tab auto-nav failure → `cfx.py nav` (and a new `goto` that wraps
      open-tab+nav+verify `innerText>0`, retry once) makes the failure
      unreachable; the `.jobenv.persist` clobber → a `cfx.sh persist-env` subcommand
      that always writes both vars; Reed URL-format bug → feed.py validates the h1
      against the unfiltered-pull signature and refuses. Success metric: SKILL.md
      byte count DECREASES after each incident instead of growing.
- [ ] **X.2 `scripts/brief.py` — per-task context compiler.** Input: intent
      (`apply reed`, `source csj`, `triage blocked`). Output: a ~2k-token briefing —
      the relevant manifest rows, the target board's NOTES quirks, and LIVE state
      (queue depth by ats_hint, active cooldowns, session/canary health, today's
      strict count). A firing reads the briefing, not the corpus. SKILL.md shrinks
      toward: identity, hard rules (CAPTCHA/integrity/PII), decision tree,
      "run brief.py".
- [ ] **X.3 Quirks as structured data.** Board quirks from NOTES.md →
      `sites/<board>/quirks.jsonl` (`{symptom, cause, fix, verified, expires?}`).
      Drivers self-serve (e.g. atsform consults quirks for the board before
      filling); `doctor.py` flags entries past their verified-date for re-check;
      NOTES.md becomes a generated human view. Staleness gets a date instead of a
      vibe — directly serves the "verify live, never trust stale notes" rule.
- [ ] **X.4 `status.json` session dashboard.** The daemon maintains one file:
      queue depth, per-board cooldown/level, session-login health (from a
      keepalive probe), canary verdict, strict Applied count today/total, open
      blockers. Session start = ONE read instead of a dozen probes; also the
      artifact a human glances at between sessions.

## Tier P — new platforms (boards only — NO new ATS drivers)

Selection criteria, in order: (1) keyless JSON/RSS API (browser-free → N.1
sentinel-compatible), (2) native quick-apply (no downstream account wall), (3)
London/remote junior-mid inventory in Jane's families.

- [ ] **P.1 Remotive** — public keyless JSON API (`remotive.com/api/remote-jobs`),
      remote-only inventory, design/product/support categories. Pure `httpfeed.py`
      adapter, no browser. Apply paths vary (many direct-email/external) — source
      first, rank the applyable subset.
- [ ] **P.2 Jobicy** — public keyless JSON API (`jobicy.com/api/v2/remote-jobs`),
      same shape of win as Remotive. Trivial adapter.
- [ ] **P.3 HN "Who is hiring"** — monthly thread via the keyless Algolia HN API;
      parse top-level comments for REMOTE/London + family keywords. Small, fresh,
      high-signal startup inventory the aggregators never carry. Apply = email
      (fits N.5 outbound) or a company careers link (routes to atsdirect logic).
- [ ] **P.4 Wellfound (ex-AngelList)** — already name-checked in SKILL.md rotation
      but has no feed. Startup UX/product inventory; login-gated (account needed →
      goes through N.4 queue), quick-apply in-platform once logged in.
- [ ] **P.5 Alert-email meta-channel** — not a board but a platform surface: N.5
      turns EVERY existing board's alert emails into a push feed, including boards
      whose search UIs are hostile (TotalJobs, CVLibrary) — sourcing without
      touching their anti-bot surface at all.

## Suggested order (leverage ÷ effort)

1. **N.4 account queue + H.5 snapshots + H.2 proof audit** — tiny builds; N.4
   attacks the actual ceiling, H.5/H.2 are one-evening insurance on known scars.
2. **H.1 health-fingerprinted verdicts** — kills the wasted-session class with one
   primitive every driver stamps.
3. **N.1 HTTP sentinel + P.1/P.2/P.3 keyless boards** — inventory growth with zero
   browser cost; all ride the existing `httpfeed.py`/pipeline plumbing.
4. **N.2 unattended drain + N.3 blocker inbox (+H.8 journal as its substrate)** —
   the async core: submissions accrue while no session is running; human unblocks
   land asynchronously.
5. **M.4 screener coalescer, M.2 cross-board fingerprint** — cheap correctness +
   turn wins inside the existing drain loop.
6. **M.1/M.3 fit-score + outcome loop** — changes what the machine optimizes;
   needs N.5's email infra, so it lands after.
7. **H.4 SQLite migration + X.1–X.4 context round 2** — structural; do
   table-at-a-time / scar-at-a-time in quiet periods, not mid-volume-run.

Everything here obeys the standing hard rules: CAPTCHA policy semantics unchanged
(N.2/N.3 halt-and-notify, never bypass), integrity/no-fabrication untouched (M.4
never teaches eligibility gates), PII config-routing untouched (new state lives in
gitignored files; run `check-no-pii.sh` before any push).

---

## Status (2026-07-17) — all tiers implemented + tested

Every item above is landed, unit-tested, and integrated. Test suite: 182 core + 28
feature = **210 green**; every new file `py_compile`s; `doctor.py` 0 FAIL/0 WARN;
`check-no-pii.sh` ✓. Files added/changed:

- **H.1** `verdicts.py` + `cfx.health_fingerprint()`/`cfx.py health-fingerprint` — every
  terminal negative stamps a backend-health fingerprint; degraded/blank-render verdicts
  quarantine to `revalidate.jsonl` for post-recovery re-test.
- **H.2** `tracker_stats.py` (strict count is the reporting path) + `scripts/audit_proofs.py`
  (Applied ⇒ real proof artifact; `cites_missing` vs `no_evidence` classes; `--fix`/`--fix-all`).
- **H.3** `log-application.py` two-pass match (`find_match_typed`): canonical URL id across
  ALL rows before any (company,role) fallback; refuses a blind pair-merge when a
  non-matching URL is supplied (the DEDUP-COLLISION guard).
- **H.4** `statedb.py` — SQLite(WAL) mirror of all state + `import-csvs`/`export`/`query`;
  additive layer (CSV writers stay source-of-truth; migrate table-at-a-time).
- **H.5** `scripts/snapshot_state.py` — timestamped state backups + rotation.
- **H.6** `scripts/canary.py` — health + render + click + (`--full`) atsform-fill smoke test
  → `canary-status.json`.
- **H.7** `scripts/doctor.py` — path/feeds/searches/captcha-mirror/examples/quirks linter
  (already caught + fixed 2 real stale doc references this build).
- **H.8** `journal.py` — per-posting `applications/<slug>/journal.jsonl` (crash-resume,
  double-submit guard, attempt-cap counter).
- **N.1** `scripts/sentinel.py` — browser-free continuous sourcing over keyless HTTP feeds.
- **N.2** `scripts/autodrain.py` — unattended code-only drain (Reed + covered-EA), dry-run
  default, self-gating, CAPTCHA-halt via blockers (policy unchanged).
- **N.3** `blockers.py` — structured blocker inbox + push-notify + `resumable()` (built on H.8).
- **N.5** `scripts/email_ingest.py` — IMAP → sourcing rows (`alerts`) + outcome events (`responses`).
- **M.1** `fit_score.py` — lexical (embedding-optional) JD↔profile fit; pipeline orders by
  `apply_rank − 2·fit`.
- **M.2** `merge_sources.fingerprint`/`cross_board` — same vacancy across boards collapses
  to one row (`_dup_urls` preserved); pipeline enables it.
- **M.3** `outcomes.py` — response events → tracker Status (forward-only) + `outcome-stats.csv`.
- **M.4** `screener.py triage`/`teach-batch` + `classify_question` (never-teach eligibility guard).
- **X.1** `cfx.goto` (verify-render) + `cfx.py persist-env` + Reed unfiltered-h1 guard;
  fixed the 2 stale doc paths doctor found.
- **X.2** `scripts/brief.py` — per-task briefing (manifest rows + board quirks + live state).
- **X.3** `quirks.py` + `sites/{reed.co.uk,civilservicejobs}/quirks.jsonl` (seed).
- **X.4** `state_view.py` + `scripts/status_dashboard.py` → `status.json`.
- **P.1/P.2/P.3** `sites/{remotive.com,jobicy.com,news.ycombinator.com}/scripts/feed.py`
  (keyless JSON/Algolia); **P.4** `sites/wellfound.com/scripts/feed.py` (records the account
  wall to N.4); **P.5** = N.5 email meta-channel. All registered in `pipeline.FEEDS` +
  `searches.csv`.
- Shared: `accounts.py` (N.4). New generated run-state added to `.gitignore`.

Deliberately scoped, not skipped: H.4 is the DB foundation + two-way sync, not a rip-out of
the working CSV writers (cut over table-at-a-time in a quiet period, per the tier note); the
live drivers keep their atomic-locked CSV writes until then. N.5/M.3 IMAP paths degrade
gracefully without an `imap.*` creds row (their pure classifiers are unit-tested). The M.1
embedding backend is optional (lexical default) because this host has no ML stack.
