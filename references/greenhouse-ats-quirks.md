# Greenhouse ATS — live quirks (verified 2026-07-13, Rightmove User Researcher)

Condensed from a real submit. The shared `sites/_common/scripts/atsform.py` drives
Greenhouse fine, but three things will fool a careful agent into mis-reporting state:

## 1. Cover Letter "Enter manually" button is flaky — use file-Attach
The "Enter manually" button on the Cover Letter field returns `HTTP 500 Internal
server error` from camofox `/click` and NEVER reveals the free-text textarea (tested
2x, both attempts failed). The **reliable** path is to attach the cover letter as a
file: `txt`/`pdf`/`doc`/`docx`/`rtf` are all accepted
(`upload-file.sh <attach-ref> applications/<co>/cover-letter.txt`). The resume Attach
input works the same way. Don't burn attempts on "Enter manually" — just upload the file.

## 2. react-select `.value` stays empty after a successful select — verify by container text
After `atsform.py select "..." "Yes"` returns `OK:Yes`, the `<input role=combobox>`
(ids like `question_9300219101`) still reads `el.value === ""` and `aria-expanded:
"false"`. This is NORMAL for react-select — the chosen option is rendered as a
chip/option inside the field CONTAINER, not in the input's `.value`. A probe that
reads `el.value` will FALSELY report "answer empty / not selected".

**How to verify a Greenhouse select actually took:** read the wrapping container's
`innerText`, not the input value. A set option shows up as e.g.
`"option Yes, selected. Yes"` in the parent element's text. The `select` command's
own DOM match (scoped to the open listbox) is what confirmed it — trust that plus
the container text.

## 3. The ambient `grecaptcha-badge` is reCAPTCHA v3 — NOT a halt
Greenhouse renders a `grecaptcha-badge` div (class `grecaptcha-badge`, no iframe,
no "I'm not a robot" box). That is **reCAPTCHA v3** (invisible background risk token,
no user challenge). It is NOT a CAPTCHA halt and NOT something to solve or hold for.
Do not stop the loop for it. Contrast:
  - visible reCAPTCHA **v2** checkbox/invisible badge/image-grid → auto-solve via `recaptcha.py` (happy path)
  - **Turnstile / hCaptcha** → FULL immediate halt + hand to user (VNC)
  - `grecaptcha-badge` (v3) → ignore, just submit

## Net pre-submit check for Greenhouse
Email = you@example.com (vision/screenshot), attachments shown as attached (resume.pdf
+ cover-letter.txt filenames visible with an X), the 3 selects confirmed via container
text, and the v3 badge noted as non-blocking. Then `atsform.py submit "Submit application"`.

## 4. ⛔ Remix EEO comboboxes resist headless fill (OLIVER Integrated Designer, 2026-07-16)
Greenhouse's **EEO/demographic dropdowns** (religion, age range, socio-economic, gender
— render as `input.remix-css-1a0ro4n-requiredInput` with no `name`, placeholder "Select...")
are a DIFFERENT widget from the react-select in §2 and **do NOT fill via `atsform.select`**:
- `atsform.select` (built for native `<select>` / react-select) returns `NO_OPTION` — these
  are custom Remix comboboxes with no `<option>`/live-region the helper recognizes.
- Synthetic `InputEvent` dispatch (prototype-setter + `input`/`change`) leaves `el.value === ""`
  — Remix manages state internally and ignores synthetic events (same class as the old WTTJ
  raw-`.click()` gap).
- `POST /tabs/{tab}/type` with `mode:fill` returns `ok:true` but the value STILL doesn't bind
  (first call only; subsequent calls 500 on an invalid CSS selector — `:nth-of-type` on inputs
  is NOT reliable here; use a stable selector, not index).
- **Clicking the input opens the WRONG listbox** — a stray Country/ITI listbox overlay (still
  open from an earlier `select("Country")`) masks the real options; every `[role=option]` read
  returns country names ("Afghanistan+93…"), so you can't even see the EEO options to pick them.

**Net: these 4 EEO comboboxes are currently a DRIVER GAP, not a value error.** The form CAN
be 95% filled (CV attached, name/email/phone/Location/LinkedIn/portfolio/notice/salary all set,
Country selected) but submit rejects on "This field is required" for the unfilled EEO selects.
**Do NOT log it `Applied`** — it's `Blocked` ("Greenhouse Remix EEO comboboxes unfillable
headlessly"). A working driver needs the SmartRecruiters-style approach (Playwright `role=combobox`
+ `role=option` selectors via `/type`/`/click`, OR clicking the input by a STABLE selector and
selecting "I don't wish to answer" from the real listbox). If you build it, add the recipe here
and flip the OLIVER row from `Blocked` to `Applied` with proof.
- **EEO default answer:** "I don't wish to answer" (seen as an option on these OLIVER fields) or
  "Prefer not to say" where present — per the applicant-profile opt-out default. Never fabricate
  a demographic answer.

## 5. ⚠️ CORRECTION (2026-07-19) — Greenhouse CV upload WORKS via atsform.upload
The "ghost attach / hard stop" text below is **OUTDATED and was WRONG**. Verified live this
session: `atsform.upload("#resume", "/uploads/base-resume.pdf")` BINDS the CV on Greenhouse — the
filename ("base-resume.pdf") appears in the resume chip and the submit SUCCEEDS with a real
"Thank you for applying" confirmation. Critical detail: pass the **container path `/uploads/<base>.pdf`**,
NOT the host path (`/volume1/.../uploads/...`) — the host path returns HTTP 400. `input.files[0]`
reads NONE after a successful upload because Greenhouse moves the file into a chip; verify by the
**filename chip text**, not by `files.length`. This also works on Ashby (`_systemfield_resume` via
`ashby.py upload_cv`). So: upload via `atsform.upload(target, "/uploads/<base>.pdf")` and trust the chip.
(Workable/SmartRecruiters may still differ — re-verify per ATS if you hit a genuine ghost-attach.)

### (OUTDATED, DO NOT ACT ON) original §5 text:
`POST /tabs/{tab}/upload` with `selector:"input[type=file]"` + basename returns `{'ok':True,
'uploaded':'/uploads/...pdf'}` but the React-controlled `<input type=file>.files.length` stays `0`
on Greenhouse/Workable/SmartRecruiters — the file endpoint stages server-side but does NOT bind
to the React input (no CDP `setFileInputFiles`). … Until the container-restart deploys
`uploadViaChooser`, CV upload on Greenhouse/Workable/SR is a hard stop.
→ **Wrong.** The shipped `atsform.upload`/`ashby.py upload_cv` call `/upload` correctly and it
binds. Do not treat Greenhouse/Ashby CV upload as a wall.
