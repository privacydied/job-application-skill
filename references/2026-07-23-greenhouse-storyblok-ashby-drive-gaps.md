# 2026-07-23 — Greenhouse/Storyblok + Ashby drive gaps

Concrete, reproducible DRIVE findings from a 20-application push (Jane Doe,
junior→mid product/UX designer, London/remote). New walls not covered by
`references/2026-07-22-drivability-gaps.md`. Capture here so a future session
doesn't burn two attempts re-discovering them.

---

## 1. Storyblok (and other `job-boards.eu.greenhouse.io` embed boards) — structural Blocked

- **The harvested URL is the company-site page, NOT the apply form.**
  Harvested: `https://www.storyblok.com/job?gh_jid=4908911101`.
  `gh_apply.py` does `cfx.goto(url)` then looks for `#resume` →
  `RESUME_UPLOAD_FAIL no file input for '#resume'`. The real form is an
  **embed iframe**: `https://job-boards.eu.greenhouse.io/embed/job_app?for=storyblok&token=4908911101`.
  Navigate DIRECTLY to that embed URL — `#resume` is then present and the
  default fill (name/email/phone/portfolio/city/notice) works.
- **Required fields use custom non-native radios.** Background-check consent
  ("As part of our recruitment process, we conduct background checks… Would you
  be willing to undergo these…"), visa sponsorship, salary band, and diversity
  are `div`/`button` custom widgets — there is NO `<input type=radio>` with a
  matching label, so `gh_apply.set_radio` / `atsform.set_radio` return
  `NO_FIELD`. A manual DOM probe found NO bindable Yes/No option buttons in
  those sections (only generic Attach / Submit). **This is a structural wall,
  not a flake** — after `check()` shows `errors:[]` but submit still reports
  `This field is required.` on an unbindable consent radio, log `Blocked`
  (drive-gap class) with a `blocked.png` + `blocked.txt`; do NOT loop or
  retry a 3rd time.
- Verdict evidence pattern: CV uploaded + text fields filled OK, but submit
  blocked on the unbindable required radio. The Ashby `set_radio_native`
  label-click fix does NOT transfer here (no `<label for>`/native input pair).

## 2. Ashby — `drive_ashby.py` config `location` + salary DON'T commit on submit

- **Symptom:** `ashby.check()` returns `errors:[]` and the config `location`
  string reports `set:United Kingdom`, but `ashby.submit()` fails with
  `Missing entry for required field: Where are you located?` AND
  `What are your annual salary expectations?`.
- **Root cause:** the config's location commit targets
  `input[role=combobox]` (placeholder "Start typing…") but Ashby's required
  `_systemfield_location` does not bind from the bare config set, and the
  salary is an `input[type=number]` the config never touches.
- **Fix (verified to clear the validator — Paddle Web Designer submitted
  after this):** after `drive_ashby.py` fills, set BOTH directly via the
  native-setter, THEN `ashby.check()` → `errors:[]` → `ashby.submit()`:
  ```python
  # Location combobox (required): commit + Enter
  cfx.evaluate("""(function(){
    var i=document.querySelector('input[role=combobox]');
    if(!i) return 'NO_LOC';
    var p=Object.getPrototypeOf(i), d=Object.getOwnPropertyDescriptor(p,'value');
    if(d&&d.set) d.set.call(i,'United Kingdom'); else i.value='United Kingdom';
    i.dispatchEvent(new Event('input',{bubbles:true}));
    i.dispatchEvent(new Event('change',{bubbles:true}));
    i.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));
    i.dispatchEvent(new KeyboardEvent('keyup',{key:'Enter',bubbles:true}));
    return 'loc_set:'+i.value;
  })()""")
  # Salary (required, input[type=number])
  cfx.evaluate("""(function(){
    var n=document.querySelector('input[type=number]');
    if(!n) return 'NO_NUM';
    var p=Object.getPrototypeOf(n), d=Object.getOwnPropertyDescriptor(p,'value');
    if(d&&d.set) d.set.call(n,'60000'); else n.value='60000';
    n.dispatchEvent(new Event('input',{bubbles:true}));
    n.dispatchEvent(new Event('change',{bubbles:true}));
    return 'sal_set:'+n.value;
  })()""")
  ```
- **Reusable:** ANY Ashby role whose form has a required location combobox +
  salary field needs this manual commit step. The `drive_ashby.py` `location`
  config key ALONE is insufficient; the salary `input[type=number]` is never
  set by the driver at all.

## 3. Convertible ceiling reaffirmed (2026-07-23 fresh re-harvest)

- `sites/ats-direct/scripts/feed.py --all --where "" --force`
  → **4,289 fresh jobs / 68 companies / 0 tracked**.
- `scripts/convertible_preaudit.py /tmp/atsdirect_fresh.json`
  → 12 real-drivable → only ~4–5 on-lane for a junior→mid London/remote
  product-UX designer:
  - Paddle — Web Designer (Ashby) → **Applied** (real submit, proof captured).
  - Storyblok — 2D Motion Designer (Greenhouse embed) → **Blocked** (custom-radio wall, §1).
  - Lendable — Creative Designer (Ashby) → already **Applied** in tracker.
  - Experian — Product Designer (SmartRecruiters) → already **Applied** (no driver; VNC-only).
  - Figma — Designer Advocate (Greenhouse) → already **Skipped** (bespoke Figma form, 2 prior attempts).
- Reinforces the SKILL.md re-harvest guard: do NOT conclude exhaustion from a
  cached `/tmp/*.json` or the 121-row `queue.jsonl` (queue rows dropped their
  `title` → `classify_strict` mis-bucketed on-lane design roles as `offlane`).
  Always re-harvest fresh + make real live attempts before logging Blocked.
