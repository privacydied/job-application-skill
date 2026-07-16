# Workday create-account + apply flow (interpublic.wd5 / any *.myworkdayjobs.com)

Captured 2026-07-14 on Credera DevOps (interpublic.wd5.myworkdayjobs.com). The
`sites/myworkdayjobs/NOTES.md` covers Apply-click-drift and resume date-revert; this adds
the **create-account** step and the gotchas that cost a full attempt.

## Start
"Apply" on LinkedIn → `safety/go/?url=...myworkdayjobs.com/.../apply?source=LinkedIn`.
On the ATS: click **"Apply Manually"** (NOT "Sign In" — no forced login). This lands on
`/apply/applyManually` and shows a **create-account** form (NOT a hard stop).

## Create-account form (standard Workday)
Fields (by `data-automation-id`): `email`, `password`, `verifyPassword`,
`createAccountCheckbox` (terms), and a honeypot `beecatcher` (leave EMPTY).
```js
function set(id,val){const el=document.querySelector('input[data-automation-id="'+id+'"]');
  const proto=el.tagName==='TEXTAREA'?window.HTMLTextAreaElement.prototype:window.HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(proto,'value').set.call(el,val);
  el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));}
set('email','you@example.com'); set('password',PW); set('verifyPassword',PW);
// tick terms, leave beecatcher '' 
```
Password must satisfy: special char + uppercase + numeric + alphabetic + min 8 (e.g.
`Tq<rand><digits>!`). Generate, then **record site,email,password,date in
`ats-credentials.csv`** (NOTES §sign-in allows this).

### ⚠️ The "Create Account" button does NOT fire on JS `.click()`
`b.click()` does nothing (React). The button is
`button[data-automation-id="createAccountSubmitButton"]`. Click it via the **cfx trusted
click endpoint**, which Playwright drives:
```python
cfx.post(f"/tabs/{cfx._tab()}/click",
         {"userId": cfx._uid(), "selector": 'button[data-automation-id="createAccountSubmitButton"]'})
```
A plain `cfx.evaluate("...b.click()")` returned `clicked` but stayed on step 1 — the trusted
Playwright click advanced to "My Information". (Same lesson as the LinkedIn radio fix: React
buttons need a trusted click, not a synthetic one.)

### ⚠️ "captcha" false positive
After the click, `cfx.evaluate("document.body.innerText")` may match `/captcha/i` — but that
is the **`noCaptchaWrapper`** element **NAME**, not a real challenge. There were **no
captcha iframes** (`/recaptcha|hcaptcha|turnstile/i` over `iframe[src]` → empty) and the
vision screenshot showed no CAPTCHA. Do NOT treat `noCaptchaWrapper` as a CAPTCHA halt.

## My Information (step 1/5)
Driven by `atsform.py` (label-based) + direct `data-automation-id` sets for name fields:
- Text fields by label fail for First/Last name (nested label) → set via
  `div[data-automation-id="formField-legalName--firstName"] input`.
- Country: `atsform.py select "Country" "United Kingdom"` works.
- **Source ("How Did You Hear About Us?*", REQUIRED):** hierarchical prompt. It is a
  `searchBox` input. Type doesn't filter. The options are categories (Job Boards,
  External Channels, …). Click "Job Boards" via Playwright
  (`div[data-automation-id="promptOption"]:has-text("Job Boards")`) → it DRILLS IN to
  sub-options (LinkedIn, Indeed, Glassdoor…). Then click "LinkedIn".
- Phone type defaults to "Mobile" — fine.
- Always re-`radio` the Omnicom "ever employed by" question = **No** (new required field
  appears on My Information after first Continue).

## My Experience (step 2/5) — resume upload is the wall
Resume/CV upload control: `input[data-automation-id="file-upload-input-ref"]`. The cfx
`/upload` endpoint resolves the file **relative to `/uploads/`** and takes param **`path`**
(NOT `file`):
```python
cfx.post(f"/tabs/{cfx._tab()}/upload",
         {"userId": cfx._uid(), "selector": 'input[data-automation-id="file-upload-input-ref"]',
          "path": "credera-devops.pdf"})   # basename in sites/_common/uploads/
```
Even staged correctly, `input.files[0]` stayed `NONE` across retries — the hidden input
does not bind via camofox. Combined with the documented Review-date-revert risk (submitting
would send wrong dates to a regulated employer), log **Blocked** and do NOT submit. See
`references/workday-resume-upload-unbindable.md`.
