# Audit ledger — job-application skill (audit-loop state)

Read this FIRST every firing; pick up from `Next`. Update at the end. A finding too big
for one firing goes to `Open findings` with enough detail that a cold firing executes it
without re-deriving. Budget: ≤2 bugs + ≤3 docs + ≤2 perf items per firing.

## Swept (subsystem — date — verdict)
- `/tmp/*.py` promotion audit — 2026-07-15 — user flagged 2 scaffolding scripts as "genuine
  gaps". Verdict after reading both vs shipped code: **`gen_queries.py` PROMOTED** (commit
  5ed972d) as `scripts/gen_queries.py` — closes the manual "break cooldown w/ NEW query URLs"
  recipe (apply-mechanics §Volume) with a tool; +manifest row +3 tests. **`source_all.py`
  REJECTED** — its multi-board sourcing duplicates `pipeline.py` (source→screen funnel),
  it re-implements `cfx.list_tabs`/`open_tab` in raw urllib (divergent-reimpl anti-pattern),
  and line 57 has an operator-precedence bug (`"ERROR" in x and "410" in x or "500"...`). If
  aggressive tab-heal is ever wanted, the RIGHT change is ~5 lines in `pipeline.run_feed`
  (reopen tab via `cfx.ensure_tab` on 410/500), NOT promoting the throwaway. Do NOT re-promote.
- `check_title` title eligibility — 2026-07-15 — naive-match: industrial-`design engineer`
  discipline leak fixed (prior) + `TestNoDivergentTitleScreen` build-guard.
- `precheck.screen_location` — 2026-07-15 — naive-match: `"london" in low` leak fixed.
- contract-drift from this session's refactors — 2026-07-15 — dead `_field_exists` removed;
  pipeline.main callers / run_pass refs / test-stub coverage clean.
- `rotation-recovery-2026-07-15.md` — 2026-07-15 — DOC: compressed 5010→3151 B (−37%),
  guardrails intact; framing corrected to current code (see §C finding below).
- `external-ats-react-select-techniques.md` — 2026-07-15 — DOC: 9856→7042 B (−28.6%); all
  10 code fences + every selector/command kept, cut dated narration + verbose Hiresome
  replay + §3/§9 and §7/§8 overlap. (firing 5, done while baseline red from searches.csv.)
- `sites/myworkdayjobs/NOTES.md` — 2026-07-15 — DOC: 14347→7250 B (−49.5%); cut incident
  narration (Lloyds date-revert saga, specific-posting log) — kept all 17 selectors/snippets
  (nav_to_link, getElementById+blur recipe, inline-error JS, formField-source/
  candidateIsPreviousWorker, pageFooterNextButton, beecatcher honeypot) + both fences + the
  ⛔ don't-submit-wrong-dates rule. (firing 6, baseline still red from searches.csv.)
- `sites/welcometothejungle/NOTES.md` — 2026-07-15 — DOC: 15038→7666 B (−49%); cut the
  /jobs-auto-open investigation proof, marketing-dead-end blocker detail, and test-posting
  log — kept the ⛔ infinite-loop rules, feed.py/theme sources, apply.py+opts/pick/set_textarea
  driver + all gotchas, react-select selectors, "We're rooting for you!" signal. (firing 7.)
- dedup date-independence — 2026-07-15 — verified `precheck.load_tracker` reads ALL rows,
  so the §C midnight double-apply trap is NOT live (guardrail satisfied).
