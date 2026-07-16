# Performance roadmap — fewer turns, fewer tokens, overlapped lanes

Cost model: a firing spends (model turns × inference latency) + (instruction/payload
tokens re-read per firing) + (browser wall-clock, serialized on one tab) + (state
re-derivation). Hard floors we do NOT fight: the CAPTCHA policy, one-tab serialization,
anti-detect pacing. All wins come from turn/token collapse and lane overlap.
Guiding rule: **the model belongs only at judgment points** (borderline screening,
creative tailoring, novel screeners, blocker triage) — everything else is code.
Measured baselines (sparse): CSJ+Hackney source pass 54s; JD screen 4–9s;
cfx pacing 0.7–2.9s/action + 2–6s post-nav dwell; 27 active searches; ~30+ model
round-trips before the first form fill.

## Tier 0 — measure first
- [x] STAGETIMER on by default (disable with STAGETIMER=0); `stagetimer.py report`
      wired into loop-prompt §5 end-of-run summary. Re-prioritize after real data.

## Tier 1 — collapse model turns (small effort, biggest lever)
- [x] `pipeline.py`: ONE call = plan → all clear feeds (yield-ordered) → merge_sources
      → precheck → jd-screen survivors → write `queue.jsonl` → stdout only counts +
      path + `review` items. Feed JSON never enters model context. Shares verdict logic
      with preflight via `search_plan.py` (no mirrored policy).
- [x] Fold the daily-applied-target check into the checkpoint (verdict=DONE, exit 12)
      — lives in `search_plan.plan()`, surfaced by both loop-preflight.py and pipeline.py.
- [x] Batch step-10 dismissals: `linkedin/feed.py hide-batch <ids> [--nav <results>]`
      — one results-page visit dismisses all terminal cards (CARD_NOT_FOUND is a
      benign no-op, tracker-dedup still protects). SKILL.md step 10 amended.

## Tier 2 — model only at judgment points
- [x] Screener answer bank `screener-answers.csv` via `screener.py` (regex/substring
      patterns, specific-before-generic, learnable). apply_ea consults it before
      NEEDS_HUMAN and prints unknowns to `screener.py learn`. Seeded from
      applicant-profile (RTW/sponsorship/notice/relocation/pronouns/years-of-X/driving/
      clearance/demographics).
- [x] Per-family bases in `applications/_bases/<family>/` (11 families) DERIVED from
      `sites/_common/family-bases.json` via `tailor.py build-bases`. `tailor.py`
      applies the family summary swap before the per-posting subs (pipeline sets
      `family` per queue row); each base ships a cover slot-template with the family
      fit line.
- [x] `company_cache.py` + `company-cache.csv`: one hook fact per company, get/put,
      Ltd/Limited-normalized so recurring companies reuse the researched hook.

## Tier 3 — async / pipelining around the single tab
- [x] Warm-queue daemon: `scripts/warm_queue.py` (cron, code-only) runs pipeline
      (self-gating on SLEEP/DONE/HOLD; `--no-screen` default so it can't wade into a
      mid-apply CAPTCHA) and keeps queue.jsonl warm. Crontab line documented in-file.
- [x] CPU/browser overlap — MEASURED FINDING: negligible. Feeds are serialized on one
      tab (~50s each); precheck+merge are sub-second CPU, so threading them saves <2%
      and adds shared-CSV race risk. The real overlap that DOES pay — PDF render off the
      fill critical path — is already done in tailor.py's parallel `--render`.
- [x] BOUNDED 2-tab experiment tool: `scripts/twotab_probe.py` — guarded, self-closing,
      wedge-detecting, control-URLs-only by default. Delivers the measurement; does NOT
      flip the one-tab default (verdict → camofox notes, per its own instructions).
- [x] jd-cache TTL 6h → 24h keyed by CANONICAL id (`?trk=`/`?theme=` variants share
      one entry). JDs are static; closings caught at apply time.

