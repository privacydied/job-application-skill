# External ATS form techniques under camofox (react-select / react-international-phone)

Reusable patterns for third-party apply forms (Hiresome, SThree, micro1, Free-Work) reached
via LinkedIn/Indeed "Apply on company site".

## 1. react-international-phone — type E.164 in ONE call, do NOT click the country select
Phone renders as `<input class="react-international-phone-inpu">` with a separate country
react-select defaulting to e.g. `+91`. That country control has NO `@eN` ref and a
coordinate-click MISSES. Ignore it; set the full E.164 number in ONE evaluate — the library
auto-detects the country:
```js
const e=document.querySelector('input.react-international-phone-inpu');
e.focus(); e.value=''; e.dispatchEvent(new Event('input',{bubbles:true}));
e.value='+447700900000';
e.dispatchEvent(new Event('input',{bubbles:true}));
e.dispatchEvent(new Event('change',{bubbles:true}));   // shows "+44 7700 900000", country auto-switched
```
⚠️ Typing `+447…` char-by-char (`cfx type`) gets parsed mid-stream as `+7` (Russia). Set the
whole value in ONE evaluate, never per-char.

## 1b. intl-tel-input (Workable-class ATSes) — set COUNTRY first, then NATIONAL number
Workable's phone is `intl-tel-input` (class `iti__search-input` / `iti-0__search-input`). Unlike
the react-international-phone in §1, the country dropdown MUST be set explicitly or validation
rejects the number:
- **Trap (2026-07-16, FE Fundinfo Workable):** every format fails —
  `447700900123` (12 digits) → "too long"; `7700900123` / `7700 900123` (10–11) → "invalid";
  `+447****0123` → "invalid". The validator strips the displayed `+44` prefix and re-checks.
- **Fix:** (1) set the country via the ITI search input to **"United Kingdom"** (or click the
  `United Kingdom` option in the `.iti__country` list), THEN (2) type ONLY the national number
  `7700 900123` (no +44, no country code). With GB selected the field accepts the 10-digit
  national format. (If Jane's real number is available, prefer it; the placeholder above is a
  valid-format stand-in.)
- For the react-international-phone in §1 the opposite holds (set full E.164 in one call, ignore
  the country control) — the difference is the LIBRARY: intl-tel-input needs the country picked
  first; react-international-phone auto-detects from E.164. Check which class the input has.

## 2. Plain react-select (currency/country) — type + Enter, not click
Renders as `.css-b62m3t-container` with a `react-select-N-live-region` id; NO `@eN` ref and
`click-xy` on the trigger FAILS. Target the combobox `<input>` inside the container:
```js
const lr=document.getElementById('react-select-2-live-region'); // the one you want
const c=lr.closest('.css-b62m3t-container');
const inp=c.querySelector('input');
inp.focus(); inp.value='GBP';
inp.dispatchEvent(new Event('input',{bubbles:true}));
inp.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));
inp.dispatchEvent(new KeyboardEvent('keyup',{key:'Enter',bubbles:true}));   // singleValue -> "£ [GBP]"
```
Disambiguate multiple containers by a sibling `input[placeholder="Current CTC"]` or each
container's `.css-1dimb5e-singleValue` text.

## 3. Submit — native `.click()`, not camofox click/click-xy
Camofox `click`/`click-xy` on submit often returns `{"ok":true}`/`500` with NO state change
(handler never fires; React re-render races the click). Fire the real handler:
```js
[...document.querySelectorAll('button')].find(b=>/submit application/i.test(b.textContent))?.click();
```
Verify via `location.href` / a confirmation banner in body text.

**⛔ Submit fires but the page doesn't advance = an unfilled REQUIRED field, NOT a dead
button — do NOT log Blocked.** The a11y snapshot/`evaluate` often can't see which field, so
`cfx.sh shot` + vision to spot the red-bordered one, fill it, re-submit. Required fields
routinely surface only AFTER a submit attempt (a second react-select, a contact-email field
labelled with placeholder prose) — expect 2–3 submit passes on Hiresome-class forms.

