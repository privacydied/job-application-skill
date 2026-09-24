# app.screenloop.com (Screenloop ATS) — site notes

Guest-drivable careers portal, format `app.screenloop.com/careers/<company>/job_posts/<id>`.
Standard fields render via a plain form (no iframe): name/email/phone/location/LinkedIn/
portfolio/"where did you hear about us"/legal-right-to-work radios/salary/consent checkbox
all bind cleanly through the generic `atsform.py apply` engine + `defaults: true`.

## Location field and "where did you hear" — react-select, use free-text fallback
Both are `react-select` comboboxes with async/empty suggestion lists in the headless
session. `combobox_pick`'s free-text fallback (commit typed value when the menu comes back
genuinely empty) handles both — put them under `"select"`, not `"fill"`. Verified
2026-09-04 (SAVA, UI Designer): Location and salary both bound via
`OK=freetext:<value> (async suggestion list empty — committed typed value)`.

## ⛔ Resume/CV upload — NO backing `<input type=file>` (verified 2026-09-04, SAVA UI Designer)
The "Resume / Curriculum Vitae" and "Cover Letter" widgets are `readonly` text inputs
(`name="atsApplicationFormResume.filename"`, `class="... cursor-pointer"`, placeholder
"Choose file") with a paired hidden `atsApplicationFormResume.content` field — **there is
no `<input type=file>` anywhere in the DOM** for `atsform.py upload` (or a bare
`cfx.post('/upload', ...)`) to target. Clicking the readonly text field presumably opens a
native OS file-picker dialog (a JS `FileReader`-driven widget), which camofox's REST
`/upload` endpoint cannot drive (it needs a real `<input type=file>` selector). Not yet
solved — tried: `atsform.py upload "Resume" <file>` → `FAIL upload: no file input for
'Resume'` (correct — none exists). Logged `Blocked`; retryable if/when cfx.py grows a
native-file-chooser-intercept upload primitive (Playwright's `page.on('filechooser')` +
`setFiles`, exposed through the camofox-browser REST layer). Do NOT re-attempt without that
— submitting past this without a resume would omit a required field.
