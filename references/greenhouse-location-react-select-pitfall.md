# Greenhouse `Location (City)` react-select — fuzzy match binds the WRONG city (silent)

VERIFIED 2026-07-21 on posting `job-boards.eu.greenhouse.io/csjobs/jobs/4924778101`
(AISI Strategy & Delivery Adviser). Reproduced the failure, then the fix.

## The failure (silent — sails through review)
On this Greenhouse form, **`Location (City)`** is a `react-select` combobox (class
`select__input` inside `.select__control`), NOT a plain `<input>`. Driving it:

```python
atsform.fill("Location (City)", "London")          # reports OK, but does NOT bind
atsform.combobox_pick("Location (City)", "London") # returns OK, but binds the WRONG city
```

`combobox_pick` does exact-then-word-boundary-then-fuzzy match. The location option
list is global and contains many "London" substrings:
`London, England, United Kingdom` · `East London, Eastern Cape, South Africa` ·
`London, Ontario, Canada` · `Londonderry / Derry, United Kingdom` ·
`New London, Connecticut, United States` · `London Colney, Hertfordshire, United Kingdom` · …

The engine bound **`London, Ontario, Canada`** (first substring hit in DOM order) —
so the applicant's location was silently recorded as **Canada**. The `atsform.apply`
`review` step passed (field non-empty), so nothing flagged it. This is a factual error
that can sink an otherwise-good application.

Also: `atsform.fill` on this field returns `OK` but does **NOT** commit (it's a combobox,
not an `<input>`) — a fill-OK here is a false positive. Always verify via
`.select__single-value`.

## The fix
Pass the FULL disambiguated option string including country/region:
```python
atsform.combobox_pick("Location (City)", "London, England, United Kingdom")
```
If unsure of the exact string, open the menu once (async open — see
`references/greenhouse-csj-eeo-react-select.md` for the poll recipe) and dump the literal
option text; Greenhouse renders them comma-separated (`City, Region, Country`).

## Same trap applies to any common-name city
`Washington` (DC vs state) · `Newcastle` (UK vs AU) · `Wellington` · `Cambridge` · …
Always qualify with region/country. Never pass a bare city name to a Greenhouse location
combobox and trust the bind — confirm the `.select__single-value` text reads the qualified
string you intended.

## Why this isn't caught by the existing Ashby-location note
`references/camofox-form-filling-pitfalls.md` + the SKILL.md Ashby location combobox note
cover the async-empty-suggestion free-text fallback, but NOT the *wrong-city fuzzy bind* on
Greenhouse (whose suggestion source IS populated, so it commits a real but wrong option).
Different failure mode — this one is a correctness bug, not a capability gap.
