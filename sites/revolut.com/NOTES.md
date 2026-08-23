# revolut.com ("Revolut careers portal") — site notes

Revolut's own careers site (revolut.com/careers/...), reached from a totaljobs.com
listing via Apply → totaljobs StepStone login → external redirect to
`revolut.com/careers/position/<slug>-<uuid>/` → `revolut.com/careers/apply/<uuid>/`.
Custom in-house React apply form (not Greenhouse/Ashby/Lever — no generator meta,
no greenhouse/ashby script tags).

## ⛔ Custom Select widget option-click CRASHES THE CAMOFOX TAB (verified 2026-08-23, 3x)
Every dropdown on this form (`button "Select one"` in the a11y snapshot) is a custom
combobox whose underlying `<input type=button>` has **no `name`/`id`/`aria-label`** —
`atsform._resolve()`'s `sel()` cannot address it, so plain `fill`/`select` always report
"no text field" / "no native select/react-select/Workday multiselect for '<label>'".
`atsform.combobox_pick` DOES resolve these (falls through to the free-text/input-less
path) and CAN commit a value two ways:
- **freetext-fallback** (`OK=freetext:<value>` — the async suggestion list came back
  empty) — SAFE, verified across ~6 fields (ethnicity, "how did you hear", "met at a
  conference", "previously employed at Revolut", notice period) with the tab staying
  alive afterward.
- **option-click** (`OK=option-click:<value>` — a real matching option existed and got
  clicked) — **UNSAFE. Every single time this strategy fires, the camofox tab dies
  immediately after** (`HTTP 404 Tab not found` on the very next `/evaluate` call).
  Reproduced 3 times across 2 different postings (Product Designer, Product Designer
  (Platform)) on 3 different fields ("Select gender you identify with", "Have you
  designed end-to-end web-based products or SaaS platforms?"), so this is the widget's
  option-click handler (likely a heavy transition/animation or an app-level route change
  fired from its `onChange`), not a fluke tied to one field or one posting.

**Net effect:** any REQUIRED field on this form whose value happens to be a real
listed option (Yes/No questions, EEO gender/ethnicity where a real option exists) is
effectively **unfillable without killing the session** — you cannot choose to force the
freetext path; `combobox_pick` tries option-click first when a match exists. Optional
fields where no matching option exists commit safely via freetext and are fine to fill.

**Verified-safe fields on this form:** CV upload (raw `input[type=file]` has no id —
POST directly with `selector: "input[type=file]"`, bypass `atsform.upload()`'s id-based
resolver), Full name / Email / Phone number / LinkedIn / portfolio-link text inputs
(all react-controlled with **no name/id**, only a `placeholder` — tag them with a
throwaway `el.id = "..."` via `cfx.sh eval` first, then `atsform.fill("#tagged-id", …)`),
salary-expectations text input (has a real `name` like
`additional_questions.sections.<N>.questions.<N>.answer` — inspect and use `[name="…"]`
directly), the two-option "Interview transcripts" radio group and pronoun checkboxes
(real `<input type=radio/checkbox>`, `atsform.set_radio`/`set_checkbox` bind them fine).

## Known failure modes + verified fixes
- **totaljobs' `/click` REST endpoint went globally broken mid-drive** (`cfx.py
  click-follow` returned `outcome: engine_broken_needs_restart` after a verified control
  click also failed) while `/evaluate` kept working fine. **Do NOT restart the shared
  camofox engine on a multi-lane drive** — it drops every open tab, including sibling
  lanes' in-flight applications. Workaround: click via `cfx.sh eval
  "document.querySelector(...).click()"` instead of the `/click` endpoint — this reaches
  the button via the DOM and worked when `/click` didn't.
- **Same-tab jump to an unrelated job's `.../application/confirmation/success` URL**
  was observed once on the SAME tab right after the eval-click workaround above, for a
  posting UUID that did not match anything driven in that tab. Treat any confirmation
  page reached WITHOUT having filled/submitted a form on that same tab as **camofox
  session bleed, not a real submission** — do not credit it as `Applied`. Close the tab,
  re-navigate fresh, and re-verify `location.href` matches the posting you expect before
  proceeding.

## Status (2026-08-23)
Both London Product Designer roles sourced from totaljobs this run logged `Blocked` —
the option-click widget crash hit on the very first required Yes/No question on each,
after the CV + text fields were already filled successfully. Retrying with the exact
same driver will reproduce the same crash; this needs a camofox-side fix (or an
atsform.py `combobox_pick` mode that refuses option-click and always forces the
freetext-commit path) before either posting can be pushed to a real submission.
