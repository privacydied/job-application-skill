# Job-Application Loop (paste-able prompt)

**Read `GOAL.md` + `SKILL.md` first.** Applicant truth: `references/applicant-profile.md`. This file is only the *loop control* — every per-posting mechanic (screen → tailor → PDF → fill → submit → log) lives in SKILL.md §"Autonomous Application Loop" (condensed step checklist + ⛔ guardrails), with the full step-by-step detail in `references/autonomous-loop.md`; follow it there, don't duplicate it here.

There is exactly **one** loop, no "modes" — ignore any stale mention of Mode A/B/C, an orchestrator, or `modes-config.yaml` (deleted for causing endless loops).

---

## 0. Bootstrap (once per run)

### 0.0 CHECKPOINT GATE — run FIRST, before reading anything else or opening a browser

```bash
python3 loop-preflight.py    # cheap: reads searches.csv + board-cooldown.csv + holds.csv only
```

It answers, from tiny on-disk state alone, whether this firing has any fresh work — do NOT read SKILL.md, open a tab, or run feeds before seeing its verdict:

- **`verdict=SLEEP` (exit 10)** — every search is cooling; nothing can have changed. **STOP immediately**, reschedule the next firing for the printed `wake_at` (firing earlier is provably wasted). One-line report: "All searches cooling; next work possible at `<wake_at>`." This is the normal, healthy idle path — a handful of tool calls, not a full instance.
- **`verdict=DONE` (exit 12)** — today's confirmed `Applied` count already meets the target (default 10; override with `--target N` / `APPLY_TARGET`). A prior same-day firing finished the goal. **STOP — do not source.** (This folds the old manual "count today's Applied rows" preflight into the checkpoint.) Re-verify the tracker if unsure; only a new instruction ("do 5 more") authorizes more.
- **`verdict=HOLD` (exit 11)** — a CAPTCHA is waiting on the user. STOP, remind them via VNC (`http://nasirjones:6080/vnc.html`), end the turn.
- **`verdict=WORK` (exit 0)** — do the full bootstrap below. Source **only the `clear` searches it listed**, **in the printed order** (highest expected-yield first) — that list IS the sourcing plan; skip cooling ones, don't re-enumerate boards it didn't name.

`searches.csv` is the canonical board+query list the gate reasons over; `holds.csv` (created on a hard stop, deleted when the user clears it) is how a hold survives across firings. The verdict logic lives in `sites/_common/scripts/search_plan.py`, shared with `pipeline.py`.

**⚡ One-call fast path (preferred on `verdict=WORK`): `pipeline.py`.** Once the tab is bootstrapped (§0.1), a single call does the WHOLE sourcing→screening funnel in code — no feed JSON in your context:
```bash
CFX_KEY=… CFX_TAB=… python3 sites/_common/scripts/pipeline.py [--target N] [--boards linkedin,indeed] [--force]
```
It re-runs the plan (so it self-gates on SLEEP/DONE/HOLD), sources every clear search in yield order, merges + prechecks + JD-screens the survivors, and writes a ready **`queue.jsonl`** (one enriched posting per line: `url,title,company,tier,family,ats_hint,apply_rank,salary,jd`). It prints ONLY counts + the queue path + the `review` items (ambiguous location — you decide) + any feed errors. Skip to §3 and apply straight from `queue.jsonl` (already ordered easiest-ATS-first). Fall back to the manual §1/§2 steps only to debug a feed or when driving a single board by hand.

### 0.1 Full bootstrap — ONLY on `verdict=WORK`

1. **Confirm the canonical dir**, not the stale mirror: `head -3 application-tracker.csv` shows real company rows (not `Example Co`) and `references/applicant-profile.md` line 1 reads `# Applicant Profile — Jane Doe`. If not, `cd` to the canonical path (SKILL.md §stale mirror).
2. `curl -fsS http://localhost:9377/health` — engine live?
3. **Hermes path:** run `sites/_common/scripts/fix-perms.sh` (Claude Code does this via hook), then `export CFX_KEY=…`, `CFX_USER=nasirjones`, open `CFX_TAB`.
4. Set the run cap (default **10 submitted**; user may override), read the tracker for context, keep an in-memory **handled-set** for this run.

---

## 1. Source into a CONCRETE LIST — then stop sourcing

