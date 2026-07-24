# Ashby custom-radio fix (2026-07-23, verified live)

## Symptom
`atsform.set_radio` (and `ashby.set_radio`) click the native `<input type=radio>` via
`r.click()`. On Ashby's custom radios this is a NO-OP: `r.checked` stays `false`, AND even
`r.checked=true` + a plain `.click()` does NOT update React state, so the submit-side
validator still reports "Missing entry for required field: <question>".

All Ashby radios on a form share ONE `name` attribute (they are NOT grouped by name), so
the per-group logic in `atsform.set_radio` collapses and the visible option labels must be
matched by exact text within the question block.

## Fix (verified to clear the validator + submit)
Locate the option `<label>` by EXACT text within the question block, set the bound
`<input>`'s `checked` via the prototype setter (so React's onChange fires), then dispatch
click/input/change:

```js
function setNativeValue(el, value){
  var proto=Object.getPrototypeOf(el);
  var d=Object.getOwnPropertyDescriptor(proto,'checked');
  if(d&&d.set){ d.set.call(el,value); } else { el.checked=value; }
}
// for each question substring q, find its label, then the option label whose
// innerText.trim().toLowerCase() === opt (exact match — avoids grabbing a "Yes"
// from a different group), get r=label.for input, then:
setNativeValue(r,true);
r.dispatchEvent(new MouseEvent('click',{bubbles:true}));
r.dispatchEvent(new Event('input',{bubbles:true}));
r.dispatchEvent(new Event('change',{bubbles:true}));
```

✅ Folded into `ashby.set_radio` (commit 9bc449f) — the label-anchored native-setter is now
the canonical Ashby radio path (`ashby.apply()`'s `radios` config commits); it defers to
`atsform.set_radio` for standard/Workday radios. The former `apply_specs/drive_ashby.py`
vehicle (`set_radio_native`) has been removed.

## Also: Ashby location combobox (`_systemfield_location`)
Free-text commit via native-setter on `input[aria-autocomplete=list][placeholder="Start typing..."]`
works to set the value, BUT on Paddle the submit validator rejected it ("Missing entry for
required field: Where are you located?") because the async suggestion list is dead headless
and free text isn't accepted by the structured-location validator. This is the documented
Ashby location residual limit → log `Blocked`, not a 3rd attempt.
