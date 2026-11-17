# Title-screen parsing pitfalls (check_title.py)

- `check_title.py`'s `parse_target_roles()` strips parentheticals from target-roles.md bullets. A line like `- QA Technician (IT hardware)` therefore registers as the bare phrase `QA Technician` and matches off-profile manufacturing/food QA postings. Put the domain word inside the phrase itself: `Hardware QA Technician`.
- A spaced dash (` - ` or ` — `) starts a description and is cut during parsing. Use ` / ` only for genuine title synonyms.
- Single-word phrases are silently dropped; a tier marker `(A)`, `(B)` or `(C)` sets the tier; adding a bullet under a numbered `## N.` section makes that title eligible immediately with no code change.
- After editing target-roles.md, verify with `python3 sites/_common/scripts/check_title.py --self-test` and spot-check titles. Include an off-profile control such as `Field Service Engineer (Pumps)`, which must keep `discipline_flag=true`, to confirm the guards still hold.
- To make a new title actually surface, add a matching board+query row to searches.csv as well; the title list alone only affects screening, not sourcing.
