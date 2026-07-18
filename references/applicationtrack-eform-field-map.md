# applicationtrack.com (VacancyFiller) — verified eform field map + fill notes

Captured 2026-07-17–18 driving MI5 Platform Engineer Ref. 3781, Software Engineer 3685, and
Lead Cyber Research Engineer 3789 end-to-end. Reusable for any MI5/MI6/GCHQ vacancy whose
application opens the eform directly (NOT a Cubiks test gate — see
`references/applicationtrack-birth-facts-blocker.md`). One MI5 credential row spans all
three tenants; the eform URLs are `/candidate/eform/<ID>/page/N`.

## Apply-entry mechanism (no visible Apply button)
The vacancy detail page renders only a careers-info link. The real apply action is a POST
form whose `action` ends in `/opp/<REF>/apply/en-GB`. Find it and click its submit button:
```js
(() => { const f=[...document.querySelectorAll('form')]
  .find(f => (f.getAttribute('action')||'').includes('/apply'));
  if (f) { const b=f.querySelector('button[type=submit],input[type=submit]'); if (b) b.click(); }
  return f ? 'CLICKED' : 'NO_FORM'; })()
```
You then land on `/candidate/eform/<ID>/page/1`. The eform ID is stable for that application.

## cfx.evaluate reliability (read first)
`cfx.evaluate` (python module) intermittently 500s on these eform pages even when the page
renders fine (phantom — backend healthy), and can throw a stale-tab `NoneType` in
`compute_referer`. Use the shell wrapper instead:
`bash sites/_common/scripts/cfx.sh eval '<js expression>'` — same REST endpoint, no 500s.
Also call `cfx.ensure_tab(persist=False)` once before `cfx.goto` to clear a stale tab
handle. Persist any fresh tab id to BOTH `.jobenv.run` and `.jobenv.persist`. Never fan out
(browser wedge).

## Section order (eform page/1 ... page/7)
1. Personal Details · 2. Minimum Eligibility · 3. Offer Of Interview (OOI: disability +
   OOI consideration) · 4. Adjustments (reasonable adjustments + special arrangements) ·
   5. Security Vetting · 6. Equal Opportunities · 7. Submit.
The 7 `a.jump-to-page` anchors list each with its page href. **Direct `/page/N` URL nav does
NOT switch VacancyFiller pages** (position tracked via hidden `page_number`/`next_page_num`
fields) — advance with the `continue_button`/`submit_button` POST, then re-open the eform to
read the refreshed tracker.

## Field IDs (MI5 3781/3685/3789 — IDs are VacancyFiller-generated; re-read per vacancy with
## cfx.sh eval, but the SHAPES below hold)
- **Personal Details page/1**: `386995` heard-about-job (select; option VALUE VARIES per
  eform — 3781/3789 had 5308=CSJ Website, 3685 had 984=Organisation Website; read the
  options live) · `16181` Email · `16214` Title (29=Mr) · `16169`/`16175` First/Last name ·
  `16250` Previous Last Name (set "N/A" if none) · `31643` NINO · `31776` Country
  (1822=United Kingdom) · `31790`/`31806` address/Town · `31824` County (13456=Greater
  London) · `31846` Postcode ([postcode], **no commas**) · `16232` how-long-lived-here ·
  `31702` Home tel · `29967` UK mobile (1=Yes) · `41520` Mobile (`+447700900000`, no spaces)
  · `31685` preferred-contact (numerics only `7804605448`) · `388025` British Citizen (1=Yes) ·
  `1027150`/`1049834` AI + travel confirmations (click the radio whose `label[for=id]` text is
  "Yes"). **County is a DEPENDENT select — set Country first, then it populates.** Role may
  add a required select (e.g. 3685 `1024141` preferred-location, London=770) — scan for it.
- **Minimum Eligibility page/2**: residency radios `985577` (age>=18 -> Yes), `985581` (lived UK
  7/10 -> Yes), and `985585/589/593/597/601/605/609/613/617/621` (all No — "if you have NOT
  lived 7/10, is it because…" sub-questions; applicant has lived 7/10 so No).
- **OOI page/3**: `931117` disability (730=No) · `931121` OOI consideration (2=No).
- **Adjustments page/4**: `18539` reasonable-adjustments (2=No) · `18536` special-arrangements
  (2=No).
- **Security Vetting page/5**: `421796` = **Date of birth** (Day/Month/Year selects; DOB
  [DOB]) · `422067` Today's date (Day/Month/Year) · `421791` agree-to-terms (click the
  radio whose label contains "agree to the terms") · `421803` drug-policy (Yes) · `422410`
  undischarged bankrupt (No). All from profile.