**FIRST: did the run prompt name a starting point or scope?** If so it overrides the default board order (SKILL.md §"Boards to hit"): reorder the preflight's `clear` list so the named board(s) come first. "**only**"/"**just**" restricts the run to those boards — don't rotate to the rest even when exhausted; report them "not in scope" and stop. A named *role* filters which `searches.csv` rows you source. Fall back to SKILL.md's numbered order only when nothing is named.

**Login-check first (one call):** `python3 sites/_common/scripts/check_login.py` — all four boards (LinkedIn, WTTJ, Indeed, SEEK; or pass a subset). Exit 11 = a login-required board is WALLED → hard stop for that site (message the user per §4), continue login-free boards (Indeed/SEEK/CSJ/Hackney). It navigates, so run it before the feeds.

**The board+query cooldown is enforced inside the `feed.py` scripts — never check/mark it by hand.** Just call the feeds:
```bash
python3 sites/indeed.com/scripts/feed.py --nav "<searches.csv nav URL>"
python3 sites/linkedin/scripts/feed.py --nav "<searches.csv nav URL>"
python3 sites/welcometothejungle/scripts/feed.py
python3 sites/civilservicejobs/scripts/feed.py --nav "<searches.csv csj nav URL>" --all-pages   # ALWAYS --all-pages; auto-solves CSJ's ALTCHA (sanctioned); trust only its jobs.cgi?jcode= URLs
python3 sites/hackney/scripts/feed.py --nav "https://recruitment.hackney.gov.uk/job-search/"   # WP board; no CAPTCHA sanction here
```
Each feed: reads the search term from the `--nav` URL (WTTJ uses the fixed key `home`); if that board+query is already confirmed dry it prints `[]` + a `COOLDOWN:` line and exits with zero browser cost; and it **auto-marks** the 12h cooldown when a real pass yields zero fresh. A feed returning `[]` with `COOLDOWN:`/`EXHAUSTED:` is **done for this run** — next board. All boards cooled/exhausted → go to §5 and stop. To deliberately re-source early (user says "check again now"): `--force`. (`board-cooldown.sh` remains for ad-hoc inspection/overrides on the same CSV.)

Pull survivors into a flat list of `{id, url, title, company, location}`, enumerated up front. **Never re-navigate a listing/index URL to "get the next job"** — the #1 historical time-sink (SKILL.md §"Don't loop"). Iterate the list, navigating straight to each canonical URL. (feed.py already dedups tracker ids out of its output; still skip this run's handled-set.)

## 2. CHEAP PRE-FILTER — before opening ANY posting

Screen the **list metadata (title + location) WITHOUT opening postings**, as ONE code call for the whole feed:

```bash
python3 sites/<board>/scripts/feed.py --nav "…" | python3 sites/_common/scripts/precheck.py -
```

