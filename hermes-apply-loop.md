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
- **HOLD (exit 11)** — a CAPTCHA is waiting on the user. STOP; remind them via noVNC, end the turn.
- **WORK (exit 0)** — continue. Source **only the `clear` searches it printed, in that order**.

## 1. Bootstrap (only on WORK)
```bash
curl -fsS http://localhost:9377/health              # engine live?
bash sites/_common/scripts/fix-perms.sh
export CFX_URL=http://localhost:9377 CFX_USER=nasirjones
export CFX_KEY=…                                     # backend token
export CFX_TAB=…                                     # a tab id from POST /tabs
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
feed errors. **Boards available** (all in `pipeline.py FEEDS`): linkedin, indeed, wttj, csj,
hackney, adzuna, reed, thedots, **totaljobs, cwjobs, guardian, charityjob, cvlibrary**.
If a run names a board/role, put it first / restrict scope accordingly.

## 3. Apply — iterate `queue.jsonl` top-to-bottom, up to the target (default 10 submitted)
For each posting, follow SKILL.md §"Autonomous Application Loop": screen → tailor resume/cover →
render PDF → fill the ATS form → submit → capture proof → `log-application.py`.
- **Never re-navigate an index/search URL "to get the next job"** — go straight to each `.url`.
- Bespoke ATS recipes exist for: ashby, greenhouse, lever, workday, workable, smartrecruiters,
  recruitee, hibob, TalentLink, applicationtrack (see each `sites/<x>/NOTES.md`). Generic forms
  → `sites/_common/scripts/atsform.py` (label-based fill + `upload`/`upload_chooser` for CVs).
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
  Guardian (sign in → "password instead" for stored-CV instant apply)**. Creds live in the
  gitignored `ats-credentials.csv`. A walled login-required board = hard stop for THAT board;
  keep applying on login-free ones.
- **No fabrication.** Answers come from the profile/config; never invent experience, motivation,
  or eligibility. Security-vetted roles (MI5/GCHQ) are **user-completed** — see
  `sites/applicationtrack.com/NOTES.md`.
- **On-profile only** — respect `references/target-roles.md`; don't spray off-profile.

## 4. Hard stop / hand-off
CAPTCHA (non-sanctioned or distrust-walled), login wall, or a genuinely stuck form → write a row
to `holds.csv`, screenshot the state, remind the user via noVNC (`http://nasirjones:6080/vnc.html`),
end the turn cleanly. Don't retry a mutating submit (double-apply risk).

## 5. Close out
When the target is met or every board is cooled/exhausted: STOP, don't re-source. Report ONE block:
`Applied: N (companies)` · `Sourced/screened: X→Y` · `Holds: <board:reason>` · `Next: <wake_at>`.
Then reschedule the next firing for the preflight's `wake_at` (firing earlier is provably wasted).

_This loop stops when the Hermes session closes. It never modifies Hermes CLI logic; it only
runs the skill's own scripts. Boards/creds/profile all live on-disk (gitignored) and are read
locally, so it behaves identically under Hermes and Claude Code._
