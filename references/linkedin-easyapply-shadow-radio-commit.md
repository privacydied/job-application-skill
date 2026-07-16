# LinkedIn Easy Apply — custom radio/checkbox widgets (shadow DOM) commit failures

## Symptom
`easyapply.py radio "<question>" "<option>"` returns `NOT_FOUND`, or worse selects the
**WRONG** option — e.g. `radio "gender identity" "Man"` selected **Woman** because
"man" is a substring of "woman". The underlying DOM shows `checked=true` after a JS
`.click()`, yet LinkedIn's **server validation** still rejects with
`BLOCKED_UNANSWERED_REQUIRED` / "Please enter a valid answer".

Root cause: LinkedIn renders Easy Apply radios/checkboxes as **custom widgets** — the real
`<input type=radio|checkbox>` is invisible and wrapped in
`<div data-test-text-selectable-option="<idx>">`. React's `onChange` is bound to the
**wrapper div**, not the input. So:
- `input.click()` / `dispatchEvent` on the input flips `checked` in the DOM but does NOT
  fire React's handler → not committed.
- `easyapply.radio` only matches questions whose group has a `<fieldset><legend>`/`<label>`;
  div-wrapped groups (gender, ethnicity, an "online portfolio" Yes/No) return `NOT_FOUND`.
- Substring option match is dangerous: "Man" ⊂ "Woman"; "Mixed" is a **checkbox**
  (multi-select "Select all that apply"), not a radio.

## Diagnosis — read the real DOM (it's in a shadow root)
`document.querySelector('[role=dialog]')` is `null` because the modal lives in a shadow
root. Resolve it:
```js
const host=[...document.querySelectorAll('*')].find(e=>e.shadowRoot && e.shadowRoot.querySelector('[role=dialog]'));
const SR=host?host.shadowRoot:document;
const DLG=[...SR.querySelectorAll('[role=dialog]')].pop();
for(const rb of DLG.querySelectorAll('input[type=radio]')){
  const fs=rb.closest('fieldset');
  const q=(fs?(fs.querySelector('legend,label')||{}).innerText:rb.name)||'';
  if(q.toLowerCase().includes(Q) && rb.value===VAL){ /* ... */ }
}
```

## Fix (works for the committed ones; the residual wall → Blocked)
Click the **wrapper div**, not the input, with a full trusted MouseEvent sequence:
```js
const wraps=[...DLG.querySelectorAll('div[data-test-text-selectable-option]')];
const w=wraps.find(o=>(o.textContent||'').replace(/\s+/g,' ').trim()===EXACT_TEXT); // "Man" not "Woman"
if(!w) return 'NF';
const inp=w.querySelector('input');
['pointerdown','mousedown','pointerup','mouseup','click'].forEach(ev=>
  w.dispatchEvent(new MouseEvent(ev,{bubbles:true,cancelable:true,view:window})));
if(inp) inp.dispatchEvent(new MouseEvent('click',{bubbles:true}));
```
- Match **exact option text** (`===`), never a substring, to avoid Man/Woman.
- **Ethnicity "Select all that apply"** is a `checkbox` (`inp.type==='checkbox'`,
  value `"on"`) — click its wrapper the same way; `easyapply.radio` will NOT handle it.
- The cfx `/click` REST endpoint (`POST /tabs/{id}/click` with `selector`) uses Playwright
  which pierces open shadow DOM, but `:has-text` / `>>` chaining **timed out in-session** —
  the JS MouseEvent-on-wrapper dispatch was the reliable path.

## Hard wall (log Blocked, do not loop)
Some custom widgets still reject after a correct wrapper-click with "Please enter a valid
answer" (observed on Computappoint's "online portfolio" Yes/No — every method flipped
`checked=true` but validation stayed red). This is a LinkedIn React commit bug on that
specific widget, not a transient flake. Per the per-posting time cap (<=2 attempts / ~10 min),
log `Blocked` with the symptom and move on — do NOT keep re-clicking. Prefer other Easy
Apply roles.

## EEO answers for Jane (pass to the widgets above)
gender = **Man**, ethnicity = **Mixed** (Mixed/Multiple ethnic group — the "Mixed" option in
LinkedIn's list), disability = **Prefer not to disclose**, right-to-work = **Yes**,
sponsorship = **No**. Set these via the wrapper-click technique, never via a substring
`radio` that can collide.