## Tier 4 — token diet
- [x] SKILL.md split (CONSERVATIVE, done mid-loop-safe): extracted the deep per-ATS
      Easy-Apply gotchas, Ashby toggle recipe, Workday/Greenhouse upload gotchas, and
      the volume playbook to `references/apply-mechanics.md`, leaving slim inline
      pointers; wired the new tools (pipeline/screener/family/company/shot/hide-batch)
      in. Net size ~flat (more capability per byte) — a further ~15KB aggressive core
      was deliberately NOT attempted while a live loop depends on SKILL.md; the big
      per-firing token win comes from pipeline.py keeping feed JSON out of context.
- [x] Files-not-stdout: ENFORCED ARCHITECTURALLY by pipeline.py — it runs the feeds as
      subprocesses and returns only counts + queue path + review items, so raw feed JSON
      never enters model context. Direct feed calls remain a debug-only fallback.
- [x] `cfx.py shot [--selector css | --clip x,y,w,h]`: client-side (Pillow) region
      crop for the pre-submit vision gate (email/radios/CAPTCHA area) — no server change.
- [x] Compact jd payloads: `jd.compact()`, `jd.py --compact`, and `pipeline.py` stores
      compact in queue.jsonl. Full payload still cached on disk for a verbatim re-read.

## Tier 5 — scheduling intelligence
- [x] `search-yields.csv` + adaptive cooldowns (board_cooldown.py): 12h × 2^(dry-1),
      cap 72h; just-dried high-yield rows 6h. Feeds record yield every pass; preflight
      + pipeline order clear searches by expected yield.
- [x] Work list ordered by expected success/minute — pipeline computes `apply_rank`
      (ATS prior blended with apply-stats.csv) and sorts queue.jsonl. `apply_stats.py`
      records per-ATS attempt/submit; apply_ea.py writes it at its terminal outcome.
