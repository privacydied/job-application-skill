# AGENTS.md — repository source-of-truth & file-placement spec

This is the **canonical structure contract** for the job-application skill. Any agent
(Claude Code, Hermes, Codex, …) working in this repo MUST follow it. `CLAUDE.md` points
here; do not duplicate this content elsewhere.

Why this file exists: two apply drivers (`amazon_apply.py`, `reed_apply.py`) had drifted
into **stale root copies + maintained `scripts/` copies**, and `SKILL.md` invoked the stale
ones — silently running the old single-ID, pre-bugfix code. The rules below prevent that
class of drift from recurring.

---

## Source-of-truth hierarchy

| Concern | Single source of truth |
|---|---|
| **How to run the skill** (operational playbook) | `SKILL.md` |
| **Per-board verified quirks / recipes** | `sites/<board>/NOTES.md` |
| **Deep-dive playbooks** (referenced by SKILL.md) | `references/*.md` |
| **Repo structure & file placement** (this contract) | `AGENTS.md` (this file) |
| **Shared browser / ATS primitives** | `sites/_common/scripts/` ONLY |

When any doc references a script, it MUST use that script's **canonical path** (below).

---

## Canonical file placement (where a file lives — and where a NEW one goes)

```
SKILL.md                         operational playbook (source of truth for HOW-TO)
AGENTS.md                        this structure contract
CLAUDE.md                        pointer to AGENTS.md + Claude-Code specifics
README.md, LICENSE, GOAL.md      public/meta docs

scripts/                         CROSS-BOARD / skill-level scripts (apply drivers,
                                 queue, login, triage). e.g. amazon_apply.py,
                                 reed_apply.py, apply_queue.py, csj_login.py,
                                 triage_blocked.py, warm_queue.py
sites/<board>/scripts/           BOARD-SPECIFIC scripts: feed.py (sourcing) + any
                                 board apply/diagnostic (e.g.
                                 applicationtrack.com/scripts/diagnose.py,
                                 civilservicejobs/scripts/tal_eform.py)
sites/<board>/NOTES.md           board-specific verified quirks
sites/_common/scripts/           SHARED primitives used by many scripts:
                                 cfx.py (camofox driver), atsform.py, jd.py,
                                 precheck.py, screener.py, make-pdf.sh, …
references/*.md                  deep playbooks
templates/ uploads/ applications/  assets & generated per-application artifacts
tests/                           test_core.py

Root-level entrypoints (the ONLY scripts that live at repo root):
  loop-preflight.py              loop preflight (invoked as `python3 loop-preflight.py`)
  open_tab.sh                    thin superseded shim → cfx.py ensure-tab
```

**Decision rule for a NEW script:**
- Board-specific sourcing → `sites/<board>/scripts/feed.py`
- Board-specific apply/diagnostic → `sites/<board>/scripts/`
- Cross-board apply driver / orchestrator → `scripts/`
- A primitive reused across scripts → `sites/_common/scripts/`
- Board quirks note → `sites/<board>/NOTES.md`; deep playbook → `references/`

---

## ⛔ The no-divergent-duplicate rule (non-negotiable)

1. **Exactly ONE copy of every script.** Never keep the same driver at the repo root
   *and* in `scripts/` (or in two boards). If you need it elsewhere, **import it or move
   it — never copy it.**
2. **Edit the canonical file in place.** Do not "fork" a working script to a new path to
   make a change; drift + a stale doc reference is the guaranteed result.
3. **When you move/rename a script, grep every `python3 <path>` invocation** in `SKILL.md`,
   `references/`, and the `*loop*.md` prompts and update them in the same change.
4. **A script that declares itself "single source of truth" in its docstring is canonical**
   (e.g. `scripts/amazon_apply.py`); delete anything it supersedes.
5. Before adding a script, check it doesn't already exist:
   `git ls-files | grep <name>` and `find . -name '<name>'`.

## 🔒 PII & the config-routing model (never commit the applicant's data)

**The model: real personal data lives ONLY in gitignored files; tracked files carry
placeholders or read the real values at runtime. So applications get the applicant's REAL
answers, while the repo stays PII-free.**

Gitignored (real PII — never tracked):
- `references/applicant-profile.md` — the answer-as-applicant source of truth
- `sites/_common/apply-defaults.json` — form-fill facts + an `applicant` block
  (gender / school / area_of_study / …) that drivers read at runtime
- `ats-credentials.csv`, `application-tracker.csv`, `applications/` — accounts, tracker, generated artifacts

Tracked (must be PII-free):
- Every `*.example.json` / `applicant-profile.example.md` — placeholder shapes for a fresh clone
- Notes / references / templates — use the **`[your …]` placeholder convention**
  (`[your gender]`, `[your ethnicity]`, `[your religion]`, `[your age band]`, …)
- **Drivers must not hardcode PII.** Route demographic/education answers through the
  gitignored config — e.g. `scripts/amazon_apply.py` reads `apply-defaults.json`→`applicant`
  via `_af("gender", …)`. The tracked driver has no personal value; the applicant's real
  `apply-defaults.json` fills the form. Add a new fact to the `applicant` block (+ the
  `.example`), never to the driver.

Rules:
1. **NEVER put the applicant's real name, email, phone, address, postcode, NINO, DOB, or any
   demographic (gender / ethnicity / religion / age band / national identity / sexual
   orientation / disability) into a tracked file.** Placeholder it, or route via config.
2. **Demographic *words* (Man / Mixed / Jewish / British) can't be auto-detected** (common
   English → false positives), so the placeholder convention is the only defense — apply it.
3. **ALWAYS run `bash scripts/check-no-pii.sh` before every push** (or wire it as a
   pre-commit hook: `ln -sf ../../scripts/check-no-pii.sh .git/hooks/pre-commit`). It derives
   your tokens from the gitignored config/profile — name, email, phone, handle, **NINO, UK
   postcode, DOB** — and fails if any appear in a tracked file. A push is not done until it
   prints the ✓ line. If it flags something, move it to a gitignored file or placeholder it.

## Verifying a stale-vs-canonical pair (the method used here)
- `git log --oneline -- <path>` on each copy — the one touched only by the initial commit
  is stale; the one with later bugfix/feature commits is canonical.
- `diff` the two — the canonical copy has the newer features (multi-ID, PII hardening, …).
- Grep `SKILL.md` for which path is invoked — fix it to the canonical one.
- `git rm` the stale copy.
