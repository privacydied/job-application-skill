# jobs.lever.co (Lever) — site notes (VERIFIED live 2026-08-15)

✅ **USE `scripts/lever.py`** — `apply <config.json> [--submit]` / `check` / `submit`.
First real submission: Metabase Product Designer, 2026-08-15 ("SUCCESS: submission
confirmed"). Lever is the THIRD guest-drivable ATS alongside Ashby and Greenhouse;
`ats_router.py` now returns `drivable: true` for it. The driver is deliberately thin —
every widget decision is delegated to `../_common/scripts/atsform.py` (AGENTS.md §6).

## ⛔ The two things that actually bite (both verified live, both now handled in code)

**1. The location autocomplete listens on `keydown`, NOT `input`.** Read Lever's own
`https://jobs.lever.co/js/retrieveLocations.js`: `$('input.location-input').on('keydown', …)`
→ `debouncedGetLocationResultsByInput()`. So a React native-setter + `input` event never
fires the search — the dropdown shows *"No location found. Try entering a different
location"*, nothing is picked, and the submit is rejected server-side with
*"Please select a location from the dropdown menu and try again."* That is a dead ringer for
the structural async-location wall on Ashby, **and it is not one** — it's an event-name
mismatch. REAL per-character keystrokes (`cfx.press`) populate the list every time; clicking
an option fills the hidden `selectedLocation` with Lever's structured `{"name":…,"id":…}`
payload, which is what the server validates. `lever.py set_location()` does this, and prefers
a UK match so "London" can't resolve to London, Ontario or London, Ohio (Lever offers both).

**2. Custom questions are `cards[<uuid>][fieldN]` with NO `<label>` and a generic
`placeholder` of "Type your response".** The question text sits in an ancestor div. This
broke `atsform._resolve` twice over: it skipped label-less fields entirely, and once a
placeholder fallback was added, EVERY card question resolved to the same meaningless string.
`_resolve` now walks ancestors for real text and treats `placeholder` as the LAST resort.

**3. hCaptcha is present but INVISIBLE** — `input[name=h-captcha-response]` arrives
pre-filled with a token and the `.h-captcha` widget has zero height. Per SKILL.md this is
NOT a CAPTCHA stop (same false-blocker class as Greenhouse's invisible reCAPTCHA); finish the
form and submit. A *visible* hCaptcha challenge would be a genuine stop.

**4. Ignore the static "File exceeds the maximum upload size of 100MB" string** — it is
permanent UI helper text, not a validation error; the attached résumé shows "Success!".

## Reaching the form
`jobs.lever.co/<company>/<posting-uuid>` → click **"Apply for this job"** → the form
at `jobs.lever.co/<company>/<posting-uuid>/apply`. (Navigate straight to the
`/apply` URL to skip the intermediate page.)

## Filling it (via `atsform.py`)
```
atsform.py fill "Full name" "Jane Doe"
atsform.py fill "Email" "you@example.com"
atsform.py fill "Phone" "+44 7700 900000"
atsform.py fill "LinkedIn" "..."                 # + GitHub/Portfolio/Other website (optional)
atsform.py upload "Resume" <resume>.pdf          # "Resume/CV" — required
atsform.py fill "Additional information" "@cover.txt"   # the cover-letter-equivalent textarea
# custom "cards" (screener questions): fill (text) / select (dropdown) / checkbox by label
atsform.py review "<Company>" <must,have,kw>
atsform.py submit "Submit application"           # success: "Thank you"/application-received
```
- Dropdowns: mix of native `<select>` and custom — `atsform.py select` tries native
  first, then react-select, so it covers both.
- **reCAPTCHA:** Lever can gate submit behind reCAPTCHA — per `SKILL.md`'s CAPTCHA
  directive, STOP + hold the filled form + hand to the user; never abandon it.
- If a label doesn't match, dump the fields first:
  `cfx.sh eval "[...document.querySelectorAll('input,textarea,select')].map(e=>(e.labels&&e.labels[0]||{}).innerText||e.name)"`
  and target by whatever label text is actually present.
