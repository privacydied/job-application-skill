# Job-Application MAINTENANCE + APPLY Loop (paste-able prompt — Hermes & Claude Code)

**Read `SKILL.md` first** (it points to `references/tool-manifest.md` — check it BEFORE
writing any script; the shipped tool almost always exists). Applicant truth:
`references/applicant-profile.md`. This prompt extends `loop-prompt.md` with a
self-maintenance mode: **every firing does useful work** — apply when fresh postings
exist, audit/fix/optimise the skill itself when they don't.

---

## 0. Checkpoint gate — FIRST, before reading anything else or opening a browser

```bash
python3 loop-preflight.py       # reads searches.csv + board-cooldown.csv + holds.csv only
```

- **`WORK` (exit 0)** → §1 APPLY PASS (the fresh-posting queue is the priority; never
  spend an apply window on maintenance).
- **`SLEEP` (exit 10)** → §2 MAINTENANCE PASS (browser idle = perfect audit window),
  then stop until the printed `wake_at`.
- **`DONE` (exit 12)** → target met. ONE maintenance pass (§2) is authorized, then stop.
- **`HOLD` (exit 11)** → remind the user once (VNC `http://nasirjones:6080/vnc.html`),
  END the turn. No maintenance while a filled form is held — don't touch anything.

**Hermes bootstrap:** `references/hermes-bootstrap.md` (source the persisted env every
terminal call; recover dead tabs by re-opening with the stable `CFX_KEY`). **Claude
Code:** the PostToolUse hook sets `CFX_*`. Both paths: `fix-perms.sh` after writing any
skill file (Hermes has no hook).

---

## 1. APPLY PASS (verdict=WORK)

**One call sources+screens everything:** `CFX_KEY=… CFX_TAB=… python3
sites/_common/scripts/pipeline.py` → apply straight from `queue.jsonl`
(easiest-ATS-first). Volume driver for Easy Apply rows:
`python3 scripts/apply_queue.py --max 8` shakedown → audit tracker rows → full pass.
Per-posting mechanics: SKILL.md steps 0–10 + `references/autonomous-loop.md`.

### Sourcing — boolean OR-bundles ONLY (never one-title-at-a-time searches)

All queries live in **`searches.csv`**, one bundle per board+family, shaped like:

```
("product designer" OR "ux designer" OR "design engineer" OR "ux researcher") -senior -lead -principal -staff -head -manager -director
```

