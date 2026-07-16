# jobs.lever.co (Lever) — site notes (recipe)

Common external ATS. Handled by the shared engine `../_common/scripts/atsform.py`
— Lever's apply form is structurally the same class as Greenhouse's (standard
`<label>`-associated inputs + a resume upload + free-text + custom dropdowns), and
`atsform` is verified on that pattern (Greenhouse, live 2026-07-12). **Not
independently live-tested on Lever this session** — treat the field labels below as
the expected recipe and adjust from a live field dump if they differ.

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