Per candidate it runs: title eligibility against the FULL `target-roles.md` tier list (don't judge from memory — prose recall drops on-profile Tier B/C titles), the location hard screen (non-London UK city → drop; London/remote → keep; generic-UK/abroad → review), tracker dedup, salary-cache attach → `keep`/`review`/`drop` with tracker-ready reasons. `drop` → do NOT open "to make sure"; `review` → the JD's own location line decides (from `jd.py`'s payload in §3, not a snapshot). Also drop this run's handled-set.

Log dropped cards as `Skipped` (one-line reason) only if they were real postings you'd otherwise reconsider; junk promoted cards drop silently. An obviously-off card must cost a title glance, not a page-open + JD read + tailor.

Survivors = the **work list**. Only now open JDs and run the full SKILL.md screen (salary, agency, external-ATS-is-fine, …).

## 3. Apply — one posting at a time, with a HARD ATTEMPT CAP

**Work list = `queue.jsonl` from `pipeline.py`** (already precheck-screened, JD-screened, and ordered easiest-ATS-first via `apply_rank`, then tier, then family). If you sourced manually instead, your §2 survivors are the work list. For each posting, run SKILL.md steps 1–10 — **batching the turns** (`references/fast-loop.md`):

- **Screen+extract in ONE call per posting:** `python3 sites/_common/scripts/jd.py --nav "<url>"` returns the whole screening payload. Never full-page `snap` a JD; never revisit for must-haves — they're in the payload.
- **Tailor the WHOLE work list, then fill.** One `tailor.py` spec covering every survivor → `python3 sites/_common/scripts/tailor.py apply <spec> --render` (subs + cover letters + placeholder/wrong-company checks + all PDFs in one parallel pass). Front-loading the writing keeps the sequential browser fills back-to-back.
- Profiling where a run's seconds go: `export STAGETIMER=1` first, then `python3 sites/_common/scripts/stagetimer.py report` at the end.

**WTTJ logging — always capture a stable id:** before logging any WTTJ posting, get its canonical id via `python3 sites/welcometothejungle/scripts/feed.py id` and log that `/jobs/<id>` URL. Never log a bare/id-less WTTJ URL (can't be deduped; resurfaces forever). `NO_ID` → re-open the posting from its canonical link and retry before logging.

**Attempt cap (kills the endless loop):** **2 real attempts** to progress a single posting's form (attempt = a fill/submit try with no forward progress — same step, byte-identical after your action). On the 2nd failure: log `Blocked` with the concrete reason, close the tab, next posting. Never a 3rd try in the same run. Also honor SKILL.md's ~10-min-per-posting ceiling.

**LinkedIn Easy Apply → `sites/linkedin/scripts/easyapply.py`, not `atsform.py`** (shadow-DOM modal incl. the "Save this application?" dialog — solved; `sites/linkedin/NOTES.md`). It goes through the normal attempt-cap cycle like any ATS.

## 4. Hard stops — PERSIST them so the next firing doesn't re-hit them

A hard stop must survive into the next firing. **Record it in `holds.csv`** (preflight reads it): append `type,site,role,url,created_at,note` with `type` = `captcha` or `login`. **Clear it** (delete the row) once the user confirms resolution.

- **CAPTCHA** → append `captcha,<site>,<role>,<url>,<now>,<what it blocks>`, hold the filled application, message the user once (VNC `http://nasirjones:6080/vnc.html`), **end your turn**, wait. Next firing's preflight returns `HOLD`. On the user's "done": delete the row, finish the SAME application. Do NOT continue other postings; do NOT batch to end-of-run.
- **Login wall** → append `login,<site>,,,, <now>,walled`. Blocks that SITE only — preflight skips its searches but still WORKs the others. Message the user; delete the row once the session's restored.
- **Untruthful required question / payment request / legal attestation** → per SKILL.md hard-stops.

Everything else (multi-page forms, uploads, screener essays, new ATS, external-ATS redirects) → autonomous; an external ATS is a normal application, never a skip reason. **⚡ Fill standard forms with the batch runner:** ONE config starting `"defaults": true` → `python3 sites/_common/scripts/atsform.py apply <config.json>` (Ashby → `sites/ashbyhq/scripts/ashby.py apply`); per-field primitives only for discovery/stragglers. (Easy Apply stays on `easyapply.py`.)

## 5. End of run — set the NEXT wake precisely

Stop when any of: **cap reached** · **work list exhausted** · **everything remaining CAPTCHA/login blocked**. Dry searches are already cooldown-marked by the feeds.

**Pace the next firing off the checkpoint, not a blind interval:** run `python3 loop-preflight.py` once more; it returns `SLEEP` with a `wake_at` (or `DONE` if the target's met). **Reschedule for that `wake_at`** — that's what stops waking every few minutes to re-confirm "still dry". If a `HOLD` is active, wait on the user instead.

**Timing (STAGETIMER is on by default):** `python3 sites/_common/scripts/stagetimer.py report` for the per-stage wall-clock breakdown (source vs screen vs tailor vs pdf vs fill) — include the headline in the summary so the loop's own data guides the next optimization.

Report one block:

```
Applied: N  (Company Role, …)
Skipped: N  (top reasons)
Blocked: N  (posting → reason; which are retryable)
Boards:  which are exhausted vs. still yielding
Next:    SLEEP until <wake_at>  |  HOLD on <site/role>  |  WORK remaining
```

---

## Guardrails these mechanics encode (don't reintroduce the failure)

1. Endless form loop → §3 attempt cap.
2. Token waste opening ineligible roles → §2 pre-filter before opening.
3. Re-walking dry boards → cooldown enforced inside `feed.py` (§1).
4. Burning an instance to conclude "nothing new" → §0.0 preflight SLEEP/WORK/HOLD from disk state + exact `wake_at`.
5. Un-dedupable WTTJ rows → `feed.py id` at log time (§3); id-less picks are skipped with a warning.
