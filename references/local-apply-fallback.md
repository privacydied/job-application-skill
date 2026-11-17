# Local-browser file attach fallback

Scope: a verified SUB-TECHNIQUE for attaching a local file to a web form, not a complete
application workflow. Use when the sanctioned `atsform.upload` / `POST /tabs/<tab>/upload`
returns `file not found under /uploads`: the browser container's bind mount is not the
skill's local `uploads/` directory, so re-copying the file locally cannot fix it.

## Try inline uploads first
Before opening a local browser, check the sanctioned inline path: if the camofox server has
the inline-upload patch, set `CFX_UPLOAD_MODE=inline` and re-run `atsform.upload` with the
file staged in the skill's local `uploads/`. A successful `OK upload '<id>': <filename>`
means no local-browser fallback is needed. Only fall through when inline mode is genuinely
unavailable and a local file attach is the remaining route.

## Staging preference
Stage CVs and scratch artifacts in the user's home directory (`~/`), not in a NAS-hosted
skill tree, unless the user explicitly asks for the remote path. Do not attempt to write
into a remote skill tree just to make a bind mount see the file.

## Attach from a local browser session
1. Stage the file in `~/`, e.g. `~/jane-doe-cv.pdf`.
2. In a local browser session, obtain the file-input node with CDP:
   `DOM.getDocument` -> `DOM.querySelector(selector='#_systemfield_resume')` ->
   `DOM.setFileInputFiles(nodeId=<id>, files=['<absolute local path>'])`.
3. Verify by reading the input back: `input.files[0].name` must equal the staged filename.

This was verified against an Ashby Resume field; once attached, the form is still subject to
its normal gates (screeners, CAPTCHA, submit confirmation).

## Gates that remain separate
- A filled form is NOT a submitted application. Log `Applied` only with captured confirmation
  proof or a matching confirmation email; otherwise the tracker stays at zero.
- A visible reCAPTCHA challenge is its own gate. Prefer the sanctioned camofox `recaptcha.py`
  path when that browser is usable; do not infer success from a loading Submit button.
- If a CAPTCHA or login wall blocks the submit and the user has authorized skipping, record
  the skip (company, role, URL, reason) and move to the next queued posting. Never keep
  retrying the challenge or claim an `Applied` row without captured proof — a form left in
  a loading state is not a submission.
