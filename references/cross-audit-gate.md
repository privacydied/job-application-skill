# cross_audit.py — FINAL pre-drive safety gate

Shipped at `scripts/cross_audit.py` (2026-07-24). Run it as the LAST step
before driving any `convertible` row, on top of `convertible_preaudit.py`.

## Why it exists (verified trap)
`convertible_preaudit.py` matches the tracker on the feed's EXACT role string.
A feed role like `Designer Advocate (London, United Kingdom)` does NOT match a
tracker row stored as `Designer Advocate`, so preaudit flags it `REAL-DRIVABLE`.
Driving it via `gh_apply` then DOWNGRADES the real `Applied` row to `Blocked`
(the `redrive-destroys-applied-row.md` trap). In the 2026-07-24 drive this
destroyed the Figma `Designer Advocate` `Applied` row on a prior pass.

## What it adds over preaudit
1. **role_base normalisation** — strips the trailing `(Location, Country)`
   qualifier before the Company+Role tracker match, so re-drives are caught.
2. **url-prefix dedup** (same as preaudit) — catches cross-URL cross-posts.
3. **lane gate** — drops off-lane hardware/MEP/recruiting titles via
   `check_title` (graceful if `check_title` import fails).
4. **AI-attestation-wall filter** — drops companies requiring a mandatory
   "I certify I used only my own words / no AI" oath the applicant cannot
   truthfully certify through the agent. Default set: `canonical (ubuntu),
   canonical, ubuntu`. Override with `--ai-wall "..."` or disable with
   `--no-ai-wall`.

It prints only the rows safe to drive for real, plus a reject histogram and
`GENUINE NEW ON-LANE DRIVABLE: N` so an unattended loop can read the count.

## Usage
```
python3 scripts/cross_audit.py /tmp/atsdirect.json
python3 scripts/cross_audit.py /tmp/atsdirect.json /tmp/ifyoucould.json ...
python3 scripts/cross_audit.py            # defaults to /tmp/atsdirect.json
python3 scripts/cross_audit.py /tmp/atsdirect.json --no-ai-wall
```

## SKILL.md pointer
NOTE: a one-line pointer was intended in SKILL.md's `PRE-DRIVE CROSS-AUDIT`
section, but `skill_manage` enforces a 100,000-char file-size guard and the
live SKILL.md is ~100,570 chars, so the inline edit could not be applied this
turn. Add this line to that section on the next maintenance pass:

> Run the STRICTER `scripts/cross_audit.py /tmp/atsdirect.json` as the FINAL
> gate — it normalises the role (strips the trailing `(location)` qualifier)
> before the Company+Role match and drops off-lane + AI-attestation-wall
> companies, printing ONLY the genuinely-new on-lane drivable set.