(Format example only — the real bundles are the tracked rows; edit `searches.csv` to
change what's hunted.) The `-exclusions` are a **weak ranking signal** — boards don't
reliably honour them; `precheck.py`/`check_title.py` is the real gate. Title-screen word
lists live ONLY in `check_title.py` (the divergence test enforces this) — never re-add a
per-driver filter; if an off-profile title leaks, fix `check_title.py`.

### ⛔ After EVERY successful submission (same weight as the tracker row)

1. **Proof + log** — `confirmation.png` into `applications/<slug>/`, then
   `log-application.py … Applied --proof <file>` (no proof ⇒ NOT `Applied`).
2. **Return to the job-search results** view (the card-level controls live there, not
   on the detail page).
3. **Hide the listing** — click the board's prohibit/hide/"not interested" icon so it
   never resurfaces in a future sourcing pass (which reads the board, not the tracker).
   **⚡ Preferred: batch it** — collect the run's terminal LinkedIn ids and
   `python3 sites/linkedin/scripts/feed.py hide-batch <id1,id2,…>` = ONE results visit
   hides them all (`CARD_NOT_FOUND` on a virtualized card is a benign no-op). Hand-driving
   another board → the card's own 🚫 control.
4. **Confirm the hide took** — the card greys out / disappears; if the UI doesn't
   reflect it, note it and move on (tracker dedup still protects).
5. **Close the posting's tab** (`cfx.sh close-tab`) so only the main search tab remains
   — camofox strands the run past ~8 open tabs.
6. **Next listing.** When the current results page is exhausted → next page (CSJ:
   always `--all-pages`; LinkedIn/Indeed: the feed paginates). A pass with 0 fresh
   auto-marks the adaptive cooldown → switch boards; all boards cooling → §3.
   **`Blocked` is the ONE never-hide exception** (retryable; hiding makes it
   un-refindable).

Hard rules that override everything: CAPTCHA policy (`references/captcha-policy.md` —
full halt except reCAPTCHA v2 + CSJ ALTCHA), one-tab serialization, the email-identity
gate (`you@example.com`, never the gmail SSO), never pad the count with
off-profile/senior/location-fail roles.

---

## 2. MAINTENANCE PASS (verdict=SLEEP/DONE) — cap the scope, verify everything

Budget per firing: **≤1 bug fixed + ≤3 docs compressed + ≤1 perf item**. Commit each
verified unit separately. Un-run code is not a verified fix.

### 2a. Bug audit → fix forward

```bash
python3 -m pytest tests/test_core.py -q          # must be green BEFORE and AFTER
python3 -m py_compile sites/_common/scripts/*.py scripts/*.py
for f in sites/_common/scripts/*.sh; do bash -n "$f"; done
python3 scripts/triage_blocked.py                # Blocked rows grouped by ATS = live bug list
```

Then hunt one class deep: stale notes contradicting live behaviour (source-of-truth
rule: probe, don't parrot), swallowed exceptions, unlocked writes to shared CSVs (route
through `fsutil.file_lock`/`atomic_write`), divergent re-implementations (the
tool-manifest + divergence test are the guard), `NOTES.md` claims never re-verified.
**Every fix ships with a regression test** in `tests/test_core.py`, and the stale doc is
corrected in the SAME turn (continuous-learning protocol, SKILL.md §Per-site logic).

### 2b. Documentation audit — brevity WITHOUT nerfing

Pick ≤3 files from `references/` + `sites/*/NOTES.md` (largest or staled first;
`wc -c` ranks them). For each:
- Cut narration, keep **facts, commands, selectors, exit codes, and every ⛔/⚠️ rule** —
  a guardrail may be shortened, never weakened or deleted.
- Collapse duplicated prose into ONE canonical file + terse pointers (pattern:
  `captcha-policy.md`, `tool-manifest.md`, `autonomous-loop.md`). The CAPTCHA
  **directive** stays mirrored on every load-bearing surface — dedupe mechanics only,
  then run the audit grep in `references/maintaining-this-skill.md`.
- Superseded/dead notes → delete, don't append contradictions.
- Record the byte delta; target ≥25% off a verbose file. SKILL.md itself only shrinks
  via the extraction pattern (detail → reference file + inline pointer + inline ⛔s).

### 2c. Perf pass — first principles, measured

Cost model: **model turns × inference latency + tokens re-read per firing + serialized
browser wall-clock + state re-derivation**. Fixed floors — never "optimise" these: the
anti-detect pacing, one-tab serialization, the CAPTCHA policy.

```bash
python3 sites/_common/scripts/stagetimer.py report   # where did the seconds actually go?
```

Hunt, in order of historical payoff: (1) model turns that code could absorb (batch a
per-item step into one process call); (2) tokens returned to context (files-not-stdout,
suppress clean-path chatter, compact payloads); (3) un-paced round-trips (coalesce
multiple evaluates into one JSON-returning call; poll-not-sleep; spawn collapse);
(4) redundant parses/serializations of the same data (cache/stash and thread through);
(5) unlocked/non-atomic shared state; (6) idle lanes (render off the critical path,
warm the queue under SLEEP). Every idea lands in `references/perf-roadmap.md` with
file:line + expected win + risk; implement only what this firing can VERIFY (tests /
byte-equivalence / live render — **never drive the live camofox tab if another session
is active**: check `/health` `activeSessions` first).

### 2d. Close out

`fix-perms.sh` → full test suite green → commit per unit with a message naming the
audit class → update `perf-roadmap.md` status. A maintenance pass that found nothing
rots next firing's value: end by naming the NEXT most suspicious file/subsystem in the
commit body so the next firing starts warm.

---

## 3. End of run — reschedule precisely

`python3 loop-preflight.py` once more → reschedule for its `wake_at` (never a blind
interval). Report one block:

```
Mode:     APPLY (N submitted: Company Role, …)  |  MAINTENANCE
Fixed:    <bug + test>  |  Docs: <files, -X%>  |  Perf: <item, verified how>
Hidden:   N listings dismissed on-board (batch/manual)
Boards:   exhausted vs yielding · cooldowns set
Next:     SLEEP until <wake_at>  |  HOLD on <site>  |  WORK remaining
```

Guardrails this loop encodes: idle firings do maintenance instead of re-confirming
"still dry"; maintenance never runs while a form is HELD or another session owns the
tab; every submitted listing is hidden on-board + its tab closed before the next one;
no scope creep past DONE without a genuinely new instruction.
