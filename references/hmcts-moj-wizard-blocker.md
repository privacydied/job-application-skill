# MoJ jobs.justice.gov.uk — HMCTS / MoJ 7-step wizard (live diagnosis, 2026-07-15)

Verified 2026-07-15 driving HMCTS Business Analyst (jcode 1999568, jobId 18056).
Creds in `ats-credentials.csv` row `jobs.justice.gov.uk (MoJ jobs portal)`:
field2 = `you@example.com`, field3 = password. **Login uses `input[name=username]`
+ `input[name=password]` — there is NO email-typed field** (the grep that matched
`input[type=email]` was wrong; the real field is `username`).

## Wizard path
job detail (`/JobDetail/<id>`) → click the `Apply` anchor (`href*=/Eligibility?jobId=`)
→ Eligibility(2/5) → General Information(3/5) → Success Profiles(4/5) → Equality(5/5)
→ Declaration(6/5) → Confirm(7/5). The nav button is **"Save and Continue"** — NOT
"Continue"/"Next". The `ApplicationMethods?jobId=` direct URL redirects to `/Profile` —
must enter via the job-detail `Apply` anchor.

## What AUTOMATES (2026-07-15 correction — earlier "React rejects" claim was a tooling artifact)
- **Login WORKS** (session shows "Jane Doe | My profile | Logout").
- **Eligibility step**: set 19154 (right-to-work)=Yes, 19159=Yes, tick 19161 (UK National) checkbox.
- **Country `<select>` (19305)** populates its FULL option list (the old "async wall" is GONE).
- **EVERY text input fills via `atsform.py fill`** — it uses the real `POST /tabs/{tab}/type`
  endpoint (Playwright keystroke typing), NOT synthetic `.value=`. So Title / First-Name /
  Preferred-First-Name / Last-Name / address lines / Town-City / Postcode / Email /
  Home-Phone / NINO-select=No / English-first-language ALL set correctly. **Prefer
  `atsform.py` over raw `cfx.evaluate` `.value=` here** — the synthetic path is exactly
  what React-controlled inputs reject; the typed path is accepted.

## Genuinely hard tail (the real remaining wall)
1. **County `<select>` (19308) is a Select2 autocomplete** — starts EMPTY (AJAX-loaded
   options), NOT a static `<select>`. Drive it:
   `cfx.click_selector('.select2Container19308')` → real-type `input.select2-search__field`
   ("Greater London") → click the matching `.select2-results__option`. The picked value can
   **revert on Save-and-Continue** if the underlying `<select>` change didn't commit the
   option's `value` — if validation still flags County, re-open + re-pick.
2. **Mobile field (19314)** intermittently rejects programmatic set.
3. **camofox wedges HTTP 500** on this heavy SPA after many evaluates/types.
   `cfx.restart_engine()` (NOPASSWD sudoers) clears it but **DROPS the MoJ session**
   (re-login via `username`/`password`). Keep attempts tight; don't re-fill the whole
   form after a wedge — MoJ "Save as draft" + re-entry may retain step state.

## Net
Eligibility + most of General Information are automatable with `atsform.py` + Select2
clicks. The County(Select2)+Mobile+camofox-wedge tail is the remaining friction — iterate
with the typed-endpoint tooling before escalating to VNC. Do NOT abandon the posting as
"undrivable React inputs" (that claim is false); the typed endpoint fixes the text fields.

## Debugging protocol for "evaluate returns None on a node"
Do NOT conclude "flaky backend" from one None. Probe a NEARBY small element with the same
call shape (e.g. a sibling button's `getBoundingClientRect()`).
- nearby works  → target node is specifically hidden/detached (display:none, removed, 0×0),
  NOT a backend flake. Find the visible sibling/widget.
- nearby ALSO None → genuine backend flake / dead tab → retry, re-open tab.
