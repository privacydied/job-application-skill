# 2026-07-22 — confirmed headless drivability gaps (this applicant)

Verified live this session while attempting a 20-application drive. These are
CAPABILITY GAPS in the headless camofox engine / live-site drift, NOT flakes.
Log `Blocked` with the concrete reason; never pad the count with off-lane rows.

## 1. CSJ TAL — `instant=apply` drift: `tal_eform.py` INAPPLICABLE (VERIFIED 2026-07-22, deeper probe)
- `csj_login.py` works (session then shows "Jane Doe / Sign out"). Clicking
  **Apply now** (`input[type=submit][value="Apply now"]`) lands on
  `cshr.tal.net/.../candidate/application/<APPID>?instant=apply` — NOT the
  `.../eform/<ID>/page/1` that `tal_eform.py` expects.
- Resolved path (was "no visible Begin eform entry" — it WAS there, just one
  more click deep): from `…/application/<APPID>?instant=apply` → click
  **View application** → **Form List** (lists "First Stage Short Form" +
  "Full Application Form", each a "View" action) → `…/application/<APPID>/view_form/<FORMID>`.
- That `view_form` page renders with the **WCN `hform` engine** (`form_root
  form_section hform_label_pos` classes) — NOT Knockout TAL. Verified blocker:
  `document.querySelectorAll('input,textarea,select')` returns **1 element**
  (a hidden `__vxXSRF_Token`); eligibility/personal fields are app-widgets, not
  standard inputs. `tal_eform.py` (targets `datafield_NNNNN_1_1` + `/eform/<ID>/page/N`)
  cannot bind and its `…/eform/<ID>/page/1` navigate 404s ("Candidate Page Not Found").
- **Conclusion: CSJ TAL fill/submit is BLOCKED until a WCN-hform-compatible driver
  exists** (discover the widget model + a setter that updates WCN's viewmodel,
  mirroring `tal_eform.py::_set_field`'s prototype-setter). This is a structural
  platform change, durable for months — not a transient camofox flake. Full repro
  in `references/csj-wcn-hform-drift.md`. (The §4 "Knockout SPA / datafield" guidance
  in `csj-apply-bootstrapping.md` is now stale for the live form — see its drift note.)

## 2. Greenhouse (Typeform) — static Yes/No react-select screeners unbindable headless
- Typeform "Product Designer - Integration"
  (job-boards.greenhouse.io/typeform/jobs/7913052). Two REQUIRED screeners —
  "Are you legally authorized to work in the country…" (`question_66734152`) and
  "Will you…require sponsorship" (`question_66734153`) — are react-selects
  (`select__input`, `aria-haspopup=true`).
- The option menu returns **EMPTY** in headless (both `.click()` and the mousedown
  ladder → NO_MENU). `combobox_pick` reports `OK:Yes` but the value reads back
  empty (silent false-success — same class as the Ashby location-combobox
  empty-list gap, but on a *static* Yes/No select, not an async autocomplete).
- Result: submit blocked on "This field is required." → log `Blocked`
  (react-select screeners unbindable), not a flake.
- **Fix direction (unverified):** `atsform.combobox_pick`'s freetext fallback
  only fires when `opts` is empty AND the field accepts a typed value on submit —
  Typeform's static select does not. A static-option commit path for empty-menu
  react-selects is still missing.

## 3. WTTJ in-platform — Axeptio consent CMP not dismissed by `apply.py`
- `apply.py start` opens the in-platform modal, but an **Axeptio consent CMP**
  ("Consents certified by…", service toggles) intercepts. `apply.py`'s
  `dismiss_promo` only closes the *"write better applications"* promo — it does
  NOT dismiss Axeptio.
- When Axeptio is up, `status` returns `Progress: ? | Send now enabled: None`
  and no form fields are reachable (manual DOM reads hit the CMP).
- **Workaround (verified to clear the CMP):** trusted-click the Axeptio
  **"Accept all"** button (dispatch pointer/mouse sequence on the button whose
  text matches `/^Accept all$/i`) before `apply.py start`/`status`. After that
  the in-platform form fields become reachable. Full in-platform submit still
  needs per-role verification.

## Net effect on a 20-target drive
Only ~12-15 of the 31 classifier-"convertible" rows are genuinely on-lane for
this junior→mid applicant; of those, Greenhouse (react-select), WTTJ (CMP), and
CSJ TAL (instant-apply drift) all hit headless blockers this session → 0 new
Applied, 1 Blocked (Typeform). The convertible ceiling is real, but the
*drivable* set is currently near-zero until these three gaps are closed.
