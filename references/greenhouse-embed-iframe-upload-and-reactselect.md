# Greenhouse embed-iframe CV upload wall + react-select recovery

## When this bites
Driving a Greenhouse application via `sites/greenhouse/scripts/gh_apply.py` (or a hand-rolled
`gh_config.json`). Two distinct failure modes, both specific to **company-site jobs whose apply
form renders inside a cross-origin iframe**:

1. The run prints `OK upload '#resume': chip=...` but submit fails validation with
   `Resume/CV is required`.
2. `set_radio` returns `NO_FIELD`, or `combobox_pick(label)` returns `NO_OPTION`, on a question
   that is clearly on the page (background-check consent, visa sponsorship, diversity,
   "hires in a limited set of countries").

## Root cause

### 1. Iframe CV-upload wall
For company-site jobs the harvested URL is the company page, e.g.
`https://www.storyblok.com/job?gh_jid=4908911101`. The real form lives in an
`<iframe src="https://job-boards.eu.greenhouse.io/embed/job_app?for=<co>&token=<id>">`.
Navigate to that `embed/...` URL directly — `#resume` is present there.

The camofox server's `POST /tabs/{id}/upload` binds the CV **chip visually** (driver logs
`OK upload: chip`), but the `<input type=file>` inside the iframe stays `files=0`, because the
server targets the top frame, not the nested iframe document. Validation then rejects
`Resume/CV is required`.

Top-level pages upload fine — Ashby, and any `job-boards.greenhouse.io/<co>/jobs/<id>` that does
**not** redirect to the company's own domain. The difference is purely whether `#resume` is in
the top document vs. nested in an iframe.

**Tell (the wall, not a driver bug):** after an "OK upload",
`cfx.evaluate("document.querySelector('#resume') ? document.querySelector('#resume').files.length : -1")`
returns `0`, OR `#resume` is inside an `<iframe>`.

### 2. react-select `question_NNNN[]` widgets
Storyblok (and similar) render structured-interview questions as react-select single-selects
(`#question_NNNN` with `.select__control` / `.select__option`), NOT native `<input type=radio>`.
`set_radio` only binds native radios → `NO_FIELD`. The shipped `combobox_pick(label)` ladder
(ArrowDown / trusted click / type-filter) often CANNOT open the option portal headlessly on
these → `NO_OPTION`. These are required; leaving them unset yields `This field is required`.

## Fix / workaround

### CV upload
- **PREFER a top-level Greenhouse board URL.** Test: `cfx.goto('https://job-boards.greenhouse.io/<company>/jobs/<id>')`;
  if it redirects to the company's own domain (iframe host), the form is iframe-embedded →
  upload will fail.
- **If the only URL is an iframe embed: this is a HARD WALL** with the current camofox `/upload`
  endpoint. Do NOT count as Applied. Log `Blocked` with `files=0` evidence
  (`applications/<co>-<role>/{review,confirmation}.png`) and note
  "iframe #resume — server /upload binds chip but input stays files=0".
- The `embed/...` URL is the iframe's own same-origin document, but the server's upload still
  targets the top frame, so it does not help.

### react-select recovery (single session — `goto` resets the page)
```python
import sys, time
sys.path.insert(0, 'sites/_common/scripts')
import cfx

def pick(q_id, opt_text):
    try:
        cfx.click_selector('#question_' + q_id, timeout=6)   # opens the option portal
    except Exception as e:
        print('click', q_id, e)
    time.sleep(1.2)
    for _ in range(6):
        try:
            r = cfx.evaluate(
                "(function(){var w=%s;var os=[].slice.call(document.querySelectorAll('.select__option'));"
                "for(var i=0;i<os.length;i++){if(os[i].innerText.toLowerCase().indexOf(w)>=0){os[i].click();"
                "return 'clicked:'+os[i].innerText.trim();}}return 'nomatch';})()" % repr(opt_text.lower()))
            print(q_id, '->', r); return
        except Exception:
            time.sleep(2)

pick('9187106101', 'yes')                    # background-check consent
pick('9187103101', 'no')                     # visa sponsorship
pick('9187105101', 'prefer not to answer')   # diversity
pick('9187102101', 'united kingdom')         # "hires in a limited number of countries"
```
Set **ALL** required selects in ONE python session (a fresh `cfx.goto` resets every field).
Verify with:
```python
cfx.evaluate("(function(){var ids=['9187102101','9187103101','9187105101','9187106101'];var r={};"
"ids.forEach(function(q){var c=document.querySelector('#question_'+q);"
"r[q]=c.closest('.select__container').querySelector('.select__control').innerText.trim();});"
"return JSON.stringify(r);})()")
```
Option-text cheat-sheet observed on Storyblok: consent → Yes/No; visa → Yes/No; diversity →
`No` / `Yes, I'll inform the recruiter in the event I'm called for an interview` /
`I prefer not to answer`; "hires-in" → country list (pick **United Kingdom** for a London
applicant).

## Anti-pattern
- Do NOT log these as `Applied` from a chip-only upload (files=0).
- Do NOT loop `combobox_pick` endlessly on a react-select that won't open — switch to
  `cfx.click_selector` + option-click after 1–2 failures.

## Honest convertible-inventory method (run BEFORE concluding a board is exhausted)
Re-harvest ats-direct fresh (`python3 sites/ats-direct/scripts/feed.py --all --where "" --force`),
then filter the on-lane design lane with: `check_title` eligibility (sanctioned, not ad-hoc
regex) + location ∈ {London, UK, remote-EU, EMEA, home based} + non-senior + ATS ∈
{greenhouse, ashby} (the only shipped guest drivers) + tracker dedup. For a junior→mid London
designer the genuine on-lane convertible set collapses to ~1 role per fresh harvest; state the
honest ceiling once after exhausting, then stop — never pad with off-lane / senior /
Easy-Apply rows (those are not truthful Applied).
