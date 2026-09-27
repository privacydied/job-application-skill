# pinpointhq.com (Pinpoint ATS) — site notes

Seen live twice 2026-09-27 (Premier League Junior Motion Designer, CFC Product Analyst),
reached both times via an Adzuna `/jobs/land/ad/` redirect.

## ⛔ CAPABILITY GAP — unlabeled selects, JS-enhanced country/location combobox, intermittent eval 500s

Personal-details section (name/email/phone/address/postcode as plain `<input>`s) drives fine
with direct `getElementsByName` + native-setter dispatch. Beyond that the form gets hard to
drive reliably:

1. **Country/location field is NOT a plain `<select>`** — `document.getElementsByName(...)`
   for the country field returns an `INPUT` (hidden), and `document.querySelectorAll('select')`
   returns 10+ UNNAMED selects with no `name` attribute, making container-based label lookup
   unreliable (label-to-select DOM-proximity search grabbed the WRONG question's select at
   least once — matched "What are your preferred pronouns?" to a right-to-work select instead).
2. **`cfx.evaluate` intermittently 500s on a value-set-and-dispatch call against a TEXTAREA
   when the write code assumes `HTMLInputElement.prototype`** — Pinpoint mixes plain `<input>`
   and `<textarea>` for what look like equivalent free-text answer fields (`text_answer`
   attributes use the same Rails-array naming convention regardless of tag); check
   `.tagName` before choosing which prototype's setter to call, this is NOT a camofox-flakiness
   500, it's a genuine JS-thrown-error-surfaced-as-500 from calling the wrong setter.
3. **Genesis-application-form Yes/No questions are POSITIONAL, not labelled** — same pattern
   as Greenhouse's checkbox-fieldset gap (see `sites/greenhouse/NOTES.md`), except here they
   are `input[type=radio]` with generic `value="true"/"false"`, ordered per-question. Index
   into the flat `input[type=radio]` list two-at-a-time per question in DOM order.

**Net effect both times:** personal details + CV + basic Yes/No questions were fillable:
the location/country field and any select whose container can't be reliably resolved were
the genuine blocking gap. Logged `Blocked` both times rather than force a wrong answer.
Worth a `probe_widget.py`-style investigation before a third sighting, per the doctrine that
a stuck widget is a capability gap to debug, not a structural limit — two sightings isn't
yet the fork/build trigger, but is worth flagging for a focused follow-up session.
