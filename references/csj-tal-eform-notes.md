# CSJ "Apply and further information" — TAL eform (verified 2026-07-14, updated 2026-07-15)

CSJ's own application flow ("Apply and further information" on the advert) opens a
**TAL eform** at `cshr.tal.net/vx/.../candidate/eform/<ID>` (NOT the
`index.cgi?SID=` links — those are one-shot). Section 1 (basic info) is
**automatable** via `sites/civilservicejobs/scripts/tal_eform.py`. Section 2
(the assessed supporting evidence) is a **separate eform** and is **NOW SOLVED**
(2026-07-14: UKEF + OFGEM + CPS all submitted end-to-end via `tal_sec2.py`;
2026-07-15: Cabinet Office Business Analyst submitted end-to-end via both drivers).
Earlier the skill claimed Section 2 was an "unresolved submit wall" — that was
wrong; the wall was a driver bug, not the site. This note is the corrected truth.

## Driver (Section 1)
`python3 sites/civilservicejobs/scripts/tal_eform.py <eform_base_no_slash> <spec.json> --max <N>`
- Fills by **stable CSJ field name** `datafield_NNNNN_1_1` (names are
  reused across all CSJ campaigns — one adapter serves every CSJ-native role).
- Resolves **radios/selects by VISIBLE LABEL TEXT**, not position/value
  (option `value`s are opaque numbers; radio labels are `for`-linked sibling
  `<label>`s or `e.labels[0]`, NOT wrapping `<label>` parents).
- Radios/checkboxes MUST be set with a native `element.click()` (Knockout-bound
  React-like SPA: setting `.checked=true` + dispatching synthetic `change` does
  NOT register; a real `click()` does). Text/textarea use the prototype
  `value` setter + `input`/`change`/`blur` dispatch.
- Steps: navigate to page/1, then advance by clicking **Continue** (which SAVES
  the current page); on the final Declaration page the button is **"Submit"** not
  "Continue" — `_continue()` falls back to Submit when no Continue exists.
- Each page's data only persists if you advance via the in-page Continue
  button; a raw `navigate(/page/N)` reload drops the unsaved page. Walk by
  Continue-chain, never by URL-jumping.

## Field quirks that blocked this run (all solved in the driver)
- **Page-4 Diversity has 3 `required` text inputs that look conditional but
  aren't:** `datafield_97665` (gender self-describe), `datafield_97658`
  (sexual-orientation self-describe), `datafield_35261` (other-ethnicity
  specify). Fill them even when Jane picked a non-"other" radio
  ("[your gender]" / "[your orientation]" / "[your ethnicity]") or the page-4 save silently
  fails with "Diversity monitoring problem" and the flow won't advance.
- **Declaration checkbox** (`datafield_22499_1_1`) must be ticked
  *immediately before* Submit on the final page — a fresh reload of page 5
  loses the tick and Submit returns "Select if you agree to our terms".
- **Ethnicity**: Jane is [your ethnicity] → broad group
  "Mixed / multiple ethnic groups", sub "[your ethnicity]"
  (NOT "White" / "Any other White background").
- **Socio-economic** radios (178072/178075/178114): option text is
  "Prefer not to say" (the driver spec said "Prefer not to disclose" → no match).
- **`datafield_178075_1_1` is EMPLOYMENT STATUS, not socio-economic** — options are
  Employee(48020) / Self-employed with employees(48021) / **Self-employed/freelancer
  without employees(48022)** / Not working(48023). Jane = 48022. ⚠️ A spec value of
  "Self-employed" resolves to **48021 (WITH employees) — WRONG**. Use the substring
  "without employees" to match 48022. This was a silent data-accuracy bug (wrong value
  saved, no validation error) that cost a full re-run.
- **Diversity page is NOT just 3 text inputs** — see the full field map below. The
  page also requires age-group, ethnic-group, ethnicity, and religion SELECTs; leaving
  any of them on "Select" is why Section 1 kept reporting "Diversity monitoring
  problem" and the Declaration Submit button never rendered.
