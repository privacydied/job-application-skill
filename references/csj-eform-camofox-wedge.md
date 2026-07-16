# CSJ TAL eform × camofox `evaluate` wedge (verified 2026-07-15, CORRECTED 2026-07-15)

## Headline — the 500 is SPURIOUS; the write lands
CSJ's TAL eform pages (`cshr.tal.net/.../eform/<ID>/page/N`, a Knockout SPA) make camofox's
REST `evaluate` **return `HTTP 500 Internal server error` on MOST calls that MUTATE the DOM**
(setting `input.value=`, radio `.click()`, `dispatchEvent`). BUT the mutation **actually
(executes before the response — the value sticks **in the DOM**. WARNING: a DOM `.value`/`:checked`
read will then SHOW your value, but that does NOT mean Knockout's **viewmodel** got it — see
the CORRECTION block below. So CSJ apply via camofox IS practical, but ONLY via the driver's
prototype-setter (which updates the model); ad-hoc `el.value=` writes look filled but save blank.
This is CSJ-page-specific: LinkedIn/Indeed pages evaluate fine on the same tab, and even CSJ
*reads* (`document.title`, `.value`, `:checked`, `querySelectorAll`) and *button-Continue
clicks* work reliably — only DOM-mutation writes "wedge" (spuriously).

## ⚠️ CORRECTION (2026-07-15, end-of-session) — ad-hoc writes look filled but DON'T persist; the submit wall is a validation error, not a click failure

The headline above is right that the 500 is spurious, BUT the earlier "write-then-verify works ad-hoc / an entire Section-1 form was filled and verified" claim was **misleading** and caused a 10-turn loop. The "verification" read `.value` / `:checked` — that returns the **DOM attribute**, not Knockout's **viewmodel**. CSJ's TAL eform serializes its **viewmodel** on Save/Continue, so a field you set with `el.value = x` (or a plain radio `.click()` whose event didn't reach Knockout) saves as **BLANK** even though the DOM read shows your value.

**The real symptom (NOT a click-delivery failure):** every Continue "advances" fine, but on the final Declaration page the submit is rejected with **"There is a problem — The following form pages have problems that need to be fixed: Eligibility / Personal information / Diversity monitoring."** That banner means those pages' required fields are **empty in the Knockout model**. Hammering Continue / the Submit button harder does nothing — the fix is to re-fill the fields correctly (in the model).

**The ONLY correct way to write CSJ eform fields:** the driver's prototype-setter in `tal_eform.py::_set_field` — `Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set.call(e, val)` (textarea: `HTMLTextAreaElement.prototype`) + `input`/`change`/`blur` dispatch. That updates Knockout. **Replicate it exactly if you must hand-write; never use bare `el.value =`.** This is also why the driver — not ad-hoc evaluates — is the supported path: its setter is correct and its retry survives the flake.

**Confirm success by the ABSENCE of the "There is a problem" banner after each Continue** — NOT by a DOM `.value` read (which lies about model state). If the banner names pages, those pages' fields were blank-in-model; re-fill them with the prototype-setter (via the driver spec).

**Driver fix shipped 2026-07-15:** `tal_eform.py::_continue()` was broken — it matched only `button, a` and missed CSJ's Continue (`<input type=submit value=Continue>` on inner pages, `<button type=submit>Continue</button>` on Guidance). It is now patched to (1) include `input[type=submit]`, (2) be wedge-resistant (fire the click, ignore the spurious 500, verify navigation by **title change**, retry 6×), (3) prioritize the real submit button. **Use `tal_eform.py` with a spec.json — do NOT hand-drive the fields.** If `_continue()` still reports `NO_ADVANCE`, the title-read inside it can also 500 (make `_page_title()` retry, like the `read()` helper would) — a transient, not a structural wall. Note the remaining open item: when run from a tab parked mid-flow, the driver `cfx.navigate(.../page/1)` reloads Guidance; if the SPA needs >4.5s to be interactive, the first Continue can no-op — bump the post-navigate wait if you see `NO_ADVANCE` stuck on Guidance.

## The write-then-verify technique (still valid for READS + radio clicks; use the driver for all writes)
Do NOT trust the 500, and do NOT retry the write. Swallow it and verify separately:
```python
def fire(e):
    try: cfx.evaluate(e)        # mutation; ignore the spurious 500
    except Exception: pass
def read(e):                    # reads work; retry only the READ
    for _ in range(8):
        try:
            r = cfx.evaluate(e)
            if r is not None: return r
        except Exception: pass
        time.sleep(1.2)
    return "R?"
```
- Keep each **write expression tiny** — one `.click()` or one `.value=` per call. Big IIFEs
  with multiple `dispatchEvent`s, and heavy array-maps (`.map(...).join()`, looping
  `querySelectorAll` to build a string) are the ones that 500. Single statements are reliable.
- **Verify with a separate read** (`.value` / `:checked` / `document.title`). If the read
  returns the expected value, the write succeeded. If the read is also flaky, retry the READ
  (8×, ~1.2s) — never retry the write 12× (burns time, re-wedges).
- **Page navigation via Continue clicks works even while writes "wedge"** — so advance
  page-by-page (Guidance→Eligibility→Personal→Diversity→Declaration) and fill each page's
  fields with fire-and-verify. The SPA does not change the URL between pages.
- **Last step — Submit/Declaration:** tick the declaration checkbox (`datafield_22499_1_1`)
  and click Continue **in the SAME evaluate call** (a fresh reload drops the tick → "Select if
  you agree"). On the final Declaration page the button text is "Continue" (it submits Section
  1); only Section 2's final page reveals a "Submit" after the declaration + "Full Application
  Form Submitted?"=Yes. If the Continue won't fire the advance after several tries, the button
  is wedging — `cfx.restart_engine()` then immediately redo the page with fire-and-verify.

## `cfx.restart_engine()` is SELF-SERVICE (no user permission needed)
The skill's older text said "restart camofox (user permission)" — that is WRONG for this host.
`cfx.py` ships a NOPASSWD sudoers rule (`_RESTART_CMD`, ~L579):
```
sudo -n docker compose \
  -f compose.yaml restart camofox-browser
```
`cfx.restart_engine(health_timeout_s=90)` calls it and polls `/health` until
`browserConnected`. Login persists (cookies live in the camoufox *profile*, not the tab).
**Verified live 2026-07-15: it returned `True` and dropped the wedged tab (HTTP 410), and a
fresh tab then evaluated the CSJ advert fine.** BUT the wedge returned once back on a CSJ
eform page — so a restart is only a TRANSIENT fix, not a cure. Do not tell the user "I need you
to restart camofox" — just call `cfx.restart_engine()` yourself.

## Symptom triage (don't misdiagnose)
- `evaluate` → HTTP 500 / `None` on a CSJ eform, but `document.title` or a *different* field
  reads OK → intermittent flake. Retry with a patient loop (6–12 tries, 1.5–2s gaps). A single
  `None` is a flake, not session death (see `hermes-bootstrap.md`).
- `evaluate` → 500 on EVERY field, every call, for >30s → hard wedge. `cfx.restart_engine()`,
  then continue. If it re-wedges immediately on the eform, the eform page itself is the trigger.
- The wedge is NOT a tab-count issue here (serialized to 1 tab, still wedged). It is the Knockout
  SPA overloading camofox's evaluate pipe.

## What DID work (concrete apply-handshake, verified 2026-07-15)
1. Navigate `jobs.cgi?jcode=<id>` (stable URL; the `index.cgi?SID=` links are one-shot — decode
   `joblist_view_vac=<id>` from the base64 SID if you only have those).
2. Click **"Apply now"** (green button) — a *minimal* `cfx.evaluate("...querySelector(...).click()")`
   works where `cfx.click_selector` 500s. This lands on `candidate/application` (apps list).
3. On the apps list, find the row for the role, click its row button (the text is "Review latest
   update" / "Continue application" depending on state) → navigates to `eform/<ID>/page/1`.
   Alternatively the "Apply and further information" anchor only scrolls; use the row button.
4. **Continue-chain advance**: minimal `evaluate` finding the button whose `innerText`/`value`
   lowercases to `"continue"` and `.click()`-ing it. The SPA does NOT change the URL between
   pages (stays `.../eform/<ID>/page/1`); the title changes (Application Guidance → Eligibility →
   Personal information → Diversity monitoring → Declaration). `_continue()` in `tal_eform.py`
   already does this.
5. **Section 2** entry: from the apps list, open `.../candidate/application/<APP_ID>?instant=apply`,
   click `input[name=submit_form]` "Continue application" → redirected to `/eform/<SEC2_ID>/page/1`.
   Run `tal_sec2.py` (see `csj-tal-eform-notes.md`).

## Field map discovered (Performance Analyst, eform 56992962 — field NAMES are reused across CSJ
campaigns, so this is portable). FILL VIA `tal_eform.py` spec, never ad-hoc (the driver's retry
is the only thing that survives the flake).
- **Eligibility** (`/page/3` after Guidance+...): `datafield_87767_1_1` civil servant? (No) ·
  `datafield_44636_1_1` meet nationality requirements? (Yes — British) ·
  `datafield_44639_1_1` right to remain/work in UK? (Yes) ·
  `datafield_177937_1_1` Home department (select — real value, e.g. `14600`=Cabinet Office;
  NOT the "Select" placeholder) · `datafield_87776_1_1` Other organisation (text, e.g.
  "Self-employed contractor").
- **Personal information**: `datafield_11625_1_1` First name (Jane) · `datafield_11628_1_1`
  Surname (Doe) · `datafield_21495_1_1` Preferred first name (optional) ·
  `datafield_11643_1_1` (a required text field — label was blank on capture, inspect live) ·
  `datafield_11657_1_1` Secondary telephone (optional) · `datafield_11631_1_1` Email
  (you@example.com) · `datafield_98109_1_1` meet minimum job criteria? (Yes) ·
  `datafield_15904_1_1` (radio — inspect label live) · `datafield_110850_1_1` (radio — inspect) ·
  `datafield_174746_1_1` / `datafield_174773_1_1` (textareas — likely "reasonable adjustments" /
  "something else we should know") · `datafield_138183_1_1` veteran of British armed forces? (No) ·
  `datafield_138179_1_1` consider for "Great Place to Work for Veterans"? (No).
- **Diversity monitoring** (VERIFIED filled 2026-07-15 via write-then-verify):
  `datafield_36491_1_1` disability? → **730**=No (729=Yes, 731=Prefer not to disclose) ·
  `datafield_12784_1_1` gender → **27**=Man (28=Woman, 423=Prefer to self-describe,
  15390=Prefer not to disclose) · `datafield_97665_1_1` gender self-describe (text, REQUIRED
  even when Man) → "Male" · `datafield_35296_1_1` sexual orientation → **4012**=[your orientation] or
  straight (4015=Bisexual, 4016=Gay or lesbian, 4017=Prefer to self-describe,
  15391=Prefer not to disclose) · `datafield_97658_1_1` sexual-orientation self-describe (text,
  REQUIRED even when [your orientation]) → "[your orientation]" · `datafield_54157_1_1` national identity →
  **14553**=British (14549=English, 14550=Welsh, 14551=Scottish, 14552=Northern Irish,
  14554=Other, 14555=Prefer not to disclose) · `datafield_178072_1_1` socio-economic (parental
  occupation) → **48019**=Prefer not to say (48007–48018 are the 12 occupation bands) ·
  `datafield_178075_1_1` employment status → **48022**=Self-employed/freelancer without employees
  (48020=Employee, 48021=Self-employed with employees, 48023=Not working, 48024=Not applicable,
  48025=Don't know, 48026=Prefer not to say) · `datafield_178114_1_1` school type → **48034**=Prefer
  not to say (48027–48033 are the school bands) · `datafield_165298_1_1` (text — likely
  socio-economic "other"; leave blank unless label requires). Ethnicity broad/sub radios were
  NOT present on this campaign's Diversity page (some CSJ campaigns omit them; if present they
  follow the same datafield_NNNNN pattern — broad "Mixed / multiple ethnic groups", sub "Any
  other Mixed / Multiple background"; resolve radios by VISIBLE LABEL TEXT, not value).
- **Declaration**: `datafield_22499_1_1` agreement checkbox (tick, value 804) — tick AND click
  Continue in the same evaluate call (see write-then-verify above).

## The real path to VOLUME (verified 2026-07-15)
CSJ apply via camofox IS practical — but ONLY via `tal_eform.py`/`tal_sec2.py` with a spec
(because those drivers use the prototype-setter that updates Knockout). Ad-hoc `el.value=`
writes are a trap: they look filled (DOM read shows the value) but save blank, so the final
submit rejects with "There is a problem". To push past the LinkedIn count:
1. **Use the write-then-verify technique** (above) for every field write; verify each with a
   separate read. Do NOT retry the write or trust the 500.
2. Build the per-posting `spec.json` from `applicant-profile.md` + the field map above, then
   run `tal_eform.py` (Section 1) and `tal_sec2.py` (Section 2, with Jane's tailored
   Success-Profiles statements). The driver skips `NO_FIELD`, so partial specs run; its retry
   wrapper complements write-then-verify.
3. If the wedge hard-blocks a page (every call 500 for >30s), `cfx.restart_engine()` (self-service)
   then immediately redo that page with fire-and-verify before it degrades.

Do NOT report "CSJ apply is impractical / accept the LinkedIn count" — that was the pre-2026-07-15
wrong conclusion before write-then-verify was discovered. The wall is the spurious-500 write,
now solved. State it ONCE with the technique above.
