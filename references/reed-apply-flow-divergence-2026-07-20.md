# Reed apply-flow divergence (2026-07-20)

## What changed
`scripts/reed_apply.py` was verified working **2026-07-15** (simple Yes-radio →
Continue → Submit modal). As of **2026-07-20** that verification NO LONGER holds
for current postings. Driving a batch of 21 on-lane Reed roles produced **0
submissions** — not a flake, a real flow divergence.

## Two distinct failure modes observed (live, on `CFX_TAB`)

### Mode A — external-ATS redirect (new tab the agent can't follow)
- **F5 "UX Designer" (id 56992386):** clicking "Apply now" makes the button
  vanish (`Apply now` no longer in `document.body.innerText`) but NO Reed modal
  opens, NO `<iframe>` appears, and no "redirect / leaving reed" text is present.
  The page opened the employer ATS in a **NEW browser tab** that camofox's
  single-tab model does not surface — the agent can't follow it, verify it, or
  confirm submission.
- **Impact:** account wall until the downstream ATS has credentials. Log `Blocked`
  (retryable), do NOT pad. The single-tab serialization rule means we physically
  cannot drive a new-tab redirect.

### Mode B — looping "How did you hear about this job?" checkbox step
- **AJ Bell "UX Writer" (id 57119546):** the Apply-now modal opens to a
  **checkbox list** ("Radio Advert", "Other (Please mention in your
  application/cover note)", …) + a "Continue" button — NOT the Yes-radio the
  driver expects.
- `answer_yes_and_advance()` clicks Continue, but the modal **re-renders to the
  SAME step** (checkbox present again, no Submit, no Yes-radio). It never reaches
  a Submit step. AJ Bell routes to its own ATS after this pre-step, so the
  headless flow just loops.
- Confirmed: after checking "Other" + Continue, `document.body` still shows the
  same "heard about this job" step and the job page still shows "Apply now"
  (nothing registered).

### Mode C — no drivable Reed-native modal at all
- Sampled 8 of 21 on-lane roles: **none** exposed a Yes-radio or a "Submit
  application" button after Apply-now. Only AJ Bell showed the "hear about" step.
  The rest behaved like Mode A (external redirect) without a visible modal.

## Why the driver fails
`reed_apply.py::answer_yes_and_advance` only handles:
  1. Yes-radio click, then
  2. "Submit application" (click) else "Continue" (click).

It does NOT handle:
  - a **checkbox** "hear about" step (Mode B) — Continue loops,
  - an **external-ATS new-tab redirect** (Mode A) — no Submit to click on the
    Reed page at all.

## Diagnosis recipe (run BEFORE mass-driving Reed)
```python
import sys,time,re; sys.path.insert(0,'sites/_common/scripts')
import cfx
def classify(job_id):
    cfx.navigate(f"https://www.reed.co.uk/jobs/ux-designer/{job_id}"); time.sleep(8)
    cfx.evaluate("(()=>{const b=[...document.querySelectorAll('button.btn-primary')].find(x=>x.innerText.trim()==='Apply now');if(b)b.click();})()")
    time.sleep(5)
    txt=cfx.evaluate("document.body.innerText")
    return dict(
      hear_about=bool(re.search(r'heard about this job',txt,re.I)),
      yes_radio=cfx.evaluate("!!document.querySelector('input[type=radio]')"),
      submit=bool(re.search(r'Submit application',txt)),
      apply_still_there='Apply now' in txt,   # True after Apply-now w/ no modal = Mode A redirect
    )
```
- `hear_about=True` + loops on Continue → Mode B.
- `apply_still_there=True` and no modal → Mode A (external ATS).
- neither radio nor submit → Mode A.

## What needs fixing in `reed_apply.py` (engineering task — not yet done)
1. **Mode B:** detect the "hear about" step (checkbox/select), select an option
   (e.g. the "Other" checkbox; value varies per poster), click Continue, then
   re-enter the loop — but expect AJ Bell to still hand off to an external ATS.
2. **Mode A:** after Apply-now, detect a new tab / external redirect and follow
   it (`cfx.py click-follow`) — but the downstream ATS is an account wall, so
   this mostly converts to `Blocked` anyway.

## Honesty guard
Do NOT log these as `Applied` from a "the modal closed" signal — verify against
the live `https://www.reed.co.uk/account/jobs/applications` list (count
"Withdraw application" buttons / check the specific title appears). A closed
modal with no Applications-list entry = NOT submitted.
