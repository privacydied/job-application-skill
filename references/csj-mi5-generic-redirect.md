# CSJ — "Apply at advertiser's site" MI5 redirect is NOT a real ATS (2026-07-14)

For an MI5 / security-service role, the CSJ "Apply at advertiser's site" link resolves
to the bare `https://www.mi5.gov.uk/careers` generic careers page — there is **no
job-specific apply form**. The ONLY reason to skip these specific cards is that
mechanical one — **no driveable form** — NOT clearance. Clearance is NOT a blocker:
UK vetting (SC/DV) is granted THROUGH the role after offer, not held beforehand, so
apply to security-service roles wherever a real apply form exists and answer the
clearance question honestly (no current SC/DV, holds enhanced DBS, willing to be vetted).

Do NOT treat the generic MI5 careers URL as an external-ATS flow to drive.

Observed on SRE `jcode=2003197` ("Apply at advertiser's site" -> `mi5.gov.uk/careers`).

Contrast: a genuine external ATS link (e.g. The National Archives ->
`nationalarchives.wd3.myworkdayjobs.com/.../JR200863`) IS a real apply form and is
driveable. **Classify by whether the href is job-specific, not just by the presence of
the "Apply at advertiser's site" label.**

This is a CSJ-specific quirk that supplements `sites/civilservicejobs/NOTES.md` §Applying.
The review tooling could not edit the `sites/` file directly, so it lives here; port the
finding into that NOTES.md when convenient.
