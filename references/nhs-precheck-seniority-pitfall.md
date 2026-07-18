# NHS seniority false-drop (precheck.py)

## Symptom (verified 2026-07-17)
`precheck.py` screen drops NHS roles whose *title words* look senior
("Lead"/"Executive"/"Deputy"/"Head of"/"Portfolio") as off-profile — but in NHS
those words frequently denote **Band 6-7** (junior->mid), not senior management.
Confirmed false-drops on a live "digital" NHS harvest:

| Title | NHS band | Salary | precheck verdict | correct |
|---|---|---|---|---|
| Digital Delivery Executive | Band 6 | 39,959-48,117 | DROP "seniority word" | **keep** |
| Digital Learning and Skills Lead | - | 46,000 | DROP "seniority word" | **keep** |
| Digital Implementation Lead | Band 7 | - | DROP | correct (borderline) |
| Digital & Clinical Systems PM | Band 8a | 66k+ | DROP | correct |
| Digital Innovation Deputy Portfolio Lead | Band 8b | 75k+ | DROP | correct |
| Group Head of Clinical Applications | - | - | DROP | correct |

The title-word seniority rule is correct for **CSJ** (where grade encodes
seniority and the rescue path already exists) but over-reaches on **NHS**, where
band != title word.

## Why it matters
NHS is a top on-profile source for gov/health digital + IT-support roles (the
applicant's NHS COVID-19 App experience). Silently dropping Band 6-7 "Lead"
roles hides the exact junior->mid fit the run is hunting.

## Detection
After any NHS `feed.py | precheck.py` pass, re-scan the `drop` bucket for
`seniority word` reasons and open the JD's band line (NHS cards expose
`Salary: X to Y` / `Band N`). Band <=7 with pay <=~55k -> it's a false drop,
route to `keep`/`review` and apply.

## Fix (tool gap, not a one-off)
`precheck.py`'s seniority rescue currently special-cases CSJ only
(`_CSJ_HOST in url`). Extend it: when the source/url is NHS (`jobs.nhs.uk`),
downgrade a seniority-flagged title to `review` (open the JD to read the band)
instead of `drop`, the same way CSJ junior-mid grades are rescued. Don't blanket
rescue — Band 8a/b and "Head of"/"Director" stay dropped. Until patched, the
manual re-scan above is the workaround; do NOT hand-edit precheck output into the
tracker.

## Note
NHS apply is itself account-gated: every trust routes "Apply" to its OWN
downstream ATS (Jobtrain / Trac / Oleeo), each a separate account — even with the
NHS Jobs cred present. So fixing the screen recovers the *candidates*; the
per-trust account wall still gates submission.