- **Eligibility page (non-civil-servant):** answering "Are you already a civil
  servant?" = **No** still forces TWO extra required fields:
  `datafield_177937_1_1` "Home department" (select a REAL department value, NOT
  the placeholder "Select") and `datafield_87776_1_1` "Other organisation" (text,
  e.g. "Self-employed contractor"). Leaving 177937 on "Select" is the #1 reason
  the Eligibility Continue silently fails.

## Complete Diversity monitoring page field map (verified 2026-07-15, eforms 56992962 & 56996507)
The old note's "3 required text inputs" was INCOMPLETE — the page has 14 fields and
MOST are required. Leaving any select on "Select" is why Section 1 reported
"Diversity monitoring problem" and the Declaration Submit never appeared. Canonical
filled spec: `templates/csj_s1_spec.json`.
- `datafield_36491_1_1` (radio) disability → **No** (730)
- `datafield_12784_1_1` (radio) gender → **Man** (27)
- `datafield_97665_1_1` (TEXT) gender self-describe → **"Male"** (required even when Man)
- `datafield_35296_1_1` (radio) sexual orientation → **[your orientation]** (4012)
- `datafield_97658_1_1` (TEXT) sexual-orientation self-describe → **"[your orientation]"** (required even when [your orientation])
- `datafield_53438_1_1` (SELECT) age group → **30-34** (14529)
- `datafield_54157_1_1` (radio) national identity → **British** (14553)
- `datafield_53446_1_1` (SELECT) ethnic group → **Mixed / multiple ethnic groups** (14514) [match substring "Mixed"]
- `datafield_35302_1_1` (SELECT) ethnicity → **[your ethnicity]** (4032) [match "[your ethnicity]"]
- `datafield_35261_1_1` (TEXT) other ethnicity → **[your ethnicity]** (required)
- `datafield_53463_1_1` (SELECT) religion or belief → **Jewish** (14523)
- `datafield_178072_1_1` (radio) socio-economic parental occupation → **Prefer not to say** (48019)
- `datafield_178075_1_1` (radio) employment status → **Self-employed/freelancer without employees** (48022) — see warning above; match "without employees"
- `datafield_178114_1_1` (radio) school type → **Prefer not to say** (48034)
- `datafield_165298_1_1` (TEXT) — postcode, pre-filled (e.g. "[postcode]"); leave as-is.
Ethnicity is expressed via the TWO SELECTs (53446 broad + 35302 sub) + the 35261 text,
NOT a radio broad/sub pair as the old note implied.

## Two-section flows
Section 1 (basic info) submits via the page-5 **Submit**. Section 2
(supporting evidence — the assessed part: CV + personal/behaviour statements)
is a **separate eform** (its own `<ID>`, reached by clicking the
detail-page `input[name=submit_form]` "Continue application" button, which
navigates to `…/eform/<SEC2_ID>/page/1`). The detail page shows "Thank you
for submitting the first section… complete the second section" and the
Section-2 entry is that "Continue application" button (an `<input
type=submit>`, NOT an `<a>`/`<button>` — a `querySelector('a,button')` scan
MISSES it; search `input[name=submit_form]`).

### Section-2 driver — `tal_sec2.py` (SOLVED 2026-07-14, BA run 2026-07-15)
`python3 sites/civilservicejobs/scripts/tal_sec2.py <sec2_eform_base_no_slash> <spec.json>`
- Spec shape (see `spec_ofgem_s2.json` / `spec_cps_s2.json` / `spec_ba_s2.json`):
  `{"pages":[1,2,3,...], "fields":{ "<name>": {"kind":"textarea|text|checkbox|select", "value":"..."}, ...}}`
  with token substitution in string values: `__CV_EMP__` / `__CV_SKILLS__` /
  `__PS__` → `applications/cabinet-office-user-researcher/{cv-employment.txt,cv-skills.txt,personal-statement.txt}`.
  **Path gotcha:** the APP dir is THREE levels up from the script
  (`os.path.join(HERE,"..","..","..","applications")`); two-level was wrong and
  silently emptied the CV/personal-statement textareas (they reported `OK:0`).
