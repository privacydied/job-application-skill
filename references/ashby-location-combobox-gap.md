# Ashby location combobox — label/placeholder detection gap (verified 2026-07-22)

Repro on Paddle `Web Designer` (jobs.ashbyhq.com/paddle/...), Ashby in-platform apply:

1. `atsform.combobox_pick("located","London")` → `FAIL combobox_pick: no select/combobox for 'located'`
2. `atsform.combobox_pick("Start typing","London")` → `FAIL combobox_pick: no select/combobox for 'Start typing'`
3. Field inspected live: `<input role=combobox placeholder="Start typing...">` — no `label[for]`, no `aria-label`. Value stays empty after both attempts.
4. Form submit (after Full Name / Email / Phone bound truthfully for Jane Doe) bounces:
   `BLOCKED — validation errors: ... Missing entry for required field: Where are you located` (name/email/phone WERE bound; only location empty).

## Why
`combobox_pick`'s field-finder matches on visible label text or `aria-label`/placeholder substrings. Ashby's location field carries neither a label nor an `aria-label` — only a placeholder — and the substring `located` does not appear in `Start typing...`, so detection fails *before* the free-text fallback can run. The documented `OK=freetext:London` outcome assumes detection succeeds; on Paddle it never does via the label/placeholder route, so the failure mode is `no select/combobox`, NOT the documented "commits but bounces at submit".

## Workaround (unverified — NOT tested this session)
Drive the setter directly: `cfx.evaluate` a React native-setter on the `input[role=combobox]` (mirror `atsform.combobox_pick`'s freetext commit), then Enter/blur. Expectation from `SKILL.md` residual limit: Paddle's structured-location validator still rejects free text at submit ("wants a city/region object"), so the field bounces regardless. Log `Blocked`, never a 3rd attempt.

## Lesson for the 2-attempt cap
When an Ashby apply hits a required "Where are you located?" that won't drive: one real attempt to bind identity + one location attempt exhausts the cap. Don't retry the label-based `combobox_pick` — it cannot find the field. Then `Blocked` (retryable on a backend/engine fix).

## Related: Ashby first-attempt form-render flake (reuse pattern)
On Paddle, the FIRST `ashby.py apply <cfg> --submit` returned `FAIL: form did not render after click / ABORT: form did not reveal` — a transient Ashby modal-timing failure, NOT a wall. A fresh `cfx.goto` + explicit `evaluate` click of the `Apply for this Job` CTA revealed the form (49 fields). Second `ashby.py apply --submit` then ran the real fill. So an Ashby `ABORT: form did not reveal` should be treated as a retryable transient: re-nav + retry once before logging `Blocked`. This is the legitimate 2nd attempt, not a 3rd. (Do not confuse with the location-combobox gap above, which is a genuine capability limit after the form DOES render.)
