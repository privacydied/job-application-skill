# Apply-gate pitfalls — POINTER (do not re-apply fixes here)

Both items below were already captured in the authoritative docs during the
2026-07-13 session. This file is a signpost, not a fix list — do NOT re-apply
anything from it; the code/docs are already updated.

- **Ashby `set-toggle` double-toggle / false-positive bug** → FIXED in-repo
  (commits af26693, read-fix then write-path + docstring follow-up). Full
  post-mortem + the corrected selection/read logic lives in
  `sites/ashbyhq/NOTES.md`. Lesson that survives: even after the fix, **re-verify
  a toggle's real selected state** (screenshot / JS read of the button colour)
  after `set-toggle` on a live form — never trust the printed `OK` alone.
- **AI-recruiter / platform funnels (Jack&Jill: Ollyinsurance, Model ML; SiiRA
  "download our app") have NO application form** → these are `Skipped`
  ("platform funnel — no web application form"), per the funnel rule in SKILL.md
  step 1's external-ATS section, NOT `Blocked`. Do not sign the user up to such a
  platform on their behalf. (Note: the 2026-07-13 live run logged the first such
  case — Ollyinsurance via Jack&Jill — as `Blocked`; that tracker row is the one
  inconsistency and should be corrected to `Skipped` to match the standing rule.)
- Operator habit worth keeping: **when a script reports success on a visual
  widget (toggle/checkbox/reCAPTCHA), vision-check it before Submit** — SKILL.md
  step 6 already mandates this; this file just re-emphasises it for Ashby toggles.
