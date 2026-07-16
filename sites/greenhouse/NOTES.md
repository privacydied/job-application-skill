# boards.greenhouse.io / job-boards.greenhouse.io (Greenhouse) — verified site notes

Very common external ATS. **No dedicated script needed** — the shared engine
`../_common/scripts/atsform.py` does the whole form (verified live on Figma's
board 2026-07-12: `fill` + react-select `select` both worked). This file is the
recipe. Assumes camofox env exported (`CFX_KEY`/`CFX_TAB`/`CFX_USER`).

## Reaching the form
Job URLs: `job-boards.greenhouse.io/<company>/jobs/<id>` (new domain) or the older
`boards.greenhouse.io/<company>/jobs/<id>`; a company "careers" page usually links
out to these. **The application form is INLINE on the job page** — unlike Ashby,
there is no "Apply for this Job" gate to click first; the fields are already there
(scroll down past the JD). ("Apply" / "Quick Apply with MyGreenhouse" buttons are
for logged-in Greenhouse accounts — ignore, just fill the inline form).

## Filling it (all via `atsform.py`)
Everything is a standard `<label>`-associated control, so target by label text:
```
atsform.py fill "First Name" "Jane"
atsform.py fill "Last Name" "Doe"
atsform.py fill "Email" "you@example.com"
atsform.py fill "Phone" "+44 7700 900000"
atsform.py select "Country" "United Kingdom"     # react-select (input role=combobox, id via label for=)
atsform.py fill "Location (City)" "London"
atsform.py fill "LinkedIn Profile" "..."         # optional
atsform.py upload "Resume" <resume>.pdf          # 1+ file inputs (Resume/CV, sometimes Cover Letter)
# custom screener questions: fill (text) or select (react-select dropdowns) by their label
atsform.py review "<Company>" <must,have,kw>     # wrong-company / placeholder / empty-required guard
atsform.py submit "Submit Application"           # success: page shows "Thank you"/confirmation
```
- **Dropdowns are react-select** (Country, custom questions) — `atsform.py select`
  handles them (native `<select>` is rare here). Options may combine values, e.g.
  Country shows "United Kingdom +44" — substring match ("United Kingdom") still hits.
  - **How `select` opens them (verified live on Cleo 2026-07-13):** it JS-focuses the
    combobox and presses a real **ArrowDown** to open the menu, then matches the option
    inside that input's `aria-controls` listbox. This replaced the old trusted-`/click`
    approach, which on Greenhouse **hangs ~30s** (the click fires a React re-render
    Playwright waits on) and often leaves the menu shut → spurious `NO_OPTION`. A
    synthetic `value`-set does **not** open the menu either (`aria-expanded` stays
    false). If you ever drive one by hand, use ArrowDown, not a click.
  - **`[role=option]` is globally polluted:** the phone field (react-phone-number) keeps
    its full ~200-country option list in the DOM at all times, so an unscoped
    `document.querySelectorAll('[role=option]')` always returns countries. `select` now
    scopes to the open menu's `aria-controls` listbox — do the same in any ad-hoc probe.
  - **The phone `Country*` selector (flag + "+44") is the country field** — one control,
    not a separate empty required "Country" text box. Its label reads `Country*` and its
    combobox value shows the dial code; don't chase a phantom empty country field.
- **EEO / demographic** block at the bottom (Gender, Race, Veteran, Disability) is
  optional react-select — leave blank or pick "Decline to self identify".
- **reCAPTCHA:** Greenhouse commonly gates submit behind an (often invisible)
  reCAPTCHA. Per the CAPTCHA directive in `SKILL.md`: if a challenge appears, STOP,
  hold the filled form, and hand it to the user — do not abandon it.

## ✅ Newer `job-boards.greenhouse.io` (Remix) — react-select combos: use `atsform combo`
The modern Greenhouse board (`job-boards.greenhouse.io/...`) renders every dropdown as a
**react-select `input[role=combobox]`** that **ignores synthetic events** and on which
camofox's **`/click` hangs** (Hermes got stuck here). The verified driver (2026-07-16, OLIVER
Integrated Designer — submitted, "Thank you for applying"):
```
python3 sites/_common/scripts/atsform.py combo "#question_67935604" "No"     # picklist combos
python3 sites/_common/scripts/atsform.py combo-type "#candidate-location" "London"  # type-to-search
```
Mechanics (in `atsform.react_select` / `react_select_type`): **JS-focus the input** (focus is
the load-bearing step — `click_selector` times out and won't move focus between combos), then a
**REAL `ArrowDown`** (`cfx.press`, not a dispatched key) opens the listbox; read options via
`aria-controls`; **keyboard-navigate** (menu opens with index 0 highlighted → `ArrowDown` i
times → `Enter`). For a type-to-search combo (Location), type the text **char-by-char with real
keypresses** then **`Enter`** — the first suggestion is auto-highlighted (do NOT press ArrowDown
first, or you select the 2nd, e.g. "East London, South Africa").

⚠️ **The demographic EEO combos are OPTIONAL (`aria-required=false`) UNTIL you tick the
"I consent to … demographic data" checkbox — which is itself required (`*`) and, once checked,
flips those combos to REQUIRED.** So after ticking consent you must set every demographic combo
(age, gender, religion, ethnicity, orientation, disability, socio-economic). Each offers
**"I don't wish to answer"** — the honest default for decline-to-disclose (set age to the real
band per the profile). The genuinely-required non-demographic combos are Country (phone dial
code), Location (City), sponsorship, reasonable-accommodations, and "Point of data transfer"
(single option "I acknowledge this"), plus a required **right-to-work TEXTAREA** (plain — use
`fill`, not `combo`). A stale "This field is required" can persist after a valid pick; the real
signal is the redirect to `/confirmation`.
