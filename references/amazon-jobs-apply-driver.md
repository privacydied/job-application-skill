# amazon.jobs — headless apply driver (verified 2026-07-16)

## Reality (2026-07-16)

- **Login:** the operator logs into amazon.jobs once in the camofox session (email/password or SSO). The session PERSISTS in the browser profile across tabs/runs — re-verify with a snapshot showing `My career | My applications | My profile | Sign out` before applying. Do NOT treat amazon.jobs as a hard login wall once the operator has authenticated.
- **How roles get here:** WTTJ `Apply` and The Dots `Apply` open the employer ATS in a **NEW tab** (use `cfx.py click-follow`, never a plain click). For Amazon postings this lands on `amazon.jobs/en[-gb]/jobs/<id>/<slug>`. Adzuna's "Apply for this job" is a JS-redirect LOOP (walled) and does NOT reach amazon.jobs — so Adzuna-inventory roles are NOT amazon.jobs-applyable headlessly.
- **Genuinely-applyable set WITH an amazon.jobs login:** only the amazon.jobs-routed roles (~3–4 in Jane's sourced inventory: WTTJ UX Designer Amazon `3155480`, Dots UX Researcher `10459975` [APPLIED, confirmed `summary?result=success`], Dots UX Visual Designer `10449797` [operator did manually]). Adzuna's 186 on-profile roles are walled at the board, so "191 roles" from the aggregator boards ≠ 191 applyable amazon.jobs roles.

## The wizard (multi-step, auto-saved)

URL after `Apply now`: `amazon.jobs/en-US/applicant/jobs/<id>/apply`. Steps are tabs with `aria-selected="true"` marking the current one. The `Review & submit` tab stays `[disabled]` until every step is completed. **The form AUTO-SAVES** — if a run times out mid-form, re-running `amazon_apply.py` on the same URL RESUMES from the saved state (no re-typing).

Steps (order varies slightly by role):
1. Contact information — pre-filled from profile (skip)
2. SMS Notifications — **`Skip & continue`**
3. General questions — pre-filled (continue)
4. Education — pre-filled (continue)
5. Job-specific questions — **REQUIRED screening** (see below)
6. Work Eligibility — **REQUIRED radios** (see below)
7. Resume — pre-filled (continue)
8. Acknowledgement & consent — pre-filled (continue)
9. EEO Self-Identification — optional (continue)
10. Military Status — optional (continue)
11. Review & submit — enabled only when 5+6 done → click → confirm

## Field techniques (the non-obvious parts)

**Native `<select>` (screening Yes/No):** set value `"1"` (Yes) via the prototype setter + `change` event. Value map: `""` empty, `"1"` Yes, `"2"` No.
```js
var s=document.querySelector('select');
var d=Object.getOwnPropertyDescriptor(Object.getPrototypeOf(s),'value').set;
d.call(s,'1'); s.dispatchEvent(new Event('change',{bubbles:true}));
```

**ARIA comboboxes (Job-specific step has up to 11):** NOT native `<select>`. Open by `.click()`, then click the visible `Yes` option (`[role=option]` / `li` with `textContent.trim()==='Yes'`, `offsetParent!==null`). Skip nav chrome (`Preferences`, `My progress`, `Show all answers`). If no Yes option, `Escape`.
```js
var cb=[...document.querySelectorAll('[role=combobox],[aria-expanded]')].find(e=>
  e.getAttribute('aria-expanded')==='false' &&
  /question|experience|portfolio|design|degree|research|work|adjust/i.test((e.closest('form')||e.parentElement).innerText));
cb && cb.click();
var y=[...document.querySelectorAll('[role=option],li,[class*=option]')].find(o=>o.offsetParent!==null && /^yes$/i.test(o.textContent.trim()));
y && y.click();
```

**Required portfolio text input:** `input[type=text]` whose surrounding container text contains "portfolio". Set via prototype setter + `input`+`change` events (React controlled input — plain `.value=` assignment is lost). Value: `https://example.com`.
```js
var i=[...document.querySelectorAll('input[type=text]')].find(e=>/portfolio/i.test((e.closest('div')||{}).innerText||''));
var d=Object.getOwnPropertyDescriptor(Object.getPrototypeOf(i),'value'); d.call(i,'https://example.com');
i.dispatchEvent(new Event('input',{bubbles:true})); i.dispatchEvent(new Event('change',{bubbles:true}));
```

**Radios (Work Eligibility):** `input[type=radio]` with `value` `"YES"|"NO"|"NEVER"` and `aria-checked`. For Jane (British, no Amazon history, no sponsorship needed, not a government employee) the answer is **NO / NEVER on every question** — click every radio whose `value==='NO'||value==='NEVER'`. Do NOT value-set; use `.click()`.
```js
for(var r of document.querySelectorAll('input[type=radio]')){ if(r.value==='NO'||r.value==='NEVER') r.click(); }
```

**Submit:** click the `Review & submit` button (enabled), then any `confirm` / `submit application` button. **Success = URL ends `…/summary?result=success`** and the page shows "Thank you for applying!". Capture that as the `--proof` artifact.

## The driver — use the COMMITTED one, do NOT rebuild

`scripts/amazon_apply.py` is the single source of truth (drives the full ~10-step React SPA + conditional cascades + resume upload + pre-submit consent modals, and verifies via the applicant dashboard). Usage:

```bash
source .jobenv.persist
python3 scripts/amazon_apply.py <jobId|jobUrl> [--resume am-uxd.pdf]
```

It is built ENTIRELY on the `atsform` React-widget helpers (`rclick`/`answer`/`advance`/`active_step` + the React-controlled `<select>` setter), so it works headlessly with NO server change and NO bespoke per-field driver. **⚠️ DO NOT re-implement a divergent `amazon_apply.py` in the skill root** — a hand-rolled per-field walker reproduces every gap atsform already solved and silently lags the committed one. If a field technique is missing, extend `atsform` (or `scripts/amazon_apply.py`'s `ANSWERS` map), never fork.

The `ANSWERS` map encodes Jane's responses; unmapped Yes/No questions default to Yes for "do you have experience…" (qualifying) and No otherwise. Key entries:
- `citizenship` → `United Kingdom`; `salary expectation` → `£50,000`.
- `previously applied/employed by amazon` / `non-competition agreement` / `need … sponsorship` → `No`.
- **Government-employee question → `No, I was NEVER a government employee.`** Jane was a contractor/product designer on NHS work, NOT a direct civil servant. Never answer FORMER (inaccurate + spawns a needless compliance cascade). `scripts/amazon_apply.py` defaults to NEVER and force-corrects any stale FORMER on every fill.
- `sanctioned countries` / `reside in` / `permanent resident in any other` → `No`.

One role takes 3–5 min (heavy Job-specific screening with 11 comboboxes is slow); run in the **background** for roles with heavy screening. The form **auto-saves** — a timed-out run resumes from saved state on re-run; amazon.jobs also redirects an already-done posting to its existing received app (`summary?result=duplicate`), so re-running is safe.

## "on/on toggle" gap — SOLVED

Amazon's custom radios ALL share `value="on"`; they must be matched by **option TEXT**, never by value. `atsform.rclick(option_text)` scopes to the question container and clicks the label/input by visible text, so the Work Eligibility "on/on" toggle radiogroup that blocked earlier bespoke drivers now resolves. Plain `el.value=` on a React `<select>`/radio is also silently ignored — `atsform.answer()` dispatches the prototype setter + `input`/`change` events, which is why the committed driver advances where hand-rolled `.value=` assignments stall. **If a step still won't advance, it is a genuine validation gap (e.g. a required field atsform didn't map), not the old toggle bug — inspect `_unanswered_questions()` and extend `ANSWERS`, don't re-fork.**

Heavy Job-specific screening (UX Researcher had 8 required radiogroups + 7 selects + portfolio) is slow but works; budget background time.

## Pitfalls

- **Use `scripts/amazon_apply.py`, not a rebuilt root-level `amazon_apply.py`.** The root one is a divergent re-implementation — retired.
- **Don't grep env for an amazon.jobs credential** — there isn't one; the operator logs in via the browser. The account is the unblock, not a CSV row.
- **Adzuna "Apply" ≠ amazon.jobs.** Adzuna's apply is a walled redirect loop; only WTTJ/Dots `Apply` (which open a new tab to the real ATS) reach amazon.jobs.
- **Form auto-saves** — a timed-out run resumes; don't assume a re-run re-applies.
- **On-profile only.** Sourced amazon.jobs roles that are off-profile for Jane (e.g. `10472108` Music Licensing Manager) must be SKIPPED, never applied to pad the count.
