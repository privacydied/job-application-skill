# Job-Application Apply Loop — paste-able Hermes prompt

Run the job-application skill's source→screen→apply→log loop. **Read `GOAL.md` + `SKILL.md`
first** for the per-posting mechanics and ⛔ guardrails; this prompt is only the loop control.
Applicant truth: `references/applicant-profile.md`. There is exactly **one** loop — ignore any
stale "modes".

## 0. Checkpoint gate — run FIRST, before reading SKILL.md or opening a browser
```bash
cd /volume1/homes/pry/.hermes/skills/productivity/job-application
python3 loop-preflight.py        # reads searches.csv + board-cooldown.csv + holds.csv only
```
- **SLEEP (exit 10)** — every search cooling. STOP; reschedule for the printed `wake_at`. One-line report.
- **DONE (exit 12)** — today's `Applied` count already meets target. STOP; don't source.
- **HOLD (exit 11)** — a CAPTCHA/login is waiting on the user. STOP; remind them via noVNC, end the turn.
- **WORK (exit 0)** — continue. Source **only the `clear` searches it printed, in that order**.

## 0.5 ⚠️ COEXISTENCE — this repo is edited LIVE by Claude Code while you run
A developer is actively expanding this skill in Claude Code (new board feeds, tests, docs,
commits) **on the same repo and the same camofox browser**. This loop MUST survive that without
corrupting either side. Hard rules:

- **🖥️ Browser: use your OWN dedicated tab; never touch a foreign one.** At bootstrap, `POST /tabs`
  to create a fresh tab and use ONLY that `CFX_TAB`. **NEVER** `restart` the camofox engine and
  **NEVER** close/navigate/submit on a tab you didn't open — Claude Code may have an application
  mid-flight in another tab (closing it or restarting the engine destroys in-progress work and can
  double-submit). Camofox serializes actions server-side, so a shared browser is safe as long as
  each side stays on its own tab.
- **🔁 Treat transient browser errors as contention, not failure.** A 500 / timeout / `410 Tab not
  found` / one-off `evaluate` error mid-run is very likely the other session pacing the shared
  browser. Back off ~3–5s and **retry idempotent reads once** (feeds already do this). NEVER
  auto-retry a mutating POST/submit (double-apply risk) — on a submit error, verify state first.
- **🧩 Tolerate code edits under you.** Claude Code may edit `feed.py`/`pipeline.py`/`atsform.py`
  between (or during) your calls. Each feed runs as a fresh subprocess, so edits are picked up
  cleanly next firing; a mid-edit import/syntax error on ONE board = **skip that board this
  firing, do NOT try to fix or debug code** (that's Claude Code's job). Re-read `searches.csv`
  every firing — new boards appear there without warning; never cache the board list.
- **📎 Git: stay out of it.** Do **NOT** `git add`/`commit`/`push` — ever. You only write local
  run-state (tracker, cooldowns, yields, queue, proof screenshots) via the canonical helpers
  below. Committing collides with Claude Code's in-flight commits; leave all git to the developer.
- **🔒 Shared files: only via the locked helpers.** Write the tracker ONLY through
  `log-application.py`; cooldowns/yields ONLY through the `feed.py`/`board_cooldown` path; the
  queue is written by `pipeline.py`. These use `fsutil` atomic+locked writes so concurrent access
  is safe. **Never hand-edit** application-tracker.csv / board-cooldown.csv / searches.csv /
  queue.jsonl / holds.csv. Only write a `holds.csv` row for YOUR own genuine block; act on a HOLD
  the preflight reports regardless of who set it.

## 1. Bootstrap (only on WORK)
```bash
curl -fsS http://localhost:9377/health              # engine live? note activeSessions (≥1 = Claude Code is here too — fine, see §0.5)
bash sites/_common/scripts/fix-perms.sh
export CFX_URL=http://localhost:9377 CFX_USER=nasirjones
export CFX_KEY=…                                     # backend token
export CFX_TAB=…                                     # a FRESH tab id from POST /tabs (yours alone — §0.5)
```
Confirm the canonical dir: `head -3 application-tracker.csv` shows real rows (not `Example Co`)
and `references/applicant-profile.md` line 1 is `# Applicant Profile — <real name>`.

## 2. One-call source→screen (preferred fast path)
```bash
python3 sites/_common/scripts/pipeline.py [--target N] [--boards <subset>] [--force]
```
It self-gates (SLEEP/DONE/HOLD), sources every clear search in yield order, merges + prechecks
+ JD-screens, and writes a ready **`queue.jsonl`** (one enriched posting per line:
`url,title,company,tier,family,ats_hint,apply_rank,salary,jd`), ordered easiest-ATS-first.
It prints ONLY counts + the queue path + `review` items (ambiguous location — you decide) +
feed errors. **Boards available** (all in `pipeline.py FEEDS`, re-read fresh each firing):
linkedin, indeed, wttj, csj, hackney, adzuna, reed, thedots, **totaljobs, cwjobs, guardian,
charityjob, cvlibrary, nhs**. If a run names a board/role, put it first / restrict scope.

