# CSJ WCN `hform` renderer drift — `tal_eform.py` inapplicable (2026-07-22)

VERIFIED live 2026-07-22 while attempting to drive UK Export Finance "User Researcher"
(jcode=2005241, SEO grade, on-lane). The CSJ TAL eform renderer has changed since
`tal_eform.py` was built. This is a structural platform change (durable for months),
not a transient camofox flake.

## What changed
- **Old (driver assumption):** eform at `cshr.tal.net/.../eform/<ID>/page/N`; fields are
  Knockout-bound `<input name="datafield_NNNNN_1_1">` filled via a prototype native-setter.
- **New (live):** apply lands on `cshr.tal.net/.../application/<APPID>?instant=apply`
  (instant-apply draft). From there: **View application** → **Form List** (lists
  "First Stage Short Form" + "Full Application Form", each with a "View" action) →
  `cshr.tal.net/.../application/<APPID>/view_form/<FORMID>`. That page renders with the
  **WCN `hform`** engine (`form_root form_section hform_label_pos` classes), NOT Knockout TAL.

## Evidence the driver cannot bind
On `…/view_form/<FORMID>` (after dismissing the cookie banner):
- `document.querySelectorAll('input,textarea,select')` → **1 element**, a hidden
  `__vxXSRF_Token`. No eligibility/personal inputs in the DOM.
- Section text IS present (e.g. "Are you already a civil servant…? No", First
  Name/Surname, Disability Confident, declaration) — so the form renders, but its fields
  are app/component widgets, not standard inputs.
- `tal_eform.py`'s `cfx.navigate(eform_base + "/page/1")` against `…/eform/<ID>` returns
  **"Candidate Page Not Found (404)"** — the `/eform/<ID>/page/N` path no longer exists.

## What still works
- `scripts/csj_login.py` → LOGIN_OK (header shows "Jane Doe / Sign out").
- Apply handshake: open advert `jobs.cgi?jcode=<id>` → click **"Apply now"**
  (`input[type=submit][value='Apply now']`, minimal `.click()` evaluate) → lands on the
  instant-apply draft. NOTE: the "Apply and further information" anchor is only an
  in-page scroll link — do NOT rely on it to open the eform.
- Cookie banner: dismiss via the "I accept the cookie policy" button; it otherwise
  overlays the form.

## Open gap (the actual blocker)
No shipped driver fills the WCN `hform` widgets. `tal_eform.py` targets the retired
Knockout renderer and is a no-op/inapplicable on the live form. **CSJ TAL fill + submit
is BLOCKED until a WCN-hform-compatible driver exists** (discover the widget model —
likely label-wrapped custom radios/selects — and a setter that updates WCN's viewmodel,
mirroring `tal_eform.py::_set_field`'s prototype-setter approach).

## Companion live-channel blockers, same session (honest ceiling)
- **Greenhouse (Typeform "Product Designer - Integration"):** the two required Yes/No
  screeners (work authorization, sponsorship) are react-selects whose option list returns
  **EMPTY** in headless camofox. `atsform.fill` / `combobox_pick` report `OK` but the value
  reads back empty → submit blocked on required fields. (Same class as the documented
  Ashby empty-menu case; `combobox_pick`'s freetext fallback did NOT bind here.) Logged
  `Blocked`.
- **WTTJ in-platform (loveholidays / AIOS Product Designer):** `apply.py start` opens the
  modal, but the application-form questions do not render as standard DOM inputs (only 1
  input present) — the driver's label-walk binder cannot locate fields. The Axeptio CMP
  also intercepts if poked manually; the driver does not auto-dismiss it.
- **Ashby:** spam-flagged in this client (known, skip).
- **Net:** every on-lane, account-less, headless-submittable channel for this
  junior→mid London product/UX applicant was walled this session. The convertible pool is
  structurally small and currently undrivable in camofox.

## Repro (CSJ)
```
cfx.goto("https://www.civilservicejobs.service.gov.uk/csr/jobs.cgi?jcode=2005241")
# login if needed: python3 scripts/csj_login.py
cfx.evaluate("document.querySelector('input[type=submit][value=\"Apply now\"]').click()")
# -> .../application/<APPID>?instant=apply
# View application -> Form List -> View (Full Application Form)
# -> .../application/<APPID>/view_form/<FORMID>
# dump: document.querySelectorAll('input,textarea,select')  -> 1 (XSRF token only)
```
