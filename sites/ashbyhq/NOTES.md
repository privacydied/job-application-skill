# jobs.ashbyhq.com (Ashby) — verified site notes

External ATS (green success banner "Your application was successfully submitted…"). Assumes
camofox env (`CFX_KEY`/`CFX_TAB`/`CFX_USER`) — see `../_common/scripts/cfx.sh`.

## ✅ USE `scripts/ashby.py` — the quirks below are handled in code
```
CFX_TAB=<ashby tab> python3 scripts/ashby.py reveal              # open the form (JS click)
python3 scripts/ashby.py upload-cv <file-in-uploads>.pdf         # CV -> #_systemfield_resume (waits out autofill)
python3 scripts/ashby.py upload "Portfolio" <portfolio>.pdf      # any other file field, by label/id
python3 scripts/ashby.py fill "Name" "Jane Doe"               # text/textarea by LABEL (uuids are random)
python3 scripts/ashby.py set-toggle "London office" Yes          # Yes/No toggle buttons
python3 scripts/ashby.py set-radio "right to work status" "Full right to work"
python3 scripts/ashby.py set-checkbox "fully understand and accept"
python3 scripts/ashby.py check                                   # FULL state: answered vs empty + alerts
python3 scripts/ashby.py submit                                  # JS-clicks + waits reCAPTCHA + verifies (IRREVERSIBLE)
```
Setters take a **substring of the question/label** (uuids random per posting; text stable)
and verify. `set-toggle` is idempotent. **Run `check` before submit** — it enumerates every
field (text/file/radio/toggle) answered-vs-empty; Ashby only shows "Missing entry for
required field: …" alerts AFTER a failed submit. `submit` is the one irreversible step —
call it only after your own review (SKILL step 6). Read the sections below only if `ashby.py`
misbehaves on a new posting.

## Reaching it + revealing the form
- From WTTJ: "Or apply on [Company]'s website" opens Ashby in a **NEW TAB** (popup) —
  `cfx.sh find-popup` and switch `CFX_TAB` to the `jobs.ashbyhq.com` tab.
- The posting shows only an **"Apply for this Job"** button; fields render ONLY after it's
  clicked (there are no inputs before that).

## ⚠️ Drive ALL Ashby buttons with JS `.click()`, not camofox click
- **Reveal + Submit** buttons trigger a re-render/nav → a camofox trusted `/click` HANGS
  ~30s (post-click ref rebuild stalls) then times out. `reveal`/`submit` use JS `.click()`
  (instant). (`cfx.py post()` now raises a catchable `CfxError` on read-timeout, so a lingering
  hang degrades gracefully instead of an uncaught `socket.timeout` crash.)
- **Yes/No toggles** don't nav, so camofox click returns fast — but silently DOESN'T register
  (`{ok:true}`, no selection). JS `.click()` registers. → Net rule: JS-click everything.

## ⚠️ File inputs have NO `name` — target by `id`
Résumé/CV → `input[id=_systemfield_resume]` (target the id DIRECTLY; do NOT use
`:not([accept*=image])` — on all-documents forms it grabs the wrong input and leaves the
required CV empty). Portfolio/other → its own per-posting uuid `id`, or the file input
following a matching label (`upload "Portfolio" …`). Stage the PDF in `uploads/` first; the
driver POSTs `/tabs/:id/upload` and confirms `files[0].name`. Portfolio can be a required FILE
(not URL) — if it's a website, generate a 1-page linking PDF (template
`applications/tilt-product-designer/portfolio.html`).

## ⚠️ Uploading the CV triggers "Autofill from resume" → form RE-RENDERS
After the résumé attaches, an "Autofill completed!" banner re-renders the form. Typed text
(name/email/phone/salary/notice/cover) SURVIVES, but **boolean Yes/No answers set before the
upload can RESET to unanswered.** → **Upload the CV FIRST, then set Yes/No, then re-verify
every required field immediately before submit.**

## ⚠️⚠️ Yes/No questions — toggle `<button>` pair, JS-click ONCE + verify by colour
Booleans are a pair of toggle `<button>`s (Yes/No) backed by a hidden checkbox. Scope to the
field by its checkbox name, click the target label ONCE:
```js
const inp=document.querySelector('input[name="<uuid>"]');
let box=inp; for(let i=0;i<6;i++){box=box.parentElement; if(box&&/Yes/.test(box.innerText)&&box.querySelector('button'))break;}
[...box.querySelectorAll('button')].find(b=>b.innerText.trim()==='No').click();
```
- **They TOGGLE** — clicking a selected button DESELECTS. Click once, verify by
  `getComputedStyle(btn).backgroundColor` (selected = blue `rgb(3,116,218)`; unselected =
  `rgba(0,0,0,0)`). **Do NOT trust `.checked`** — "No" selected still reads `checked=false`;
  the button background colour is the source of truth.
- **`set-toggle` fails LOUD on ambiguity (fixed):** it scores how filled each button is and
  returns null when the pair is indistinguishable (the old "first non-transparent match"
  always reported "Yes" and could skip clicking, leaving "No" on a live submit). A FAIL/
  ambiguous from `set-toggle` is a real "can't read state" — check the screenshot.
- An unanswered required boolean blocks submit with `[role=alert]` **"Missing entry for
  required field: <question>"** — grep for that.

## Text / number / reCAPTCHA / EEO
- Text: `_systemfield_name`/`_systemfield_email` have real names; phone `input[type=tel]`;
  custom fields (salary number, notice text, cover/visa textarea) have uuid names — fill via
  `/type` `selector` + `mode:fill` (no double-up bug like WTTJ).
- Right-to-work may be a **radio** group (`set-radio`), some acknowledgments a **single
  checkbox** (`set-checkbox`), not always a toggle pair.
- **Invisible reCAPTCHA** (`iframe[title=reCAPTCHA]`, `grecaptcha` undefined in page scope) —
  ran transparently on submit both runs, no visible challenge; `submit` polls ~18s for it.
- EEO (age/gender/transgender/orientation/ethnicity/disability) all **optional** — "I prefer
  not to answer" or blank is fine.
