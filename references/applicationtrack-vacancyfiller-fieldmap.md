# applicationtrack (MI5/MI6/GCHQ) VacancyFiller eform — full drive map

Field-tested 2026-07-17/18 driving MI5 Platform Engineer Ref. 3781 to a real
"Under review" submission. The applicationtrack.com VacancyFiller eform is the
apply path for ALL THREE intelligence tenants on the ONE `applicationtrack.com (MI5)`
credential row: MI5 = `appcentre-1/brand-5`, MI6 = `appcentre-2`, GCHQ = `appcentre-3/brand-7`.
One login covers all three. This file is the reusable field map + gotchas so a future
session does not re-derive it.

## 1. How to START an application (no visible "Apply" button on the detail page)
The vacancy detail page (`/candidate/so/pm/1/pl/4/opp/<REF>-<slug>/en-GB`) has NO apply
link — only a careers-info link. The apply action is a POST form whose `action` ends in
`/opp/<REF>/apply/en-GB`. Submit that form (find it, click its submit button) to create the
application. It redirects to `/candidate/application/<APPID>` and the eform opens at
`/candidate/eform/<EFORMID>/page/1`.

```
# from the opp detail page:
form = document.querySelector('form[action*="/apply"]')
form.querySelector('button[type=submit],input[type=submit]').click()
```

The eform id (e.g. `7744410`) is stable for the session; the section tracker lives in the
`a.jump-to-page` links: each shows `<Section> [tracker_stat_<state> page-<submitted|not-submitted>]`.
`tracker_stat_complete` / `tracker_stat_mandatory_complete` = done. Use the tracker as the
source of truth, NOT a single page render.

## 2. The 7-section structure (MI5 3781 / 3685 confirmed)
`a.jump-to-page` order:
1. Personal Details        -> page/1
2. Minimum Eligibility     -> page/2
3. Offer Of Interview (OOI)-> page/3
4. Adjustments & Special Arrangements -> page/4
5. Security Vetting        -> page/5
6. Equal Opportunities     -> page/6
7. Submit                  -> page/7

IMPORTANT: VacancyFiller tracks the "current page" via hidden `page_number`/`next_page_num`
fields, NOT the URL segment. Direct `cfx.sh nav …/page/2` re-renders page/1 content. You
advance ONLY by clicking `continue_button` (pages 1-6) or `submit_button` (page/7). After each
continue, re-read the tracker to confirm the section flipped to `complete`. The Submit page
has neither `continue_button` NOR a visible submit button until Personal Details is fully
`mandatory_complete` — if Submit shows "NO" button, a prior section is still incomplete.

## 3. Field map + truthful values (from references/applicant-profile.md)
All values below are the applicant's recorded facts. Fill via `cfx.sh eval` (see §5), never
hand-wave. Set `<select>` by `.value`; set radios by clicking the radio whose
`label[for=id]` text matches exactly (Yes/No), or contains a substring for statement radios.

### Personal Details (page/1)
| datafield | type | value |
|---|---|---|
| 16181_1_1 Email | text | you@example.com |
| 16214_1_1 Title | select | 29 (Mr) |
| 16169_1_1 First Name(s) | text | Jane |
| 16175_1_1 Last Name | text | Doe |
| 16250_1_1 Previous Last Name | text | N/A  (field says "if no previous surname type N/A") — it is REQUIRED |
| 31643_1_1 NINO | text | [NINO] |
| 31776_1_1 Country | select | 1822 (United Kingdom) |
| 31790_1_1 Address l1 | text | Flat 3 The Forge Building 22 Wharf Road |
| 31806_1_1 Town | text | London |
| 31824_1_1 County | select | 13456 (Greater London)  — appears ONLY after Country is set |
| 31846_1_1 Post Code | text | [postcode] |
| 16232_1_1 How long here | text | Over 5 years |
| 31702_1_1 Home Tel | text | +447700900000  (format: +447 followed by 9 digits, no spaces) |
| 29967_1_1 UK mobile? | select | 1 (Yes) |
| 41520_1_1 Mobile | text | +447700900000  (same format rule) |
| 31685_1_1 Preferred contact | text | 7804605448  (numerics only) |
| 388025_1_1 British Citizen? | select | 1 (Yes) |
| 386995_1_1 Where heard | select | **VARIES per eform instance** — see §4 |
| 1027150_1_1 AI guidance confirm | radio | Yes (label "Yes") |
| 1049834_1_1 Travel guidance confirm | radio | Yes (label "Yes") |

Phone format trap: value `+44 7700 900000` (space, +44) fails with
"Phone number should be in format: +447 followed by 9 numeric digits with no spaces".
Use `+447700900000`. The Preferred-contact numeric field must be digits only.

### Minimum Eligibility (page/2) — UK residency for DV clearance
Resided outside UK past 10 years = No (lived in UK 7/10). So:
- 985577_1_1 (age >=18 for DV): Yes
- 985581_1_1 (lived UK 7 of last 10 yrs): Yes
- 985585 / 589 / 593 / 597 / 601 / 605 / 609 / 613 / 617 / 621: all No
(these are the "if not 7/10, is it because…" conditional questions — answer No when the
residency test is met). Some eforms omit these datafields; `setradio` returning NO_OPT is harmless.

