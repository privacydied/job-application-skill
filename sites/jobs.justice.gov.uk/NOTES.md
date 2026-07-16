# MoJ jobs.justice.gov.uk — 7-step wizard (HMCTS / MoJ postings)

Verified 2026-07-14 while attempting HMCTS Senior Business Analyst (jcode 2004059, jobId 19623).

## Flow
CSJ advert "Apply at advertiser's site" → `jobs.justice.gov.uk/careers/JobDetail/19623?entityId=19623`
→ "Apply" → `.../ApplicationMethods?jobId=19623&record=19623`
→ choose "Without CV" (manual entry; avoids CV-upload widget)
→ `.../Register?...` account creation (First Name 11300, Surname 11301, Email 11302,
  Confirm 15708, Password 11305, Confirm 11306, I-agree 11307)
→ wizard steps (URL changes per step):
  - Eligibility  `.../Eligibility`      (selects 19154 rt-work, 19159 nationality-req,
                                         19171 meet-eligibility; checkboxes 19161[] UK National,
                                         19162[] ILR/British)
  - General      `.../RegistrationGeneralInfo1`  (~45 fields; address, NI, employment status…)
  - Success Profile `.../RegistrationSuccessProfile` (free-text BA statements)
  - E&D          `.../RegistrationEquality`  (diversity monitoring)
  - Declaration  `.../RegistrationDeclaration`
  - Submit

## Account
Created 2026-07-14 (you@example.com / pw in ats-credentials.csv row
`jobs.justice.gov.uk (MoJ jobs portal)`). Step counter after account = "2/5".

## FIELD-BINDING — RESOLVED (earlier diagnosis was WRONG)
Programmatic `evaluate` (cfx + browser_console) DOES bind inputs to Angular when the
event is dispatched correctly: `select.value=opt; dispatchEvent('change')` binds selects;
`input.value=...; dispatchEvent('input')` binds text. First/Last name + all ~40 General
selects (Title, NI=No, employment status=Non Civil Servant, nationality-req=Yes,
right-to-work=Yes, English=Yes, veteran/redeploy/surplus/etc=No, text-consent=Yes)
persist and the step advances when valid. The earlier "SPA drops values" read-back=None
was a transient node-replacement artifact during re-render, NOT a binding failure.

## BLOCKER — Country dropdown has no options + state won't persist + camofox flake
1. Country select (19308) renders only the "Select a country" placeholder — its
   ~200-option list is loaded async and does NOT populate via evaluate (heavy list
   times out → 500; clicking/focus doesn't trigger load). MoJ labels the missing field
   "County: This field is required" but there is NO separate county field — it IS 19308.
2. MoJ step state does NOT persist across re-renders. After a "Save and Continue" click
   the form re-renders EMPTY (Title/Preferred First Name/all fields reset to required).
   So fields must all be set + saved in ONE coherent pass, which the flaky backend won't
   allow for a 45-field form.
3. camofox REST backend (localhost:9377) intermittently 500s (heavy payloads) AND 400s
   (ba1c87eb tab wedged) — unreliable for multi-field setting.

## ROOT-CAUSE (DEFINITIVE, 2026-07-14)
The Country field (19308) is a CUSTOM async dropdown widget, NOT a standard <select>:
- In the `evaluate` context `s.options` is EMPTY (`[...s.options].length === 0`; the
  one-pass driver returned `19308:NO[]`).
- The browser SNAPSHOT shows ~200 country options — but those are JS-rendered widget
  nodes, NOT real `<option>` children of the <select>. They only exist transiently
  during focus/click interaction.
- No @eN element ref is assigned to the control (snapshot floods the widget's rendered
  option list and never tags the select itself), so browser_click/browser_type can't target it.
THEREFORE it is impossible to set Country programmatically: no queryable options, no
addressable ref. A human must focus the control (widget populates) and pick "United Kingdom".
PLUS: MoJ step state does NOT persist across re-navigates (re-nav reset Title etc. to
empty), and camofox REST flakes (500 heavy / 400 wedged tab). All fields must be set
+ saved in ONE pass with the widget already interactive — which can't happen for Country.
NET: HMCTS SBA General Information cannot be completed automatically. No junk submitted.

## How a human finishes (VNC as you@example.com; MoJ account already created)
1. Focus Country → pick "United Kingdom" (unlocks County + UK-mobile fields).
2. Fill County (e.g. "Greater London"), UK mobile 07700900000, text-consent Yes.
3. Save and Continue → Success Profile (BA behaviours: Communicating & Influencing,
   Working Together, Making Effective Decisions, Changing & Improving) → E&D → Declaration → Submit.
Field map above is reusable.