- **Equal Opportunities page/6** — REQUIRED EEO (`*`) fields; fill truthfully from profile,
  do NOT leave blank (blank blocks Submit even though the skill's general rule is "optional
  EEO -> prefer not to say" — here they are mandatory): `27849` Ethnic Origin (Mixed -> "Any
  other Mixed/Multiple ethnic background") · `17697` ethnic "please specify" ("Mixed Caribbean
  and North African") · `17709` Religion (Jewish) · `17712` religion details ("Jewish") ·
  `17694` Gender (Male) · `17706` Disability (No/none) · `17718` Sexual Orientation
  (Heterosexual) · `17703` Age Range (30-34). The socio-economic selects (938519/555/591/606/
  621/636/651/666) + their "please specify" fields (938534/938570) — you do NOT hold those
  facts; set the selects to "Prefer not to say" and the specifies to "Prefer not to say".
  Profile section Demographics holds all of these.
- **Submit page/7**: `387216` memorable-word (>=5 chars, a private word — not real PII) ·
  `387231` hint (textarea) · `387245` consent checkbox (click to check). Then `submit_button`.

## Fill mechanics that worked
- Text: `el.value=...; el.dispatchEvent(new Event('input',{bubbles:true}));
  el.dispatchEvent(new Event('change',{bubbles:true}))`.
- Select: `s.value=...; s.dispatchEvent(new Event('change',{bubbles:true}))`.
- Radio by label: find `input[type=radio][name=...]`, click the one whose
  `label[for=id].innerText.trim()` matches "Yes"/"No". (Option value suffixes like `_1`/`_2`
  are NOT reliable — match on the label text, not the value.)
- Submit appears on page/7 only when all 6 content sections validate. After Submit the
  eform may advance to a "Helpful Hint" eform — the main app IS submitted; verify
  "Submitted <datetime>" on the candidate application list and capture that as `--proof`.

## SOURCE OF TRUTH = the section-tracker class, not "I clicked continue"
Each `a.jump-to-page` link's **parentElement className** carries the real completion state:
`tracker_stat_mandatory_complete` / `tracker_stat_complete` / `tracker_stat_incomplete`.
Read it after every step — a section that "saved" can still be `incomplete` (a hidden required
field). A section is done ONLY when its class shows complete. This is how you catch the
County/role-specific traps below before they silently block Submit.

## Pitfalls (2026-07-18 — each cost a wasted/incomplete application)
1. **County (31824) is DEPENDENT on Country (31776).** Set Country first, `sleep 2`, THEN set
   County — if both are set in the same tick County's options haven't repopulated and the value
   reverts to empty -> PD1 stays `incomplete` ("County - This field is required").
2. **Role-specific required fields vary per eform.** MI5 3685 required "preferred location"
   (`1024141`, London=770); 3781/3789 did not. After filling PD1, SCAN for empty `required`
   fields (`[...required]...`) and fill any found before continuing. Never assume the standard set.
3. **Button semantics differ per eform.** PD1 may expose `continue_button` (advances to the next
   section) OR `submit_button` (saves current section, returns to the tracker view). Both are
   valid — click whichever exists, then verify the tracker class. Do not assume `continue_button`.
4. **Phone format is enforced.** Must be `+447` + 9 digits, no spaces (e.g. `+447700900000`);
   preferred-contact = numerics only (`7804605448`). A `+44 7...` with a space fails validation.
5. **Equal Opportunities "Mixed - Other" (843) and "Jewish" (505) reveal required "please
   specify" text fields** (`17697`, `17712`). Leaving them empty keeps EO `incomplete`. Fill
   them ("Mixed Caribbean and North African" / "Jewish"). The socio-economic selects
   (938519/555/591/606/621/636/651/666) + their "please specify" fields (938534/938570) — you
   do NOT hold those facts; set the selects to "Prefer not to say" and the specifies to
   "Prefer not to say".
6. **Never log an app without a confirmation artifact.** A submitted form shows
   "Thank you, your application has been submitted" and the candidate list shows "Under review".
   If the section tracker still shows `incomplete` after your final submit, the app is NOT
   submitted — do not log it (log `Applied?` at most).

## Verified per-section loop
fill section fields -> click the present button (continue OR submit) -> **read tracker class,
confirm complete** -> next section. Only after Submit shows "Thank you" do you screenshot
(`cfx.sh shot applications/<slug>/confirmation.png`) and `log-application.py --proof <path>`.

## Bulk-driver warning
A blind driver that fills all 7 sections then submits in one pass FAILS: it clicks `submit_button`
on an incomplete PD1 (submitting an incomplete application) and never verifies per-section.
Drive section-by-section with verification. Do NOT ship a `/tmp` orchestrator (banned by
SKILL.md Step 1) — the technique above is the deliverable, not a script.
