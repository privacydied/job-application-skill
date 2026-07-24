# Combobox config silent-fail: `fill` vs `combo` block

**Symptom:** Greenhouse/Ashby submit bounces with `BLOCKED — validation errors: - This field is required.` AND `CODE_MISSING — no verification code fetched`. Looks like an IMAP/OTP failure. **It isn't.**

**Root cause:** a required react-select field was placed in the config `fill` block instead of `combo`. `atsform.fill` types the value into the react-select's `<input role=combobox class="select__input">` and returns `OK (N chars)`, but the value never commits to react-select React state (no menu option is selected). The form is invalid → submit is rejected before any OTP email is sent → no code arrives → `CODE_MISSING`.

**Tell a field belongs in `combo` (not `fill`):**
- control is `<input role="combobox">` / `class*="select__input"`, inside a `[class*=control]` wrapper, OR a native `<select>`.
- Text/textarea fields (`<input type=text|email|tel>`, `<textarea>`) go in `fill`.
- Typical `combo` fields on Greenhouse/Ashby: Country, Location/City, "Are you authorized to work in the country…", "Have you ever worked for…", any work-authorization / consent react-select.

**Diagnostic chain (submit bounces + CODE_MISSING):**
1. Do NOT assume IMAP is broken — verify IMAP independently first if unsure (`python3 scripts/fetch_verification_code.py --sender greenhouse --company X --wait 30` should return NO_CODE, not crash; a crash = creds, not this bug).
2. Re-read the required fields; find which is EMPTY.
3. The empty one is a react-select you put in `fill`. Move it to `combo`. Re-drive.

**Verify a react-select actually committed** (after fill) — read the underlying input value, NOT the display:
```js
(() => { const el=document.getElementById('<id>'); if(!el) return 'no el';
  const ctrl=el.closest('[class*=control]');
  const sv=ctrl?[...ctrl.querySelectorAll('[class*=singleValue]')].map(v=>v.textContent.trim()):[];
  return 'singleValue='+JSON.stringify(sv)+' inputVal='+(el.value||''); })()
```
For Greenhouse, `el.value` holds the real value even when `singleValue` shows only a fragment (value="United Kingdom" but display "+44"). `inputVal==""` + `singleValue==[]` = NOT committed.

**Fix:** move the field to `combo` in the driver config. `combobox_pick` then opens the menu, filters, clicks the exact option → commits.

**Worked example — Figma Designer Advocate (London), Greenhouse.** The `authorized to work` field is a react-select. Putting it in `fill` was the exact bug that bounced the first attempt with `CODE_MISSING`. Correct split:
- `fill`: First Name, Last Name, Email, Phone, "Why do you want to join Figma?" (textarea)
- `combo`: Location (City)→"London", "Are you authorized to work in the country for which you applied?"→"Yes", "Have you ever worked for Figma…"→"No", "From where do you intend to work?"→"London", Country→"United Kingdom"

**Do NOT confuse with the Ashby location wall:** the Ashby `_systemfield_location` ("Where are you located?", `[placeholder="Start typing..."]`) is a DIFFERENT problem — even placed correctly in `combo`/`location`, no option list renders headless so the value won't bind on submit (seen on Paddle/Trainline/Accurx). Tell: `combobox_pick` prints `OK=freetext:… (async suggestion list empty — committed typed value)` yet the field still reads empty at submit → genuine `Blocked`, not a config fix.

## 2026-07-24 addendum — HEADLESS REACT-SELECT WALL (config-correct but still uncommittable)

Verified live across Monzo Lead/Staff Product Designer, Canonical Visual/UX/Usability, Cleo:
even with the CORRECT `combo` block, submit still bounces `This field is required` + `CODE_MISSING`
on specific required fields — **notably "Please confirm your UK Right to Work" / "🛂 UK Right to
Work status" and "🇺🇸 Are you a US Person?"**. These are NOT a `fill`-vs-`combo` config error:
the config split is right, the field id is resolved, `combobox_pick` types the value, but the
field's **option list renders ZERO nodes in the headless camofox session** (confirmed: open the
menu, wait 6s, `document.querySelectorAll('[class*=option]')` with `offsetParent!==null` = empty).
Without a live menu option, react-select's `onChange` never fires, so React state stays empty
(`singleValue=NONE` even though `input.value="Yes"`).

**This is a GENUINE driver wall, not a config fix.** Symptoms that distinguish it:
- `combobox_pick` returns `NO_OPTION:No options` (not `OK`).
- `atsform.combobox_pick`'s free-text fallback returns `OK=freetext:Yes (async suggestion list
  empty — committed typed value)` BUT the field still reads empty at submit (`singleValue=NONE`).

**Do NOT loop or "fix the config" — log `Blocked` with evidence** (`files=0` / "required react-select
renders no options headless — submit bounce"). Re-drive attempts on the same form are wasted (the
2026-07-24 Monzo Lead + Staff PD both hit the identical RTW wall; 2 attempts = hard stop per the
loop's 2-attempt cap).

**Probe before driving** to triage fast: `scripts/probe_required_fields.py <url>` prints the list
of EMPTY required react-selects on a form. A form whose EMPTY_REQUIRED contains a consent/RTW field
that won't load = wall. A form with `EMPTY_REQUIRED=[]` (e.g. SumUp's description page — but note
SumUp `sumup.com/careers` has NO `#resume` input, so it's not a gh_apply target anyway) = no combo
blocker from this cause.

**Why not just inject a synthetic `[role=option]`?** react-select binds its option handler via
React props on each option node, NOT DOM event delegation — a synthetically-injected node cannot
trigger `onChange`. So the only headless-safe commit path is the real menu option, which doesn't
render here. (A future fix would inject the value into react-select's controlled state via its
`onChange` call signature — out of scope, UNVERIFIED, do not ship blind.)

## Related (2026-07-24)
- `references/gh-apply-reentry-integrity.md` — when a re-drive flips an already-`Applied` row to
  `Blocked` (Greenhouse URL `?gh_jid=` vs feed URL + title-location mismatch in `classify_strict`
  dedup). Includes the restore recipe + the pre/post `tracker_stats.py --count` verification gate.
- `scripts/probe_required_fields.py` — batch-diagnose EMPTY required react-selects on a form before
  driving, so you can tell a fixable `combo` gap from the headless wall above.
