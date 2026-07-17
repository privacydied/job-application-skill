# CLAUDE.md

**Repo structure & source-of-truth rules live in [`AGENTS.md`](./AGENTS.md) — read it first
and follow it. It is not duplicated here (on purpose — duplication is exactly the drift this
repo just cleaned up).**

Quick pointers:
- **How to run the skill:** `SKILL.md` (the operational playbook / source of truth).
- **Where a file belongs, and the no-divergent-duplicate rule:** `AGENTS.md`.
- **Per-board quirks:** `sites/<board>/NOTES.md`. **Deep playbooks:** `references/*.md`.

## Claude-Code specifics
- **Canonical script paths matter.** Invoke skill-level drivers from `scripts/`
  (e.g. `python3 scripts/reed_apply.py <id> …`) and board scripts from
  `sites/<board>/scripts/` — never a repo-root copy (there are none; keep it that way).
- **Never create a second copy** of an existing script to edit it — edit the canonical one
  in place, and update every `python3 <path>` reference in `SKILL.md` / `references/` /
  `*loop*.md` in the same change (see AGENTS.md §no-divergent-duplicate).
- **Browser automation** runs through the camofox helper `sites/_common/scripts/cfx.py`
  (REST on `$CFX_URL`, tab in `$CFX_TAB`); load `.jobenv` for env. Global browser/Playwright
  notes are in the user-level `~/.claude/CLAUDE.md`.
- **Integrity is the hard rule** (see SKILL.md): every field must be true to the applicant's
  real profile (`references/applicant-profile.md`); personal declarations and final submits
  are the user's. Never fabricate experience, grades, or answers to eligibility gates.