## 4. Wrong-field / stale-render forms (micro1) — treat as a wall
`jobs.micro1.ai` re-keys/reorders inputs between snapshots (a value typed into field A shows
in field B next snapshot; resume upload resets after "Next"). Environmental wall, not
retry-fixable — log `Blocked` (retryable) and move on (SKILL.md 2-attempt cap).

## 5. Free-Work LinkedIn SSO — OAuth popup is an isolated context
"Sign in with LinkedIn" opens an `oauth` popup that does NOT inherit the main LinkedIn
session (each camofox tab is isolated); a fresh SSO click spawns another isolated popup
needing the LinkedIn password (not in `ats-credentials.csv`) → blocked. Email/password
Free-Work login also fails if the account pre-exists ("This value is already used").

## 6. camofox tool surface — cfx.sh vs cfx.py
`cfx.sh` has `shot` + `click-xy`; `cfx.py` has NO `snapshot`/`upload`/`click_xy`/`shot`. For
screenshots + coordinate clicks shell out to `cfx.sh`. For uploads use the REST endpoint
directly (`upload-file.sh` needs a snapshot REF, which `display:none` file inputs lack):
```
POST /tabs/{tab}/upload  {"userId":CFX_USER,"selector":"input[type=file]","path":"<file in uploads/>"}
```

## 7. Credential walls everywhere? Pivot to LinkedIn Easy Apply (login-free)
When the remaining on-profile roles all sit behind credential walls (Free-Work SSO, "Apply
with Indeed" login, micro1), don't re-report the same blockers — source a FRESH LinkedIn
batch (widen title variants / 7d window) and prefer **"Easy Apply"** (login-free; uses the
logged-in profile + saved resume; application email = his profile email, compliant).

Drive it with `sites/linkedin/scripts/easyapply.py` — the modal is **shadow DOM**, so plain
`cfx` click/click-xy/evaluate silently no-op (the driver pierces the shadow root):
```
easyapply.py open          # click the page's Easy Apply button
easyapply.py dismiss-save  # cancel any "Save this application?" dialog
easyapply.py state         # {header, step, progress, nav, errors, labels}
easyapply.py next          # advance (Continue->Review->Submit); refuses on an empty required field
easyapply.py submit        # "SUCCESS: application sent." on confirmation
```
Contact info + often the resume are pre-filled (`state.labels` shows the selected resume).
Many Easy Apply jobs are Contact→Resume→Review→Submit (no questions step). Verify the "Your
application was sent" modal via `cfx.sh shot` + vision before logging Applied.

## 8. "Apply on company site" bypasses Indeed login
These open the EMPLOYER's ATS in a popup (sthree.com, hiresome.ai, micro1.ai). With a
LinkedIn/Indeed session live it proceeds with NO re-prompt and the application email is
Jane's own (entered on the employer ATS), not Indeed's. Prefer it over "Apply with Indeed"
roles, which require login and (under Gmail SSO) bind the wrong email.

## 9. Multi-step submit sequence + beating flaky `evaluate`
When `cfx.evaluate`/`cfx.sh eval` repeatedly return `None`/`500` on a heavy React page, reads
are flaking — the page is NOT dead. In order:
1. **Set every field via ONE `evaluate` per field** (value + `input` + `change`), not `cfx
   type` (per-char mis-binds react widgets). Phone per §1, react-selects per §2.
2. **Verify all fields in a SINGLE `evaluate` returning a `{label: value}` JSON map** — one
   read, not 20. If it 500s, fall back to `cfx.sh shot` + vision (reliable when evaluate is
   wedged).
3. **Submit via native `.click()` (§3).** No confirmation ⇒ an unfilled required field —
   `shot` + vision, fill the red-bordered field (invisible to the a11y snapshot), re-submit.
4. **Confirm ONLY via screenshot + vision** ("Application received" / "Thank you" / green
   check) — the `evaluate` confirmation reads are the least reliable signal here.

Concrete field order that worked (Hiresome): resume upload → text inputs by placeholder
match → phone (§1) → Expected/Current CTC currency `GBP` (§2, the Current one is the SECOND
`react-select-2` container) + values → Notice `Immediate` → the required consent field whose
placeholder IS the prompt prose → `you@example.com` → native `.click()` Submit. The consent
field + Current-CTC react-select surfaced only after the first submit returned no confirmation.