- **THE submit bug that LOOKED like a wall:** the final (Declaration) page of
  Section 2 has NO "Continue" button — it reveals a **"Submit"** button ONLY
  AFTER (a) the declaration checkbox is ticked AND (b) the "Full Application Form
  Submitted?" select (`datafield_76575_1_1`) = "Yes". If you click Continue on
  the non-final pages and then only look for Continue on the last page, you see
  "NO_BTN" and conclude "no submit control". Fix: on the final page, fill the
  declaration fields FIRST, then click **Submit** (the driver's
  `click_continue_or_submit(final=True)` does exactly this).
- **`tal_sec2.py` re-fills ALL spec fields on EVERY page** (it doesn't scope
  fields to the current page). Harmless — fields not on the current page return
  NO_FIELD and are skipped — but it means every field gets set on its own page as
  the walk passes through. Confirm the CV/personal-statement/behaviours stuck by
  re-reading them after the run (they survive Continue navigations).
- **Fields DO persist** across Continue navigations (this was a mis-diagnosis in
  an earlier run caused by flaky `cfx.evaluate` reads returning `None`). Fill
  each page, click Continue, repeat; the SPA saves per page. Verify a value stuck
  by re-reading that field after the Continue — it survives.
- CPS Section 2 additionally needs FOUR Success-Profile behaviour statements
  (Communicating & Influencing / Working Together / Making Effective Decisions /
  Changing & Improving) — generate them from Jane's IT Service Desk / break-fix /
  onboarding background; no pre-existing behaviour file ships in the skill.
