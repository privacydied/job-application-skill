# Driver re-drive guard + AI-attestation hard stop (generalized)

Companion to `references/redrive-destroys-applied-row.md` and the SKILL.md
pre-drive cross-audit. Captures two durable rules a 2026-07-24 run proved must be
enforced in the DRIVERS, not just the playbook text.

---

## 1. Pre-drive cross-audit must cover ALL terminal states, not just `Applied`

The SKILL.md cross-audit tells you to skip a row already in the tracker. The trap that
actually fired 2026-07-24: `gh_apply.py` logs `Blocked` UNCONDITIONALLY on any
no-confirm submit and does NOT check prior tracker status. Driving a Canonical (Ubuntu)
role that was already `Skipped` from a prior session DOWNGRADED it to `Blocked` —
destroying a legitimate terminal decision (the role was skipped because it needed a
false "no-AI" attestation). Same root cause as the `Applied`→`Blocked` variant, but the
`Skipped`/`Blocked` directions were NOT covered by the original guard.

**Required durable guard (apply to EVERY driver that logs on a no-confirm submit):**
`gh_apply.main()`, `ashby drive_ashby.py`, `wttj apply.py send`, `fill_csj_eeo.py`.
At entry, before any fill/submit:

```python
# match on url prefix + role_base (strip trailing "(City, Country)" qualifier)
if status in ("Applied", "Skipped", "Blocked"):
    print(f"ALREADY_{status} skip")
    return 0
```

Key points:
- The guard must match on **both** `url.split('?')[0].rstrip('/').lower()` AND
  `role_base = re.sub(r'\s*\([^)]*\)$','', role).strip().lower()` against
  `(Company, role_base)` — a feed `Role` suffix (e.g. "(London, United Kingdom)") can
  slip a url-only match past `tracked_cr`.
- It must treat `Skipped` and `Blocked` as terminal too — do NOT overwrite a prior
  `Skipped`/`Blocked` with a fresh `Blocked`.
- If a driver already corrupted the row, restore the PRIOR `Status` + strip the false
  note via read-mutate-write in ONE `with open(...,'w')` block. Never leave a fabricated
  `Blocked` over a real `Skipped`/`Applied`.

Verified incident 2026-07-24: restored `Canonical (Ubuntu) | UX Designer - Design
systems` and `| Visual Designer` from `Blocked` back to `Skipped` (their prior state),
appending the real reason to Notes.

---

## 2. Mandatory "no-AI" attestation = HARD STOP for this applicant

SKILL.md already states CSJ's "Use of AI in Applications" notice is PERMISSIVE (not an
attestation) and must not trigger the refuse/stop path. The OPPOSITE case also exists
and is a hard stop for Jane:

Some employers (e.g. **Canonical/Ubuntu**) require a checkbox attesting
*"I agree to use only my own words. I understand that plagiarism, the use of AI or other
generated content will disqualify my application."* — usually paired with several
bespoke MANDATORY long-form essays (Canonical asks ~4: most complex web design project,
design patterns embraced/discarded, companies innovating in web design, high-school
performance justifications, plus degree history).

The applicant (Jane Doe) is a **daily AI-agentic-tooling power-user** (Claude Code,
Hermes, Codex — stated in `references/applicant-profile.md`). Certifying "I use only my
own words / no AI" would be a **false attestation**.

Rule:
- A required no-AI attestation is a HARD STOP. Do NOT auto-certify and force the submit.
- Log `Skipped` with the reason ("required no-AI attestation — false for this applicant")
  and route the role to the user (who may truthfully certify on their own device).
- Do NOT pad the count by submitting a false attestation. This is the AI-attestation
  wall, distinct from CSJ's permissive notice — do not confuse the two.
- Recognition cue: the form carries a label like *"During this application process I
  agree to use only my own words… use of AI or other generated content will disqualify
  my application"* (exact wording varies). Treat its presence as terminal `Skipped`.

This is why the 5 on-lane Canonical (Ubuntu) design roles are correctly `Skipped`, not
drivable — they are real, on-lane, agent-reachable forms that become un-submittable the
moment the attestation must be truthfully answered.