## 3. Apply — iterate `queue.jsonl` top-to-bottom, up to the target (default 10 submitted)
For each posting, follow SKILL.md §"Autonomous Application Loop": screen → tailor resume/cover →
render PDF → fill the ATS form → submit → capture proof → `log-application.py`.
- **Never re-navigate an index/search URL "to get the next job"** — go straight to each `.url`.
- Bespoke ATS recipes: ashby, greenhouse, lever, workday, workable, smartrecruiters, recruitee,
  hibob, TalentLink, applicationtrack, **NHS Jobs→Jobtrain/Trac** (see each `sites/<x>/NOTES.md`).
  Generic forms → `atsform.py` (label fill + `upload`/`upload_chooser` for CVs).
- **⛔ Multi-section / modal ATSes have NO single "Save and Continue" — each section AND each
  entry-modal (employment/education/references) has its OWN save button.** Find the ACTUAL control
  before concluding a field "won't bind" (Jobtrain: `#btnConform` employment, `#saveEducation`
  education, `#saveReferenceFormTab` refs+page, `#saveApplicationForm` final). Values bind via the
  native value-setter + `input`/`change`; **HTML5 `checkValidity()` is the gate**. A section that
  silently won't advance with no per-field error = **wrong save button, not a widget limitation**
  (see `sites/jobs.nhs.uk/NOTES.md`).
- **NHS Jobs is a pure aggregator** — every trust hands off to its own account-gated ATS
  (Jobtrain/Trac/Oleeo/TalentLink). Sourcing is free; apply needs that ATS's session.
- **Log `Applied` only with a real confirmation artifact** (banner/dashboard screenshot). No proof → not Applied.

## ⛔ Guardrails (hard rules — never relax)
- **CAPTCHA:** FULL HALT for any CAPTCHA except the two sanctioned auto-solves — reCAPTCHA **v2**
  (`recaptcha.py`) and CSJ's **ALTCHA** (inside `civilservicejobs/feed.py`). Everything else
  (Cloudflare Turnstile, hCaptcha) → write `holds.csv`, remind the user via noVNC, STOP.
  ⚠️ Known gap: reCAPTCHA v2 can hit **fingerprint-distrust** (correct solves loop, no token) —
  if it won't yield a token after a couple of rounds, hand that ONE application to the user in
  noVNC (don't burn the loop on it).
- **Login/account gates** (source freely, but apply needs the user's authenticated session):
  LinkedIn, Reed, WTTJ, **Totaljobs/CWJobs (StepStone), CV-Library (also chooser-gated CV upload),
  Guardian (sign in → "password instead"), NHS→Jobtrain/Trac**. Creds live in the gitignored
  `ats-credentials.csv`. A walled login-required board = hard stop for THAT board; keep applying
  on login-free ones.
- **No fabrication.** Answers come from the profile/config; never invent experience, motivation,
  eligibility, grades, referees, or dates. A required real-world fact you don't have (referee
  email, degree grade) → ask the user, don't guess. Security-vetted roles (MI5/GCHQ) are
  **user-completed** — see `sites/applicationtrack.com/NOTES.md`.
- **On-profile only** — respect `references/target-roles.md`; don't spray off-profile.

## 4. Hard stop / hand-off
CAPTCHA (non-sanctioned or distrust-walled), login wall, a missing real-world fact, or a genuinely
stuck form → write a row to `holds.csv`, screenshot the state, remind the user via noVNC
(`http://nasirjones:6080/vnc.html`), end the turn cleanly. Don't retry a mutating submit.

## 5. Close out
When the target is met or every board is cooled/exhausted: STOP, don't re-source. Report ONE block:
`Applied: N (companies)` · `Sourced/screened: X→Y` · `Holds: <board:reason>` · `Next: <wake_at>`.
Then reschedule the next firing for the preflight's `wake_at` (firing earlier is provably wasted).
You may leave your tab open for the next firing; if you close one, close ONLY your own (§0.5).

_This loop stops when the Hermes session closes. It never modifies Hermes CLI logic and never
touches git; it only runs the skill's own scripts on its own browser tab. Boards/creds/profile
live on-disk (gitignored) and are read locally, so it behaves identically under Hermes and Claude
Code — and coexists safely with live Claude Code expansion (§0.5)._
