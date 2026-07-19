# External LinkedIn / Indeed — employer-ATS account-wall reality (2026-07-18)

SKILL.md §Forbidden says the EXTERNAL LinkedIn/Indeed path (Apply button that leaves
the platform for the employer's own ATS) "IS a real hard application and counts."
That is *technically* true — but in practice, at this depth, the external path is
almost entirely **employer-ATS account-walled**, which makes it a login wall, not
a clean submission channel. This note records what was actually observed so a future
session isn't burn passes re-discovering it.

## What the external path actually looks like (observed)

For each fresh external LinkedIn posting, the flow is:
1. Open `linkedin.com/jobs/view/<id>` → classify the Apply button.
   - Blue "Easy Apply" modal (`openSDUIApplyFlow=true`) = **FORBIDDEN**, skip.
   - Plain "Apply" with `safety/go?url=…` = external → click-follow.
2. LinkedIn's `safety/go` redirect lands on the **employer ATS**, e.g.:\n   - `job-boards.eu.greenhouse.io/<emp>/...` → **GUEST-DRIVABLE** (no account; fill name/email/CV + submit).\n   - `jobs.ashbyhq.com/<emp>/...` → **GUEST-DRIVABLE** (use `sites/ashbyhq/scripts/ashby.py`; Location is a typeahead — type then CLICK the dropdown option, value-set alone fails validation).\n   - `jobs.micro1.ai/...` → guest form but final step has OPAQUE required number/text fields (no labels) → skip (HARD STOP: can't truthfully answer).\n   - `careers-en-<emp>.icims.com` → iCIMS login (account wall).\n   - `jobs.ea.com` → account-required application methods (email-verify wall).\n   - `cgi.joyn.com` → SSL cert error in camofox (hard block).\n   - Workday / join.com / bespoke — usually account-walled or Google-OAuth-walled.\n3. **⚠️ CORRECTION (2026-07-19): guest-drivable ATSs are NOT "the exception."** The earlier\n   "guest-applyable are the exception, not the rule" claim was based on a thin sample and is\n   WRONG. Verified live this session: **Greenhouse and Ashby are fully guest-drivable** and\n   produced real `Applied` rows (Rightmove/Greenhouse, hyperexponential/Ashby, Capco/Greenhouse)\n   with no account. **Always test the actual ATS first** — don't pre-skip an external posting on\n   the assumption it's walled. Walled ones observed: iCIMS, EA (email-verify), CGI (SSL),\n   Workday (often account). Guest-drivable: **Greenhouse, Ashby** (lead with these).\n\n## ATS classification cheat-sheet (verified 2026-07-19)\n| ATS domain | guest-applyable? | driver |\n|---|---|---|\n| job-boards.eu.greenhouse.io / job-boards.greenhouse.io | YES | `atsform.upload` + fill, submit "Submit application" |\n| jobs.ashbyhq.com | YES | `ashby.py apply <cfg>` then `submit` (Location typeahead needs dropdown click) |\n| jobs.micro1.ai | form yes, opaque required fields → skip | — |\n| careers*.icims.com | NO (account) | record wall |\n| jobs.ea.com | NO (email-verify) | record wall |\n| cgi.joyn.com | NO (SSL cert error in camofox) | record wall |\n| myworkdayjobs.com | usually NO (account) | record wall |\n| join.com | NO (Google-OAuth) | record wall |\n\n## Throughput consequence (CORRECTED)\n\nAt the 351→477 depth, the external LinkedIn path is a REAL, productive channel for the\nright ATS:\n- ~half the raw postings are Easy-Apply (forbidden — skip).\n- of the EXTERNAL ones: **Greenhouse + Ashby are guest-drivable and yield real `Applied`**;\n  iCIMS / EA / CGI / Workday / join.com are account/SSL walls (log `Blocked`).\n- So prioritise external postings whose ATS is Greenhouse or Ashby — they convert. Route the\n  walled ones to `accounts.py` (per-employer) only if the user wants them pursued.\n\nSo "drive the external path" IS a viable route to +126 — **filter for Greenhouse/Ashby hosts**\nand apply those, rather than dismissing the whole channel.

## Location screening still applies

Every external posting still needs title + location + seniority screening (the
`feed.py`/audit "external" list is NOT pre-screened the way `precheck` screens the
Easy-Apply families). Observed off-profile traps among external postings:
- Redhill / Edinburgh / Manchester / remote-but-US — location skip.
- "Senior Principal Business Analyst" / "Senior Business Analyst" — seniority_flag=True, skip.
- "Business Analyst Intern (6 Months)" London — on-profile, BUT its join.com ATS
  is Google-OAuth-walled.

## The honest unblock (report ONCE, don't re-spam)

1. **Employer-ATS accounts.** If the user creates/logs in to the specific employer
   ATSs (join.com, iCIMS, Workday, Greenhouse, Lever, …) and hands over a
   live session, those external postings become drivable. Right now they're login walls.
2. **Guardian in-platform** is the higher-leverage live channel: `apply.py` does all
   the fill/CV/cover work and exits 3 at the "Send application" reCAPTCHA v2 —
   a documented **human noVNC gate** (`http://nasirjones:6080/vnc.html`). The user
   solves that one captcha per staged role; everything else is autonomous.
3. **Parliament / TfL / BBC** — no credential row; self-register (no-CAPTCHA) and
   store in `ats-credentials.csv`, or report as account walls.

## Do NOT

- Pad the count with Easy-Apply (forbidden; if a prior run logged EA rows,
  delete exactly those rows and re-verify with `tracker_stats.py --count`).
- Re-drive a CSJ↔applicationtrack cross-posted role (different URL, same vacancy —
  see the cross-URL duplicate gap in SKILL.md §applicationtrack).
- Declare the external path "exhausted" — it's account-walled, which is a LOGIN
  WALL, not a data-scarcity ceiling.
