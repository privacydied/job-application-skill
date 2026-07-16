# CSJ "Apply at advertiser's site" — advertiser ATS inventory (live findings)

Companion to `sites/civilservicejobs/NOTES.md` "Applying" section. That section says
external-ATS postings are "normal external-ATS flow, `atsform.py apply` etc." — but
the actual ATSes vary in automatability. This file records per-advertiser ATS
behaviour seen on CSJ so a future run knows what it's walking into BEFORE opening
the form.

## HMCTS / MoJ — `jobs.justice.gov.uk` (verified 2026-07-14)

- CSJ advert "Apply at advertiser's site" → `https://jobs.justice.gov.uk/careers/JobDetail/<id>?entityId=<id>`
  → "Apply" → `https://jobs.justice.gov.uk/careers/ApplicationMethods?jobId=<id>&record=<id>`.
- This is a **Ministry of Justice 7-step wizard**, NOT a simple one-page ATS:
  1. Create Account · 2. Eligibility · 3. General Information · 4. Success Profile ·
  5. Equality And Diversity · 6. Declaration · 7. Submit.
- Step 1 forces a **new account per posting** (email/password with you@example.com
  per the standing ATS-account rule; record in `ats-credentials.csv`). The account
  creation step WORKS (verified 2026-07-14: account created, Eligibility advanced).
- Step 4 (Success Profile) needs **free-text statements** (gov Success-Profiles
  personal-statement / behaviour format) — author per JD, not auto-fill from defaults.

### What ACTUALLY blocks automation (corrected 2026-07-14 — OLD NOTE WAS WRONG)

The earlier note claimed "the MoJ SPA does NOT capture programmatic input / NOT yet
automated." That is FALSE. Programmatic `evaluate` (camofox `cfx.py` AND the native
`browser_*` tools) DOES bind inputs to Angular when the event is dispatched correctly:
- selects: `el.value = optValue; el.dispatchEvent(new Event('change',{bubbles:true}))`
- text/textarea: `el.value = v; el.dispatchEvent(new Event('input',{bubbles:true}))`
All ~40 General-step selects (Title, NI=No, employment status=Non Civil Servant,
nationality-req=Yes, right-to-work=Yes, English=Yes, veteran/redeploy/surplus/etc=No,
text-consent=Yes) + name fields persist and the step advances when valid. The earlier
"read-back None = SPA drops values" was a TRANSIENT node-replacement artifact during
re-render + a camofox REST flake, NOT a binding failure.

**The real, current blocker:** the **Country dropdown (field 19308) renders with ONLY
the "Select a country" placeholder** — its ~200-option list is loaded ASYNCHRONOUSLY
and does NOT populate in the automated context (clicking/focusing does not trigger the
load; `options.length` stays 1). MoJ's validation labels this missing field
"County: This field is required" but there is NO separate county field — it IS the
Country select. Without a selectable option the General step cannot be completed, so
the wizard cannot reach Success Profile / E&D / Declaration / Submit.

**Secondary:** the camofox REST backend (`localhost:9377`) intermittently returns
`HTTP 500` on `evaluate` — both large payloads AND some small ones. When this happens,
the native `browser_*` tools (browser_type / browser_click / browser_console) drive the
SAME underlying camofox tab (shared session/cookies) and fire real DOM events Angular
captures — a reliable fallback for SPA field binding when the REST layer flakes. Also
useful: a single `None`/`500` on a large `evaluate` read is a flake, not a hard stop —
retry or use a smaller query.

### Status 2026-07-14
HMCTS Senior Business Analyst (jcode 2004059, MoJ jobId 19623) = **Blocked (retryable)**.
Account created, Eligibility passed, General ~85% filled (all selects + names + NI +
employment + nationality + text-consent bound) — ONLY the Country dropdown (no options)
+ the UK-mobile-number field (19314, appears after "Do you have a UK Mobile"=Yes) remain.
NO application was submitted (General validation failing = not committed). To finish:
user-VNC the Country pick + mobile, then Success Profile / E&D / Declaration. Full field
map, account creds, and the exact blocker are in `sites/jobs.justice.gov.uk/NOTES.md`.
HMCTS Service Desk Analyst (jcode 2003537) CLOSED 14-Jul-2026 (deadline passed) — not
submitted; same MoJ wizard, same Country blocker.

### How to resume / finish
1. Log in to MoJ with the account in `ats-credentials.csv` (row `jobs.justice.gov.uk (MoJ jobs portal)`).
2. Resume the wizard at `.../RegistrationGeneralInfo1?jobId=19623&record=19623` — most
   General fields persist server-side per account; only Country + mobile need filling.
3. If the Country options still won't populate, complete via VNC (real browser populates
   them on interaction). Then Success Profile (author BA free-text), E&D, Declaration, Submit.
4. Reuse the field map in `sites/jobs.justice.gov.uk/NOTES.md`.

## Hackney Council — Lumesse TalentLink (`emea3.recruitmentplatform.com`)

See `sites/hackney/NOTES.md`. Hackney "Apply Now" → TalentLink external ATS. Automatable
via `atsform.py apply` (Hackney runs anonymised applications; the DPS consent is a hidden
`<select name="dps">` set to 'true'). The board's live remainder is often social-care /
managerial / senior — precheck can yield 0 on-profile on a ~16-vacancy board even when
one Tier-A yield exists (the Associate Content Designer was filled via a one-off
TalentLink manual in an earlier run).