### OOI (page/3)
- 931117_1_1 disability: 730 (No)  -> 931121_1_1 OOI consideration: 2 (No)

### Adjustments (page/4)
- 18539_1_1 reasonable adjustments: 2 (No)
- 18536_1_1 special arrangements: 2 (No)

### Security Vetting (page/5)
- 421796_1_1 Date of birth: DAY=3, MONTH=3, YEAR=1995  (DOB [DOB]; day value is "3" not "03")
- 422067_1_1 Today's date: DAY=18, MONTH=7, YEAR=<current year>
- 421791_1_1 vetting terms: click radio whose label contains "agree to the terms" (labels are
  "I agree to the terms in the above statement" / "I do not agree…", NOT "Yes")
- 421803_1_1 drug policy: Yes
- 422410_1_1 undischarged bankrupt: No

### Equal Opportunities (page/6) — REQUIRED demographic fields
- 27849_1_1 Ethnic Origin: 843 (Mixed - Other)  -> reveals required `17697_1_1` "Please specify" -> "Mixed Caribbean and North African"
- 17709_1_1 Religion: 505 (Jewish)  -> reveals required `17712_1_1` "Religion details" -> "Jewish"
- 17694_1_1 Gender: 27 (Male)
- 17706_1_1 Disability: 730 (No)
- 17718_1_1 Sexual Orientation: 481 (Heterosexual / Straight)
- 17703_1_1 Age Range: 835 (31-35)
- 938519/555/591/606/621/636/651/666 socio-economic (school, parental qual/occupation, FSM,
  background): all "Prefer not to say" (2773/2780/2794/2801/2806/2811/2816/2820) -> these reveal
  `938534_1_1` ("1a. specify") and `938570_1_1` ("2a. specify") which MUST be filled or the
  section stays incomplete -> set them to "Prefer not to say" (text). These facts are not held;
  "Prefer not to say" is the honest answer.

### Submit (page/7)
- 387216_1_1 memorable word (>=5 chars, for phone identity): e.g. "WharfRoad" (NOT a real secret)
- 387231_1_1 hint: e.g. "Street where I live"
- 387245_1_1 consent checkbox: check it
- then click `submit_button`. Success -> "Thank you, your application has been submitted." and
  the candidate list shows the role as "Under review".

## 4. PER-INSTANCE SELECT-OPTION PITFALL (cost a whole draft)
The option VALUES for a given datafield DIFFER between eform instances. Example:
`386995_1_1` "Where did you hear" was `5308` (Civil Service Jobs Website) on eform 7744410
(MI5 3781) but only `5435`/`984` on eform 7744448 (MI5 3685) — setting "5308" there silently
left it empty and the section never completed. **Before setting any select, read its live
`option` list and pick the value that exists on THIS eform.** Never hardcode an option value
from a different application. If the value does not exist the field stays at "Select" and the
section reports incomplete with "This field is required" — re-read the options and fix.

## 5. cfx.evaluate 500s -> use cfx.sh eval
On these heavy VacancyFiller pages `cfx.evaluate` (python module) intermittently 500s with
"Internal server error" even though the page rendered fine. Two causes:
(a) stale tab handle in the python module -> call `cfx.ensure_tab(persist=False)` once before
    `cfx.goto` to reset it; or
(b) the arrow-function IIFE sometimes 500s while a `function(){…}()` declaration does not.
MOST RELIABLE: route ALL reads/fills through the shell wrapper —
`bash sites/_common/scripts/cfx.sh eval '<js>'`. Same REST endpoint, no python 500s.
A reusable driver that shells out to `cfx.sh eval`/`nav`/`shot` for every step is the proven
pattern. Pure-python `cfx.evaluate` loops will wedge.

## 6. Hard stop that is NOT a wall
Some roles (e.g. MI5 SRE 3772 "Covert Capability") open an application whose first step is a
timed **Cubiks online aptitude/psychometric test** ("Test in progress"), not the eform. That is
the applicant's own reasoning assessment — you cannot truthfully complete it. Surface the test
gate and STOP; do NOT fabricate or skip past it. (Contrast: roles like 3781/3685 open the eform
directly and are fully drivable once the birth/nationality facts are filled from the profile.)

## 7. Reusable driver shape (do not re-derive)
A Python script that, for each step, shells out to `cfx.sh`:
- `ev(js)` -> `subprocess.run(['bash','sites/_common/scripts/cfx.sh','eval',js])`, parse JSON `result`.
- `nav(u)` -> `cfx.sh nav <u>` + sleep.
- fill helpers: `settext` (focus + value + input/change events), `setsel` (value + change),
  `setradio(nm,yesno)` (click radio whose `label[for=id]` text matches), `setradio_substr`.
- walk sections in order, clicking `continue_button` after each, re-reading the tracker to
  confirm `complete` before moving on. Do NOT click `submit_button` until Personal Details is
  `mandatory_complete` (else Submit shows no button and the form submits incomplete -> status
  "Incomplete" on the candidate list, which must NOT be logged as Applied).
- capture proof: `cfx.sh shot applications/<slug>/confirmation.png`, then
  `log-application.py … Applied --proof …`.