- `jd.py` location_signals — 2026-07-15 — naive-match: `"london" in low` (line 180) flagged
  "Londonderry"/"New London" as london=True (skipping pipeline's review→drop); the cities on
  line 184 were already word-bounded, only london was bare. Fixed to `(?<!new )\blondon\b`
  (mirrors precheck.screen_location); test TestJdLocationSignal. (firing 14 — 5th naive-match.)
- `screener._matches` false-cognate class — 2026-07-15 — naive `p in q` substring let a
  short plain pattern embed as a word-SUFFIX: `"city"`→"ethni**city**" (a demographic
  ethnicity question got answered "London"), `"location"`→"re**location**", `"gender"`→
  "trans**gender**". Fixed with a LEADING word boundary (kills suffix-embeds, keeps
  plural/stem like "pronoun"→"pronouns"). Applies to CSV + seed patterns. (firing 12)
- contract-drift (other scripts) — 2026-07-15 — CLEAN: `check_login` exits (11 wall / 1
  ambiguous / 0 ok / 2 bad-input) match its docstring; the feed scripts' documented
  `--nav/--all/--force/--pages/--all-pages` flags all exist. (apply_queue was the one real
  drift, fixed prior firing.)
- divergent-reimpl (feed dedup) — 2026-07-15 — FOUND, logged (see Open findings): 5 site
  feeds each roll their own `load_seen_*` tracker-dedup scan.
- `sites/ashbyhq/NOTES.md` — 2026-07-15 — DOC: 9634→5755 B (−40%); cut first-run narration +
  set-toggle incident replay + the "JS-click not camofox" rule (3×→1×) — kept the ashby.py
  command list, the toggle JS snippet, `_systemfield_resume` id-targeting, colour-verify
  `rgb(3,116,218)`, set-toggle fail-loud, invisible-reCAPTCHA, all ⚠️ rules. (firing 18)
- contract-drift class — 2026-07-15 — found+fixed: `scripts/apply_queue.py` docstring listed
  `9 no-tab` but main() never returned 9 (both tab-death paths `break`→`return 0`). Realized
  the documented intent: return 9 on tab-death (heal_tab fail OR apply_ea rc=9) + `tab_dead`
  in the tally. test TestApplyQueueExit. (Also checked: pipeline exit codes match docstring;
  atsform's `_field_exists` mentions are accurate "removed" historical comments, not drift.)
- silent-truncation/caps class — 2026-07-15 — found+fixed: `pipeline.run` `screen_limit=40`
  queued survivors past the cap UNSCREENED (jd=None) but the summary never reported it →
  looked "screened everything". Now `counts.screen_capped` + a `screen_skipped` marker on the
  queue row + a stderr ⚠️. test TestPipelineScreenCap. (`jd.compact reqs[:20]` noted LOW —
  intended token diet, full payload cached on disk.) (firing 16)
- fixed-sleeps-racing-async-DOM class — 2026-07-15 — CLEAN: remaining `time.sleep`s in the
  engine are legit (anti-detect pacing, tab-open backoff, cookie-banner teardown, my B.3
  poll-graces). `check_login.py:110` 2.5s SPA-settle noted LOW — no clean poll predicate
  (login can legitimately be logged-out, so polling for "definitive" regresses the common
  guest case to a full timeout).
- `sites/indeed.com/NOTES.md` — 2026-07-15 — DOC: 19537→7620 B (−61%); cut heavy incident
  narration (company names/dates/root-cause musings) + consolidated the "verify every click"
  theme (stated 4×→once) — kept every selector/snippet/endpoint (load_seen_jks, upload
  input[type=file], relevant-experience native setter, apply-preview iframe coords, native
  Submit click, recaptcha frameSelector, feed.py hide aria-label) + all ⛔/⚠️ rules. (firing 15)
- swallowed-failures class — 2026-07-15 — CLEAN: no bare `except:` anywhere; every broad
  `except Exception` is advisory with a backstop (apply_stats date-format, board_cooldown
  URL-parse, tailor wrong-company set which re-runs authoritatively at submit); fsutil's
  `except BaseException` correctly re-raises after tmp cleanup; log/write errors surface
  (log-application returns 2, apply_stats returns False).

## Open findings (file:line — class — symptom — fix)
- ✅✅ **RESOLVED at the ROOT (firing 19) — `searches.csv` cooldown-key drift (the whole
  saga).** Root cause: preflight (`search_plan.plan`) derived the cooldown key from the `query`
  COLUMN while the linkedin/indeed feeds mark under `query_from_url(nav)` — so a column that
  drifted (the ` (Easy Apply)` label, then CSV-quoting corruption that grew 6→12 rows) made
  preflight check a different key than the feed marked → silent re-sourcing. FIXED by deriving
  preflight's key as `query_from_url(nav) or column` — ALWAYS the same source the feed uses;
  the column is now purely documentary and its formatting is irrelevant to cooldown. Baseline
  GREEN (88 pass) for the first time since firing 4. (Superseded firing-9's partial norm()
  strip — that stays as a harmless extra safety.) NOTE: the concurrent track's searches.csv
  still has ~12 malformed-CSV query columns — now COSMETIC (only affects human readability of
  that column); the user MAY want to re-quote them for legibility but nothing breaks.
- **write-sweep (firing 4, partial):** `company_cache.py:69` rewrites `company-cache.csv`
  with an unlocked `open(,"w")` (lost-update/torn-read if daemon+loop both put) — route
  via `fsutil.file_lock`+`atomic_write` when baseline is green. `stagetimer.record:110`
  appends `run-timings.csv` unlocked (LOW: gitignored profiling; fold into the same helper
  if touched). Everything else is `.tmp`+`os.replace` atomic, single-writer/CLI, or
  per-application output (clean); Tier-A writers (queue/cooldown/apply-stats/tracker/
  screener record) already route through fsutil.
- `search_plan.applied_today:~94` — design, LOW priority — the per-DAY target counter is
  today-scoped, so a session spanning midnight resets it (could over-apply 10+10). Not a
  bug (dedup still prevents double-apply); flag only if a per-RUN target is ever wanted.
- **divergent-reimpl — `load_seen_*` feed dedup (IN PROGRESS: 3/5 converted).** Shared
  `precheck.load_seen(pattern, tracker=None)` + tested (TestLoadSeen). Converted, each
  verified behavior-identical to its old inline scan: **hackney** (f20), **indeed** (f21, 41
  jks), **civilservicejobs** (f22, 11 ids; non-capturing group handled → strings not tuples).
  REMAINING 2: `welcometothejungle` (`load_seen_ids`) — SAFE (not concurrent); `linkedin`
  (`linkedin\.com/jobs/view/(\d+)`) LAST, only when its feed is confirmed not mid-use by the
  live session. Each: `from precheck import load_seen` + `return load_seen(<regex>,
  tracker=TRACKER)`, verify same-ids vs inline.
- `pipeline.family_of` — naive-match, LOW stakes (picks resume BASE, not a screen; a miss =
  slightly-off template, never a wrong application). Confirmed leak: key `"cro "` ⊂ `"macro "`
  → "Macro Analyst" would get the growth/CRO base. Also short keys `sre`/`seo`/`qa `/`uat `.
  Fix if ever touched: word-boundary the short keys. Not worth a firing on its own.
- Substring screens not yet swept for false cognates: `screener._matches` (`p in q` — does
  "commut" over-match "telecommute"?), `jd.py` location signals.

## Fixed (what — regression test)
- precheck `"london" in low` → `(?<!new )\blondon\b`; test
  `TestPrecheckLocation.test_london_substring_false_cognates_not_kept`. (commit ec987ab)
- removed dead `atsform._field_exists`. (commit ec987ab)
- doc: `rotation-recovery-2026-07-15.md` −37%. (commit 3213c9b)
- `precheck.salary_for` `"london"` substring → `(?<!new )\blondon\b` guard; test
  `test_salary_for_london_substring_guard`. (commit 2dc75b6)
- `board_cooldown.norm()` strips the cosmetic `(easy apply)` label so cooldown keys are
  robust to the searches.csv convention; test `test_norm_strips_easy_apply_label`. Drift
  18→6 (the rest is CSV corruption, above). 80 tests pass. (firing 9)

## Perf findings (firing 8 analysis → perf-roadmap "Third pass")
- ✅ G.1 `company_cache.put` unlocked rewrite → fsutil lock+atomic — DONE firing 10 (test
  TestCompanyCache). Landed on the 80→81-pass suite (residual red = the 6 corrupted rows,
  distinct/theirs) per the firing-9 precedent (ship verified improvements, don't hostage them
  to concurrent data corruption).
- ✅ G.2 `screener` memoize _rows (mtime) + lru_cache compiled patterns — DONE firing 11
  (test TestScreenerMemo). 82 pass.
- ✅ G.3 `board_cooldown` per-plan CSV re-parse — DONE firing 13: plan() read
  board-cooldown.csv per-search (50×); now parses each cooldown CSV once + threads rows into
  remaining_hours(rows=)/expected_yield(yield_rows=). Measured 50→1. test TestSearchPlanPerf.
- ✅ `screener._matches` false cognates — DONE firing 12 (leading word-boundary; test
  test_no_substring_false_cognates). Also verified `"commut"` is a `/regex/` pattern already
  (not the plain branch), and `"telecommute"` no longer over-matches.

## Next (single most suspicious target for the next firing)
- **Continue the `load_seen` refactor: convert `welcometothejungle`** (4/5) —
  `sites/welcometothejungle/scripts/feed.py` `load_seen_ids` → `load_seen(<its /jobs/<id>
  regex>, tracker=TRACKER)` + import; read its exact regex + the "URL-tail id it appends"
  comment first (wttj has a documented id-capture quirk), verify same-ids vs inline + suite.
  Then `linkedin` (5/5) LAST — confirm its feed isn't mid-use by the live session
  (activeSessions/git) before touching it.
- Otherwise continue the rotation below (diminishing returns; prefer honest clean verdicts).
- The full bug-class rotation has now been swept once (divergent-reimpl, naive-match ×5,
  unlocked-writes, swallowed-failures[clean], fixed-sleeps[clean], silent-caps, contract-drift)
  + all 3 perf items + 6 doc compressions. Diminishing returns on easy wins. Options, in order:
  (a) if the 6 searches.csv rows got re-quoted → fully green → the `load_seen` refactor becomes
  safe (one feed at a time, per-feed test); (b) a second-pass naive-match/contract sweep on
  files not yet read (the site `apply.py`/`ashby.py`/`easyapply.py` drivers — but easyapply is
  concurrent-live, avoid); (c) more DOC compression (`sites/linkedin/NOTES.md` 13K if not
  concurrent-touched, the mid-size references). Prefer a genuine `clean` verdict over
  manufactured churn — report honestly when a class is clean.
- Baseline: the 6 corrupted searches.csv rows remain the only red. If green: land the deferred write-sweep fix — route `company_cache.py`
  put through `fsutil.file_lock`+`atomic_write` (+ optional stagetimer run-timings lock),
  with a test. If still red: another DOC firing (doc audit is independent of the code suite)
  — if still red, VARY from docs: do a **PERF-ANALYSIS pass** (reading code + logging findings
  to perf-roadmap needs no green suite): sweep `screener.py`/`jd.py`/`company_cache.py` for
  uncoalesced per-iteration evaluates, growing files re-read whole, and unlocked writes; add
  each as a roadmap entry (file:line/win/risk) to IMPLEMENT once green. Else next doc target
  `sites/indeed.com/NOTES.md` (19.5K, biggest remaining safe). AVOID concurrent-touched docs
  (SKILL.md, apply-mechanics.md, camofox-backend-recovery.md, volume-driver-pitfalls.md,
  linkedin/easyapply-adjacent) + parser-sensitive target-roles.md + applicant-profile.md.
- **NOTE on the persistent red**: searches.csv drift is now 4 firings unfixed, blocking ALL
  code/perf firings (1-token-per-row fix, user asked to authorize; still awaiting). Loop is
  doc/analysis-only until the user authorizes or the concurrent track drops " (Easy Apply)".
- Then **PERF**: `stagetimer.py report` + screener/jd uncoalesced-evaluate sweep.
