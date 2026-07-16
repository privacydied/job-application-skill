# Ashby — `check` false-negative on toggles/radios; real state is the `_act` class

Captured 2026-07-14 (loveholidays Product Designer, Ashby ATS).

## Symptom
`python3 sites/ashbyhq/scripts/ashby.py check` lists a Yes/No toggle or a radio
group under `empty`, even though it is correctly selected. Tells the agent the
form is incomplete when it isn't.

## Root cause
Ashby reflects a Yes/No selection via a CSS class on the *chosen button*
(`_act` in the class string, e.g. `_container_pjyt6_1 _option_1svni_32 _act`), not
reliably via the backing hidden checkbox's `.checked` property. `check` reads the
checkbox and so misses the selection. Same class-of-bug for radio groups.

## Verify the REAL state before submit (do NOT trust `check` for these)
```js
// Yes/No toggle: selected button has class substring `_act`
for (const c of document.querySelectorAll('div')) {
  const bs=[...c.querySelectorAll('button')].filter(b=>/^(Yes|No)$/i.test((b.innerText||'').trim()));
  if (bs.length!==2) continue;
  const q=c.innerText.replace(/Yes|No/g,'').replace(/\s+/g,' ').trim().toLowerCase();
  if (/visa|office|trailblaze|london/i.test(q)) {
    const sel=[...c.querySelectorAll('button')].find(b=>/_act/.test(b.className));
    console.log(q.slice(0,25)+' => '+(sel?sel.innerText.trim():'NONE SELECTED'));
  }
}
// Radio groups (age/gender/transgender): options are <input type=radio> whose
// CONTAINER DIV text = the option label (NOT a <fieldset>/<legend>).
// Every matched radio has value="on" (identical) — verify by .checked, not value.
// Click the radio whose closest container text starts with the option text.
```
Radio option labels seen: age "Under 30 / 30-39 / 40-49 / 50-59 / 60 or older / I
prefer not to answer"; gender "Man / Woman / Non-Binary / Another Gender Identity";
transgender "Yes / No". Because `set-radio` matches by fieldset/legend it returns
NOT_FOUND on Ashby — click by container text instead.

## Working order (so autofill doesn't wipe the toggles)
upload-cv FIRST → fill all text/textarea → set-toggle (Yes/No) → click radios by
container text → re-read the `_act`/`.checked` state above → only THEN submit.
The CV-autofill re-render can reset toggles set *before* the upload.