- [x] Nightly auto-triage: `scripts/triage_blocked.py` groups Blocked rows by inferred
      ATS and `--ats <name>`/`--all` emits them as a queue.jsonl-shaped retry list
      (doesn't mutate the tracker) for re-application after a driver fix.
- [x] Per-action-class pacing tiers (`human_pause(tier)`, `navigate(pace_tier=…)`,
      `CFX_PACE_TIER` env): full (default, unchanged) / light / none. Opt-in +
      env-forceable for A/B measurement; safe default keeps current anti-detect.

Target end-state: a 10-application run ≈ 4–6 model turns (plan / write-all-creative /
review-exceptions), ~8k instruction tokens, browser wall-clock hidden behind the
daemon, and every answered screener answered forever.

---

## Status (2026-07-15) — all tiers implemented

Every item above is [x] (or [x]-with-measured-finding). Landed across the session:
`pipeline.py` (+`search_plan.py`) collapses the sourcing→screening funnel to one call;
`board_cooldown.py` adaptive cooldowns + `search-yields.csv`; DONE verdict; jd 24h
canonical-id cache + `compact`; `screener.py` shared answer bank; 11 per-family bases
via `tailor.py build-bases`; `company_cache.py`; `cfx` region-crop `shot` + pacing
tiers; `apply_stats.py` feedback loop; `feed.py hide-batch`; `warm_queue.py`,
`triage_blocked.py`, `twotab_probe.py`; SKILL.md conservative split → apply-mechanics.md.
Test suite 73→ green throughout. Deliberately-bounded calls (documented above): CPU/
browser threading (negligible), an aggressive ~15KB SKILL.md core (risky mid-loop), and
the 2-tab default (probe-only until a verdict is recorded). Re-run STAGETIMER after a
week of live data to re-prioritize any second pass.

---

# Second pass (2026-07-15) — deep audit of the shipped engine

Cost model unchanged (turns + tokens + serialized browser wall-clock + state
re-derivation). This pass came out of a four-subsystem read (browser engine / sourcing
funnel / fill-tailor-render / orchestration-state) plus a root-cause analysis of *why*
duplicate code keeps appearing. Findings are code-grounded (file:line as read
2026-07-15; verify line drift before patching). Ranked into tiers by impact/effort.
Nothing here is done yet EXCEPT P0.1 (landed this session). Do the cheap high-impact
ones first; the browser-round-trip collapse is the biggest latency lever after turn
collapse.

## P0 — correctness/safety (do before more volume; one landed)

- [x] **P0.1 `check_title` industrial-`design engineer` false-cognate — LANDED.**
      `check_title.check_title()` did a naïve `phrase in title_l` substring match, so
      "Electrical / ICT / Mechanical / CAD / RF / Systems Design Engineer" all matched
      the Tier-A phrase "design engineer" → `eligible:true, seniority_flag:false` and
      `precheck` KEPT them. **This affected EVERY board** (linkedin/csj/hackney feeds
      attach `eligibility` via check_title; indeed/wttj/seek go through
      `precheck→check_title`), not just LinkedIn Easy Apply — applying to them violates
      "never pad the count with off-profile roles" and is real-world harm. Fix
      (`check_title.py`): `_industrial_design_engineer()` guard — a `design engineer`
      title carrying an industrial modifier (`_DESIGN_ENG_INDUSTRIAL`: electrical/ict/
      mechanical/cad/rf/structural/hvac/…) and NO UX/creative signal
      (`_DESIGN_ENG_UX_SIGNAL`) → `eligible:false, discipline_flag:true`. Bare "Design
      Engineer" (Tier A), "UX Design Engineer", Tier-C "field service engineer", and
      "IT/ICT Support" are untouched. `precheck.py` emits an accurate drop reason on
      `discipline_flag`. Regression tests added (`TestCheckTitle`). Widen the modifier
      list in ONE place (check_title) — never per-orchestrator.
- [ ] **P0.2 Add divergence tests (prevents the class of bug that caused P0.1).** A
      test that FAILS if any script under `sites/` or the repo root defines its own
      seniority/discipline/on-profile word list instead of importing `check_title`
      (grep the source tree for `SENIOR|OFF_WORD|ONPROFILE|discipline` outside
      check_title.py). This is what would have caught `run_pass.py`'s divergent — and
      by luck *more*-correct — filter before it masked the canonical leak.

## Root cause of code duplication (answers "why re-implement shipped tools?")

The maintainers already documented the anti-pattern (SKILL.md item 8;
`scratch-probes-and-capability-index.md`) and it still recurred → **docs describe the
rule but can't enforce it.** Actual drivers:
1. **Session amnesia + rediscovery cost** — each firing re-derives the toolset from
   prose; writing 20 lines of inline regex is cheaper *in-context* than locating and
   importing the canonical module. Writing beats searching when search is expensive.
2. **Discoverability doesn't scale** — 45 refs (~52k tok) + SKILL.md (14k tok) + 16
   NOTES (~29k tok); the right pointer exists but is one buried line, with no
   intent→tool index.
3. **No code-level single-source-of-truth enforcement** — `target-roles.md` is the SoT
   but nothing prevents a second title-screen; divergence is invisible until it harms.
4. **A parallel orchestrator forces re-implementation** — a driver written outside
   `pipeline.py` must re-source/re-filter/re-dedup, each bypassing a shipped impl.

Structural remedies (tracked as F-tier below): expose `pipeline.run()` importable;
retire bespoke orchestrators; add divergence tests; replace prose discoverability with
a machine-checkable **task→tool manifest** read first.

## Tier A — daemon↔loop concurrency/atomicity (HIGHEST; cheap; data-integrity)

The warm-queue daemon (cron) and a live firing run concurrently by design, sharing
CSV/JSONL state. None of the shared writers are lock-guarded; several aren't even
atomic. All of A is closed by ONE new primitive: a shared `locked_rmw(path)` helper
(flock on `path+".lock"` + `tempfile.mkstemp` in-dir + `os.replace`) that every writer
routes through. Introduce it once in `_common/scripts`, then:

- [ ] **A.1 `queue.jsonl` written non-atomically** (`pipeline.py:~328`, `open(out,"w")`
      streaming rows) → a firing that reads mid-write sees a truncated/empty queue and
      falsely concludes "no work". Fix: write `out+".tmp"` then `os.replace` (mirrors
      `board_cooldown.mark`). One-line, near-zero risk. **Do this first.**
- [ ] **A.2 `board-cooldown.csv` lost update** (`board_cooldown.py:~92-110` `mark`):
      atomic swap but unguarded read→modify→write; daemon and loop both mark → one
      overwrites the other's snapshot → a proven-dry board gets re-sourced at full
      browser cost (reopens the exact leak the module exists to close). Fix: flock the
      whole RMW; same for `record_yield`/`mark_adaptive`.
- [ ] **A.3 `apply-stats.csv` non-atomic + lost update** (`apply_stats.py:~69`,
      bare `open(,"w")`): concurrent drivers lose increments; worse, `pipeline._load_
      apply_stats` (`pipeline.py:~130`) can read a truncated file mid-write and silently
      degrade `apply_rank` to the static prior. Fix: tmp+`os.replace`+flock.
- [ ] **A.4 latent: `log-application.py` append vs full-rewrite race** (`:~161` vs
      `:~184`), `screener.record` TOCTOU (`screener.py:~159-166`), `search-yields`
      unguarded append + double-header (`board_cooldown.py:~173`), `stagetimer` markers
      keyed by stage-name only so daemon+loop collide (`stagetimer.py:~90`). All close
      with the same `locked_rmw` helper (+ PID in stagetimer marker filenames).

## Tier B — browser round-trip collapse (biggest LATENCY lever)

Every `cfx.evaluate`/`post`/`current_url`/`list_tabs` is a separate HTTP round-trip;
the un-paced read loops are where latency actually shows through the deliberate pacing.

- [ ] **B.1 `nav` spawns ~5 python3 interpreters of pure overhead** (`cfx.sh`:
      `jsonstr` `:~207` forked per string; `nav` `:~306` = `tab_current_url`(curl+py) →
      `compute_referer`(py) → `jsonstr`×3). On the Synology box cold-py startup ~50-100ms
      → ~250-500ms/nav of dead overhead NOT covered by `human_pause`. Fix: one
      `jsonbody()` helper that encodes the whole request body in a single python3; for
      `nav`, one py that reads the curl output, computes referer, and prints the final
      JSON. 3-5 spawns → 1. Largest single un-paced win; pure refactor.
- [ ] **B.2 coalesce the 2-evaluates-per-poll-iteration loops** (same pattern in 4
      hot loops): `cfx.click_and_follow` (`cfx.py:~831-888`, `current_url` + dialog
      probe → one evaluate returning `{href,dialog}`); `atsform._wait_change`
      (`atsform.py:~481-500`, `current_url`+innerText-len → one `{url,len}` evaluate,
      ~15 iters); `atsform.fill` (`:~114/127/140`, fold the idempotency `.value` read
      into `_resolve`); keep `list_tabs` separate (management API). Up to ~15
      round-trips saved per click/submit.
- [ ] **B.3 replace fixed sleeps with `cfx.poll`** where a predicate exists: `fill`
      `sleep(0.3)`+read → poll-until-value (`atsform.py:~140`); `submit` `sleep(3)` loop
      → 0.5-1s poll (`:~640`, saves up to ~2.5s/submit); `upload` `sleep(1.2)`+read →
      poll-on-`files[0].name` (`:~433`). Leave the `apply` post-upload autofill-settle
      `sleep(1.0)` (no clean predicate).
- [ ] **B.4 redundant `list_tabs()` in ensure/open/alive path** (`cfx.py`
      `ensure_tab:~357`→`is_tab_alive:~292`→`open_tab:~251` can hit list_tabs 3-4×;
      `open_tab:~266` snapshots `before` even on the happy path). Thread one tab-list
      through; defer the `before` snapshot to the fallback branch.
- [ ] **B.5 GET/DELETE-only bounded retry + optional keep-alive** (`cfx.py get:~484`):
      2-try/0.3s backoff on transient `socket.timeout`/`OSError` for idempotent reads
      ONLY (never POST — double-submit risk). Keep-alive (`http.client` persistent conn)
      is a smaller win (localhost handshake is cheap, pacing dominates) and touches the
      fragile restart-reset window — lower priority.

## Tier C — funnel redundancy (CPU/disk/memory + one correctness regression)

Items C.1-C.5 are one theme: the same feed cards and the same tracker/canonical-ids get
serialized, parsed, canonicalized, and tracker-matched 2-3× each.

- [ ] **C.1 skip the tmp feed round-trip** (`pipeline.py:~256-264`): `all_posts` (the
      run's biggest blob) is `json.dump`ed to `out+".feeds.json"` then read back +
      re-parsed by `merge_sources.load_postings`. Add `merge_sources.merge_lists(posts)`
      (factor the dedup loop) and pass the in-memory list; keep the file path for CLI.
      Removes a full serialize + full parse + disk I/O of the largest payload.
- [ ] **C.2 free `all_posts` before the long screen phase** (`pipeline.py:~245-254`,
      only later use is `len()` at `:~341`): capture `n_sourced=len(all_posts)` then
      `del all_posts` before the minutes-long sequential jd-screen loop — meaningfully
      lower peak RSS (hundreds of card dicts with unused feed fields).
- [ ] **C.3 `if c in reviews` is O(survivors×reviews) deep dict-eq** (`pipeline.py:~289`;
      cards now carry nested `jd`/salary/eligibility so each compare is a deep structural
      compare, and it's aliasing-fragile). Fix: `review_ids={id(x) for x in reviews}`;
      test `id(c) in review_ids` (or tag `entry["_bucket"]` in precheck).
- [ ] **C.4 tracker parsed 2-3×/run + a real regression** (`search_plan.applied_today`
      `:~127`; `merge(drop_tracked=True)` `pipeline.py:~260`; `precheck.load_tracker`
      `:~188`). `merge(drop_tracked=True)` drops ANY tracked posting *before* precheck can
      route a `Blocked` one to `review` ("retry only if cleared") → **the cleared-blocker
      retry path is silently lost.** Fix: drop `drop_tracked=True` from the pipeline
      merge; let `precheck` own all tracker logic (it already distinguishes Blocked→review
      from other→drop). One tracker parse instead of two, and the retry path restored.
- [ ] **C.5 `canon_ids(url)` recomputed 3×/survivor** (10-regex sweep in
      `merge_sources._keys:~133`, `precheck:~199`, `jd._cache_key:~259-266`). Compute once
      in merge, stash `post["_canon"]`; precheck + jd cache-key prefer it (also makes the
      jd cache key provably == the dedup key). Fallback-recompute keeps CLI paths working.
- [ ] **C.6 re-screen under-rendered SPA shells** (`pipeline.py:~285-295`): `jd.py`
      documents `jd_text_full_len<300` = un-rendered shell "re-run once", but the pipeline
      writes the thin payload to queue and counts it screened. Fix: if `full_len<300` and
      no error, `jd.screen_one(url, use_cache=False)` once more before compacting.
- [x] **C.7 one-shot retry on transient board failure** (`pipeline.py` `run_feed`): DONE.
      `run_feed` re-runs the feed ONCE when it errors AND `_tab_dead()` confirms the shared
      tab is gone, reopening via `cfx.ensure_tab`. Gating on tab-death (not error-type) means
      a timeout with a live tab never retries — bounds tab cost. Single-shot, read-only (no
      double-submit). Supersedes the throwaway `source_all.py` tab-heal.
- [ ] **C.8 (bounded) overlap merge/precheck + CSV loads under feed browser I/O**
      (`pipeline.py:~246-267` runs feeds→merge→precheck strictly serial). Non-browser
      work can run in a background worker as each feed returns. Honest caveat: hidden
      work is ms vs seconds/feed of tab time → modest latency win, mostly architecture.

## Tier D — PDF render (deterministic wall-clock, off critical path but ×N)

- [ ] **D.1 fill-as-you-drain instead of batch barrier** (`prerender-pdfs.sh:~54-61`:
      launch JOBS, `wait` for the whole batch before the next). One slow render idles the
      other slots. Fix: `wait -n` work-queue keeping all JOBS slots saturated →
      `~total/JOBS` instead of `ceil(N/JOBS)*max`.
- [ ] **D.2 `networkidle`→`load`+`document.fonts.ready`** (`make-pdf.sh:~68`): the
      resume is self-contained (inline CSS, no fetches) so `networkidle`'s 500ms silence
      is pure dead wait ×N. `load` + explicit font-ready waits for exactly what matters.
- [ ] **D.3 skip the redundant per-child version check** (`prerender` pre-warms the
      install `:~33-39`, `make-pdf` re-runs `cat|sed|head` on each of N `:~37-43`): pass
      `PW_SKIP_VER_CHECK=1` from prerender. Small.
- [ ] **D.4 (bigger bet) single Playwright connection + page pool** (`make-pdf.sh` opens
      its own node + http.server + `chromium.connect` per dir): one node renderer, one
      connect, a `page` per dir with an internal limiter → removes N-1 connects/startups
      and naturally subsumes D.1. Higher effort/risk (per-page try/catch so one crash
      doesn't abort the batch); only if PDF is a measured bottleneck.

## Tier E — token/context diet (per-turn re-read cost)

- [ ] **E.1 suppress clean-path per-field prints in `atsform apply`** (primitives
      `print` unconditionally — `fill:~132/150`, `select:~182/284/309`, `set_radio:~379`,
      `set_checkbox:~402`, `upload:~439`; `_run:~767` doesn't capture them). A clean
      20-field form returns ~20 `OK …` lines PLUS the "collapsed" summary — the lever-#4
      collapse only trims its own block, not the chatter it was meant to replace. Fix:
      buffer primitive output in `apply` (redirect_stdout in `_run`); print per-field
      lines ONLY for failures. Big per-subsequent-turn re-read win on the common path.
- [ ] **E.2 drop `_field_exists` double-resolve for defaults** (`atsform.py:~665-711`
      called at `_run_defaults:~780`, then the primitive re-resolves at `:~781`; selects
      cost 2 evaluates each in the probe + 2 more in `select`). Give primitives an
      unambiguous not-found sentinel and let `_run_defaults` skip on it — one resolve per
      default instead of two/three. Medium risk (must not swallow real fill failures).
- [ ] **E.3 aggressive SKILL.md core + task→tool manifest.** SKILL.md is ~14.2k tok
      loaded EVERY firing; ~half is autonomous-loop mechanics only needed when actually
      applying. Deferred in pass 1 as "risky mid-loop"; now safe to: (a) move loop
      mechanics (lines ~110-207) to `references/autonomous-loop.md`, leaving a slim
      always-on core (when-to-use, decision tree, hard-stops one-liner, the manifest);
      (b) add a machine-checkable **task→tool manifest** (screen titles→check_title;
      source+screen→pipeline.py; fill→atsform apply; …) read first — the single biggest
      anti-duplication + discoverability win.
- [ ] **E.4 dedupe the CAPTCHA policy** — mirrored across ~36 files (grep confirms).
      Canonical policy file + terse pointers; the audit-grep in `maintaining-this-skill.md`
      stays. Cuts maintenance drift (P0-class policy) and doc tokens.
- [ ] **E.5 minor: `pipeline.py:~336` drop `indent=1`** on the machine-read stdout line
      (pretty-print whitespace the model doesn't need); cap `verdict_reason` length in
      `review_items`. Marginal — payload is already tight.

## Tier F — automation / structural (move loop from model to code; kill duplication)

- [ ] **F.1 retire `run_pass.py` → `apply_queue.py` over `queue.jsonl`.** `run_pass.py`
      is a session scaffold that re-sources (ignoring `board_cooldown` — full browser
      cost every run, no yield recorded, `:~176-185`), re-filters (divergent hardcoded
      word lists — the P0.1 root cause), and re-dedups (`already_applied:~146-157` is
      O(candidates×filesize) substring match with false positives). Its ONE unique value
      is a headless drive-the-whole-queue loop (`pipeline.py` stops at `queue.jsonl`).
      Replace with a thin `apply_queue.py`: read `queue.jsonl`, per row dispatch to the
      right driver by `ats_hint` (linkedin→`apply_ea`, else `atsform apply`), reuse
      canonical dedup/cooldown/`log-application`. ~30 lines; deletes all the divergent
      re-impls.
- [ ] **F.2 expose `pipeline.run()` importable** so any driver (F.1, warm_queue) calls
      the funnel instead of re-implementing it — structurally prevents the "parallel
      orchestrator re-implements everything" driver of duplication.
- [ ] **F.3 if `run_pass.py` is kept short-term:** add `bc.is_active("linkedin",tag)`
      before `run_feed` and `bc.mark_adaptive(...)` after (key on the SAME normalized
      query the feed uses — the loop-preflight key-mismatch caveat applies); replace
      `already_applied` with a one-time tracker parse into `canon_ids` + normalized
      `(company,role)` sets (import from precheck, as log-application does).

## Suggested order

1. **A.1** (queue atomic write, one line) → **A.2/A.3** (cooldown/apply-stats locks) —
   data integrity under the daemon you already run.
2. **P0.2** divergence tests + **F.1/F.2** (retire run_pass, importable pipeline.run) —
   close the duplication class permanently.
3. **B.1-B.3** (nav spawn collapse, evaluate coalescing, poll-not-sleep) — the real
   latency after turn-collapse.
4. **E.1 + E.3** (atsform clean-path silence, SKILL.md split + manifest) — per-turn
   token diet.
5. **C.1-C.5** (funnel de-dup + restore the Blocked→review retry) and **D.1-D.2**
   (render work-queue, drop networkidle) as fill-in.

Re-run STAGETIMER after landing A+B to confirm the browser-round-trip wins show up
before spending effort on C/D.

---

## Implementation status (2026-07-15, second-pass build)

**Landed + verified** (py_compile / bash -n / test suite 76 green / encoder byte-equivalence /
live PDF render — the camofox engine had an active session so browser-behaviour changes were
verified statically + with node JS-syntax checks, NOT by driving the live tab):

- **P0.1, P0.2** — check_title discipline guard (done) + `TestNoDivergentTitleScreen`
  (fails the build if title-screen word lists reappear outside check_title.py).
- **Tier A (all)** — new `fsutil.py` (`file_lock` + `atomic_write`); A.1 queue.jsonl
  atomic+locked write; A.2 board_cooldown locked RMW + yield header-race lock; A.3
  apply_stats locked atomic RMW; A.4 log-application RMW lock, screener TOCTOU lock,
  stagetimer PID-keyed markers.
- **Tier B (all)** — B.1 cfx.sh `jsonbody()` + one-python3 nav/type encoders (byte-identical
  to the old jsonstr path, proven by an equivalence harness); B.2 `_page_state()` coalesce
  in click_and_follow + `_url_len()` coalesce in atsform `_wait_change`; B.3 poll-not-sleep
  in fill/upload/submit; B.4 ensure_tab lists once and threads the pre-create snapshot into
  open_tab (recovery diff preserved — the naive "defer the snapshot" idea was rejected as it
  would break the flaky-500 recovery); B.5 bounded GET/DELETE retry (`_read_method`).
- **Tier C (all)** — C.1 `merge_sources.merge_lists` in-memory (no tmp round-trip);
  C.2 `del all_posts` before screen; C.3 `id()`-set review membership; C.4 dropped
  `drop_tracked` from the pipeline merge → precheck owns tracker logic, **Blocked→review
  retry restored**; C.5 `_canon_ids` stashed in merge, reused by precheck; C.6 SPA-shell
  re-screen; C.7 one-shot transient feed retry; C.8 apply-stats load moved off the post-feed
  path.
- **Tier D (D.1–D.3)** — prerender `wait -n` fill-as-you-drain work queue (bash-4.3+ gated,
  batch-barrier fallback); make-pdf `load`+`document.fonts.ready` instead of `networkidle`;
  `PW_SKIP_VER_CHECK` from prerender. Live-rendered 3 postings OK.
- **Tier E (E.1, E.2-fill, E.3-manifest, E.5)** — atsform buffers primitive stdout and
  suppresses the clean-path per-field chatter (replays only failures); fill defaults skip via
  a `NOTFOUND` sentinel (no `_field_exists` double-resolve); `references/tool-manifest.md`
  (task→tool index) + a SKILL.md pointer; pipeline stdout drops `indent` and caps review
  reasons.
- **Tier F (all)** — `pipeline.run()` importable; `scripts/apply_queue.py` (headless
  drive-the-queue reusing pipeline.run + apply_ea + precheck dedup) **replaces the retired
  run_pass.py** (both copies deleted, SKILL.md + linkedin-ea-batch-filter.md rewired).

**Second build — the 4 formerly-deferred items, now LANDED + verified:**

- **E.2 for select/radio/checkbox** — `quiet_notfound` added to all three; each returns the
  `NOTFOUND` sentinel at its field-absent branch, so `_run_defaults` dropped `_field_exists`
  entirely (one resolve per default, not two/three). Default (explicit-config) behavior is
  byte-unchanged. `TestAtsformDefaultsSkip` added.
- **E.3 SKILL.md loop-mechanics extraction** — the verbose per-step mechanics moved to
  `references/autonomous-loop.md`; SKILL.md keeps a condensed step checklist with EVERY ⛔
  guardrail inline (email gate, proof, dismiss, funnel, attempt cap); loop-prompt.md pointer
  updated. Done via surgical `Edit`s (which fail-safe rather than clobber a concurrent write).
  SKILL.md 58.3KB → 46.6KB (~11.7KB / ~2.9k tokens off every firing, with E.4).
- **E.4 CAPTCHA-policy dedup** — `references/captcha-policy.md` is now the canonical source;
  SKILL.md's block condensed to the directive + 2 sanctioned exceptions + halt procedure +
  pointer (deep solve/popup/cooldown mechanics moved out). The safety-critical *directive*
  stays intentionally mirrored across all surfaces (verified: 10 key-phrase hits remain in
  SKILL.md); only the detailed mechanics were de-duplicated. Audit-grep note points at the
  canonical file.
- **D.4 single Playwright connection/page-pool** — `sites/_common/scripts/multi-render.js`
  (one `chromium.connect`, a page per dir, per-page try/catch) + an opt-in
  `PRERENDER_SINGLE_CONN=1` path in prerender-pdfs.sh (falls back to the D.1 work-queue if the
  LAN IP/server/CWD constraints aren't met). Live-tested — and it surfaced a real bug (a
  missing resume.html served a 404 page that rendered as a bogus PDF); fixed with a `[ -f
  resume.html ]` guard + a non-2xx `response.ok()` check in the node renderer.

Everything in this roadmap is now implemented. Test suite 78 green; all changed Python
compiles, all changed shell is `bash -n` clean; cfx.sh encoder changes proven byte-identical;
PDFs live-rendered on both the per-dir and single-connection paths.

---

## Third pass — audit-loop findings (2026-07-15, to IMPLEMENT when the baseline is green)

Surfaced by the audit loop while code fixes were blocked by the concurrent `searches.csv`
cooldown-key red. All are verified-by-reading (file:line); land each with a regression test
once the suite is green again.

- [x] **G.1 `company_cache.put` unlocked rewrite — DONE (firing 10).** Now a locked atomic
      read-modify-write via `fsutil.file_lock`+`atomic_write` (same as Tier A.2/A.3); test
      `TestCompanyCache.test_put_get_roundtrip_normalized_atomic` (roundtrip + Ltd-normalize +
      no leftover temp). 81 tests pass.
- [x] **G.2 `screener.lookup` re-reads CSV + recompiles regex per call — DONE (firing 11).**
      `_rows()` now memoized on CSV mtime (`_rows_cached`, auto-invalidates on `record()`
      which bumps mtime) and each `/regex/` pattern compiled once (`_compiled` lru_cache).
      test `TestScreenerMemo.test_memoized_and_record_invalidates`. 82 tests pass. (Still OPEN
      as a separate BUG-AUDIT item, not perf: `_matches` plain branch is `p in q` substring —
      audit the seed patterns for false cognates, e.g. `"commut"` ⊂ `"telecommute"`.)
- [x] **G.3 `board_cooldown` CSV re-parse per planning pass — DONE (firing 13).** Confirmed
      live: `plan()`'s WORK path read `board-cooldown.csv` once PER search (50×) via
      `remaining_hours` and the append-only `search-yields.csv` per clear search via
      `expected_yield`. Fixed: `remaining_hours(…, rows=)` + `expected_yield/yield_history(…,
      yield_rows=)` accept pre-parsed rows (default None = read, backward-compatible), and
      `plan()` reads each CSV ONCE before the loop and threads them in. Measured 50→1 read
      each. test `TestSearchPlanPerf.test_plan_reads_cooldown_csvs_once_not_per_search`. 84
      tests pass.