- **2026-07-15 BA run:** Section 2 field IDs (99856/99863 CV, 72158 PS, 22232/22238/22244
  behaviours, 53467 location, 205967/76575 declaration) are STANDARDIZED across CSJ
  postings — the CPS S2 spec was reusable for the Cabinet Office Business Analyst
  with only the personal statement swapped (Jane's real BA-adjacent experience).
  See `spec_ba_s2.json` + `applications/cabinet-office-business-analyst/`.
- Page counts differ per role (UKEF 3, OFGEM 5, CPS 4) — MAP the target eform's
  pages first (navigate `/page/N` for N=1..8, dump fields per page) before
  writing the spec; don't assume 3 pages.
- **Reaching the S2 eform id:** from the apps list, open
  `…/candidate/application/<APP_ID>`, click
  `input[value="Continue application"]`, read the redirected
  `/eform/<SEC2_ID>/page/1` URL.

## CSJ apply is UNBLOCKED — credentials ALREADY exist (2026-07-15)
Do NOT ask the user for CSJ login. The creds are ALREADY in the skill's
`ats-credentials.csv` under row key `civilservicejobs.service.gov.uk`
(`you@example.com` / password). Login is fully scriptable (see "Re-authenticating
a dead CSJ/TAL session" below). A live logged-in CSJ tab shows "Account details" /
"Sign out" — NOT "Sign in to your account". This was the single biggest unblock
of the 2026-07-15 run: the creds were in the credential store the whole time.

## Reaching the TAL eform from a live advert (the Apply handshake, verified 2026-07-15)
1. Open the advert via the STABLE url `https://www.civilservicejobs.service.gov.uk/csr/jobs.cgi?jcode=<vac>`
   (NOT an `index.cgi?SID=` link — those are one-shot / expire; regen the SID by
   re-running the London search in-browser and copying the fresh results URL).
2. Click the green **"Apply now"** button (`input[type=submit][value*=Apply]`).
   This lands on `cshr.tal.net/vx/.../candidate/eform/<ID>/page/1` (Section-1 eform).
   ⚠️ The TOC anchor "Apply and further information" is a SCROLL link, NOT the apply
   button — clicking it only jumps to the apply section; you must then click the real
   green "Apply now" `input[type=submit]`.
3. Page 1 = Application Guidance; the **Continue** button is at the page bottom
   (0-based `<button>`/`input[type=submit]` index 2). Click it via a NATIVE
   `.click()` — the SPA advances WITHOUT a URL change. After Continue,
   `document.title` becomes "Eligibility - Civil Service Jobs".
4. Walk the rest with `tal_eform.py` (Section 1) then `tal_sec2.py` (Section 2).

## Driver `_continue()` / navigation pitfalls (2026-07-15 code fixes — already in tal_eform.py)
Two driver bugs cost repeated full re-runs this session; both are fixed in the
committed `tal_eform.py` but recorded here so they are never reintroduced:
- **`_continue()` must NEVER click a TOC `<a>` named "continue".** The CSJ eform
  renders a Table-of-Contents sidebar with `<a>Continue</a>` anchors that only
  scroll the page — clicking one does nothing and the walk silently stalls on
  page 1. Fix: only consider `input[type=submit], button[type=submit]` (filter out
  `value/innerText` == "back"/"back_button"), prefer the one labelled "Continue"
  then "Submit"/"Finish"/"Confirm".
- **Do NOT navigate twice.** `main()` already does `cfx.navigate(page/1)`; the old
  `walk()` did a SECOND `cfx.navigate(page/1)` which, on a wedged tab, 500s and
  aborts the whole run. Fix: `walk()` skips re-navigate if already on Guidance,
  and uses a wedge-resistant `_navigate()` (retry on 500).
- **Declaration `NO_ADVANCE` is a DIAGNOSTIC, not a click failure.** The final
  "Submit" button only RENDERS after (a) every prior page validates and (b) the
  declaration checkbox is ticked. If the page shows "There is a problem … Diversity
  monitoring" (or Eligibility/Personal), Submit will not appear and `_continue()`
  reports NO_ADVANCE — go FIX the flagged page; don't retry the click. Re-read each
  page's `:checked`/value after filling to confirm it stuck before advancing.

## Eligibility-page field names (verified 2026-07-15, Performance Analyst vac 2005339)
- `datafield_87767_1_1` — "Are you already a civil servant…?" → **No** (Jane is not).
  Answering No FORCES two extra required fields:
  - `datafield_177937_1_1` — Home department (SELECT, a REAL value e.g. `14600`=
    Cabinet Office). Must not stay on "Select" placeholder or the page won't save.
  - `datafield_87776_1_1` — Other organisation (TEXT, e.g. "Self-employed contractor").
- `datafield_44636_1_1` — "Do you meet the nationality requirements?" → **Yes** (British).
- `datafield_44639_1_1` — "Right to remain and take up work in the UK?" → **Yes**.

## camofox evaluate wedge on CSJ pages — WORKAROUND (2026-07-15)
`cfx.evaluate` intermittently returns HTTP 500 on CSJ pages under tab load, but it
is NOT a total wedge: `document.title` and SIMPLE single-expression `.click()` /
single-field reads work. The wedge triggers on COMPLEX array-mapping JS
(`[...document.querySelectorAll(...).map(...)]`) and on large payloads.
- To extract posting links: the CSJ results cards use `index.cgi?SID=…joblist_view_vac=<ID>`
  (decode the base64 SID to get the vac id), NOT `jobs.cgi?jcode`. Prefer `shot` +
  vision_analyze over evaluate for reading CSJ pages (screenshots never wedge).
- To set a radio: `document.querySelector("input[name='<f>'][value='<v>']").click()`
  in its OWN minimal evaluate. The 500 may still return on the CLICK call, but the
  click usually FIRES before the response — re-read `:checked` with a separate tiny
  evaluate to confirm (retry the read a few times; reads recover).
- This wedge was NOT cured by reducing tab count. When it hard-wedges (reads 500
  repeatedly), the real fix is restarting camofox (`docker restart <camofox-container>`
  or `docker compose restart camofox-browser`) — which needs user permission the
  agent lacks. State this as the unblock; do not loop the wedge.

## Re-authenticating a dead CSJ/TAL session (SCRIPTABLE — not a VNC halt)
The TAL flow needs the **CSJ SSO session** in the camofox tab, and it CAN die
mid-run (both tabs returning len-0 HTML for CSJ home / TAL apps / the login
deep-link, while `example.com` still renders — proving the cfx pipe is fine).
**But CSJ login IS scriptable** — do NOT route it to user-VNC as the old
note said. To recover:
1. `open_tab("about:blank")` a FRESH tab (the dead one keeps returning empty
   even after re-nav — a brand-new tab is required).
2. Navigate `https://www.civilservicejobs.service.gov.uk/csr/login.cgi`
   (poll `readyState=="complete"`, then **`sleep 3`** — the first evaluate
   calls right after load intermittently 500 / return None; settle first).
3. Fill `input[name=username]` (email) + `input[name=password_login_window]`
   (password) from `ats-credentials.csv` (row `civilservicejobs.service.gov.uk`),
   set via native value-setter + `input`/`change` dispatch, then click
   `input[name=login_button]` (value "Sign in").
4. After redirect to `index.cgi?SID=…` with `just_logged_in=1` in the SID,
   the session cookie is restored. Then reach TAL via the **advert Apply
   handshake** (above), NOT a deep-linked TAL URL.
⚠️ The `cfx.evaluate` pipe intermittently returns `None` on LARGE payloads
(`outerHTML`, big `body.innerText`). Symptom: `ev()` retry-wrappers that
reject `None` then report "empty page" and you wrongly conclude the session
is dead. **Mitigation:** use small reads (`document.title`,
`document.body.innerText.slice(0,200)`, field-by-field) and re-run the read
once if it returns None — never declare a session dead on a single flaky
`None`. A control nav (`example.com`) rendering while CSJ returns None means
camofox flake, not session death.

## CORRECTION — S2 field IDs are NOT stable across CSJ campaigns (2026-07-15, second pass)
The "Section 2 field IDs are STANDARDIZED across CSJ postings — the CPS S2 spec
was reusable for the BA" claim (in the Section-2 driver callout just above) is
WRONG as a universal rule; the SKILL.md correction now scopes it. Reusing
`spec_ba_s2.json` on a different campaign's S2 eform makes `tal_sec2.py` report
`NO_FIELD` on the personal-statement field, then *"There is a problem — Enter your
personal statement for this job application"* + `NO_BTN` on the final page, after a
~400s timeout. Root cause: the PS field id differs by campaign.

Verified divergence (both real CSJ S2 eforms):
- **BA / CPS** (eforms 56996507 / 56996925): PS = `datafield_72158_1_1`; **5 pages**
  (CV 99856/99863 → PS 72158 → behaviours 22232/22238/22244 → location 53467 →
  declaration 205967 + "Full Application Form Submitted?" 76575).
- **UKEF Service Designer** (eform `57015893`, jcode 2005590): PS =
  `datafield_72117_1_1`; **3 pages** (CV 99856/99863 + name-blind checkbox 217326 →
  PS 72117 + name-blind checkbox 217326 → declaration 205967 + 76575). **No behaviour
  pages.** The "name blind recruitment" warning means the PS must contain NO name /
  email / gender / age / educational-institution — the reusable
  `applications/cabinet-office-user-researcher/personal-statement.txt` is already
  name-blind; write role-specific PS the same way.

**Rules that prevent the dead-end:**
1. **ALWAYS MAP the target S2 eform's pages + field ids before writing its spec.**
   Dump field names per page with a minimal evaluate
   (`JSON.stringify([...document.querySelectorAll('textarea[name],input[name]')].map(e=>e.name))`).
   Do NOT navigate via `location.href='/candidate/eform/<id>/page/N'` to "map" — that
   HARD-RELOADS the page and **discards any unsaved S2 data**, and desyncs the driver's
   Continue-chain. Map by reading fields only, or map on a fresh re-entry (click
   "Continue application" from the apps detail page), never mid-fill.
2. **Write a per-eform S2 spec** (copy `spec_ba_s2.json`, swap the PS/behaviour field
   ids + `pages` list to the mapped eform). Only `99856`/`99863` (CV) and
   `205967`/`76575` (declaration) are safely reusable across campaigns.
3. **`tal_sec2.py` token substitution is hardcoded** to
   `applications/cabinet-office-user-researcher/{cv-employment,cv-skills,
   personal-statement}.txt` (`__CV_EMP__`/`__CV_SKILLS__`/`__PS__`). For a new role
   either (a) drop the role's name-blind CV/PS into that dir, or (b) write the spec with
   **literal** text values (no tokens) — the driver passes non-token strings through
   unchanged.
4. **Page counts differ** — UKEF = 3, BA/CPS = 5, others vary. Set the spec `pages`
   list to the mapped count; an over-long pages list makes the driver walk past the real
   final page and miss Submit.
