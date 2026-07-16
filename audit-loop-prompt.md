# Skill AUDIT Loop (paste-able prompt — Hermes & Claude Code)

Pure maintenance: **this loop never sources or submits applications.** Its only job is
to make the skill more correct, cheaper per token, and faster — bug audit → fix, doc
audit → compress, perf audit → implement. (`loop-prompt.md` runs the hunt;
`maintenance-loop-prompt.md` mixes both. This one is audit-only.)

**Read first:** `SKILL.md` → `references/tool-manifest.md` (never re-implement a shipped
tool) → `references/perf-roadmap.md` (what's already done — do NOT re-suggest it).

## 0. Safety gates — check before touching anything

1. **`cat holds.csv 2>/dev/null`** — a `captcha`/`login` HOLD means a filled form is
   frozen mid-flight. Code/doc edits are still OK, but do NOT restart the engine, close
   tabs, or edit apply-path state (`queue.jsonl`, tracker, holds).
2. **`curl -fsS http://localhost:9377/health`** — if `activeSessions ≥ 1`, another agent
   owns the browser: **never drive the camofox tab, never restart the engine.** All
   verification goes static (tests / mocks / byte-equivalence / `bash -n` / `node
   --check`); the Playwright PDF container (`:3006`) is separate and always fair game.
3. **`git status --short`** — uncommitted files you didn't touch = a concurrent track's
   in-flight work. Never stage them; use surgical `Edit`s (they fail-safe on drift, never
   clobber) and explicit per-file `git add`.

## 1. The ledger — no re-plowed ground

State lives in **`references/audit-ledger.md`** (create on first firing):

```
## Swept          <file/subsystem> — <date> — <verdict: clean | N found>
## Open findings  <file:line> — <class> — <symptom> — <proposed fix>
## Fixed          <commit> — <what> — <regression test>
## Next           <the single most suspicious target for the next firing>
```

Start every firing by reading it; pick up from `Next`. End every firing by updating it.
A finding too big for one firing goes to `Open findings` with enough detail that a cold
future firing can execute it without re-deriving the analysis.

**Budget per firing: ≤2 bugs fixed + ≤3 docs compressed + ≤2 perf items.** Commit each
verified unit separately. Un-run code is not a verified fix.

## 2. BUG AUDIT — hunt one class deep per firing, then fix forward

Baseline (must be green BEFORE and AFTER every change):

```bash
export PYTHONPYCACHEPREFIX=/tmp/jobapp-pyc     # root __pycache__ perms trap
python3 -m pytest tests/test_core.py -q -p no:cacheprovider -s
python3 -m py_compile sites/_common/scripts/*.py scripts/*.py sites/*/scripts/*.py
for f in sites/_common/scripts/*.sh; do bash -n "$f"; done
python3 scripts/triage_blocked.py               # Blocked rows grouped by ATS = live bug list
```

Rotate through these classes (one per firing, exhaustively — the ledger tracks which):

- **Divergent re-implementations** — logic that exists canonically but was re-written
  inline (the class that caused the industrial-design-engineer leak). Grep for word
  lists, regex screens, dedup loops, tracker parsing outside their canonical module.
- **Naive matching** — bare `x in y` substring tests on titles/labels/status where a
  false cognate passes (`"design engineer" in "electrical design engineer"`). Check
  every eligibility/label/status comparison for compound-word leaks.
- **Unlocked / non-atomic shared state** — any `open(path,"w")` or check-then-append on
  a file two processes touch; route through `fsutil.file_lock` + `atomic_write`.
- **Swallowed failures** — bare `except: pass` hiding real errors; verify each is
  genuinely advisory (cache/telemetry) and not eating a submit/log failure.
- **Fixed sleeps racing async DOM** — `time.sleep(N)` + single read where `cfx.poll`
  with a predicate is correct.
- **Stale docs contradicting live code** — NOTES/references claiming X is broken/manual
  when a shipped fix exists (source-of-truth rule: probe, don't parrot). Fix the doc in
  the same turn.
- **Contract drift** — CLI flags/exit codes documented but unimplemented (or vice
  versa); docstrings describing pre-refactor behaviour; test stubs missing functions the
  code now calls (`cfx.poll` class).
- **Silent truncation/caps** — top-N slices, `[:limit]`s, and timeouts that drop data
  without printing what was dropped.

**Every fix ships a regression test** in `tests/test_core.py` + a one-line ledger entry.
If the bug class is structural, also add a build-guard test (pattern:
`TestNoDivergentTitleScreen`).

## 3. DOC AUDIT — brevity without nerfing

Rank targets: `wc -c references/*.md sites/*/NOTES.md | sort -rn` — biggest ×
most-stale first; the ledger tracks which are already tight. Per file:

- **Keep, always:** commands, selectors, exit codes, verified failure modes, every
  ⛔/⚠️ rule (shorten wording, never weaken meaning), the WHY when it prevents a repeat
  mistake (one clause, not a story).
- **Cut:** narration, restated context, duplicate explanations of the same quirk,
  superseded notes (delete, don't append contradictions), multi-paragraph histories
  where one dated line carries the lesson.
- **Dedupe across files:** repeated prose → ONE canonical file + terse pointers
  (pattern: `captcha-policy.md`, `tool-manifest.md`, `autonomous-loop.md`). ⚠️ The
  CAPTCHA **directive** is intentionally mirrored on every load-bearing surface — dedupe
  its *mechanics* only, then run the audit grep in `references/maintaining-this-skill.md`.
- **SKILL.md** shrinks only via extraction (detail → reference file + inline pointer,
  ⛔ rules stay inline). It is re-read every firing — every KB here costs every run.
- **Verify:** every pointer resolves (`grep -o 'references/[a-z-]*\.md' <file>` →
  `ls`), no orphaned references to files you renamed/deleted, and record the byte delta
  in the ledger (target ≥25% off a verbose file; report honestly when a file is already
  tight — that's a `clean` verdict, not a failure).

## 4. PERF AUDIT — first principles, from the codebase, nothing too small or too big

Cost model: **firing cost = (model turns × latency) + (tokens re-read per firing) +
(serialized browser wall-clock) + (state re-derivation)**. Fixed floors — never
"optimise": anti-detect pacing, one-tab serialization, the CAPTCHA policy. Guiding
rule: **the model belongs only at judgment points; everything else is code.**

```bash
python3 sites/_common/scripts/stagetimer.py report    # measured, not vibes
```

Sweep the axes, reading the actual code (file:line for every claim):

- **Turn collapse (biggest lever):** any step the model drives per-item that a script
  could batch into one call; any decision derivable from disk state that burns a turn.
- **Token diet:** stdout that returns whole payloads where counts + a file path do; OK
  chatter on clean paths; pretty-printed JSON on machine-read lines; full-page snapshots
  where a scoped eval/region-crop answers; growing files re-read whole.
- **Coalescing:** multiple REST round-trips per poll iteration that one JSON-returning
  evaluate covers; N subprocess spawns encoding what one interpreter could; existence
  pre-probes followed by the real call re-resolving the same target.
- **Async/pipelining:** CPU/disk work stacked serially after browser I/O that could
  hide under it; renders/uploads on the critical path that batch off it; idle windows
  (SLEEP) that could pre-warm caches/queues. Respect the one-tab floor.
- **Memory:** the run's biggest blobs held across long phases after their last real
  use; serialize-to-disk-then-reparse round-trips of data already in RAM; caches with
  no TTL/pruning (`du -sh .jd-cache`).
- **Stability:** transient-error paths with no bounded retry (idempotent reads ONLY —
  never auto-retry a mutating POST: double-submit risk); single-shot feed runs where one
  flake zeroes a board; missing self-heal on known-flaky seams.
- **Batching:** per-item navigations/dismissals/logs where the board/tool offers a
  batch form; barrier waits where fill-as-you-drain saturates slots.
- **Automation:** anything the loop prompt tells the *model* to remember that code
  could enforce (the board-cooldown lesson); manual recipes run ≥3 times that should be
  a script + a tool-manifest row.

Every idea → `references/perf-roadmap.md` with file:line, expected win, risk. Implement
what THIS firing can verify; **ambitious multi-firing items** get a design note in the
roadmap + an `Open findings` ledger entry so the next firing executes instead of
re-thinking. Verify: tests, byte-equivalence for any encoder/wire change, mock-based
unit tests for browser logic when the tab is occupied, live render only on `:3006`.

## 5. Close out every firing

```bash
bash sites/_common/scripts/fix-perms.sh
python3 -m pytest tests/test_core.py -q -p no:cacheprovider -s    # green, or revert
```

Commit per unit (explicit `git add` of YOUR files only — never sweep concurrent work),
message naming the audit class. Update the ledger — including `Next`. Report one block:

```
Bugs:   N fixed (+tests) · N logged to ledger    Docs: <files> (-X%, guardrails intact)
Perf:   <items landed + how verified> · <roadmap additions>
Swept:  <subsystems now clean>                   Next:  <named target>
```

Then reschedule: this loop is steady-state background — a long interval (hours) is
right; it must never starve or collide with the apply loop's firings.
