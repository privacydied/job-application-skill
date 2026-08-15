#!/usr/bin/env python3
"""diagnose_gh_block.py — why did this Greenhouse submit bounce?

WHY (2026-08-15): when `gh_apply.py` prints

    BLOCKED — validation errors:
      - This field is required.
    CODE_MISSING — no verification code fetched

neither line names the field. Worse, the second line is usually a RED HERRING: Greenhouse
only emails the security code for a submit that PASSED validation, so a validation bounce
always drags `CODE_MISSING` along with it and the failure reads like a mailbox problem when
it is really one unfilled input. That misreading cost a real application (Capital on Tap)
and was hand-diagnosed four separate times in one run with a throwaway JS snippet.

This is that snippet, made canonical. It reads the CURRENT tab — run it straight after a
failed gh_apply, with no navigation, so the part-filled form is still on screen.

USAGE (needs live CFX_TAB; run from the skill root):
    source .jobenv.run && python3 scripts/diagnose_gh_block.py

OUTPUT
    EMPTY_REQUIRED  — required fields with no value: add each to the config's fill/combo.
    FIELD_ERRORS    — fields showing an inline validation message.
    CODE_GATE       — True once the 8-char security-code input is present, which means
                      validation PASSED and the only thing left is the emailed code
                      (fetch it with scripts/fetch_verification_code.py).

A field is "empty" only if it has no value AND no react-select single-value chip AND no
uploaded-filename chip — checking `input.value` alone reports every bound react-select and
every successful upload as empty (Greenhouse swaps the file input out for a chip).
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "sites", "_common", "scripts"))
sys.path.insert(0, "sites/_common/scripts")
import cfx  # noqa: E402

JS = r"""
(() => {
  const out = {empty: [], errors: [], code_gate: false, url: location.href};
  out.code_gate = !!document.querySelector('[id^=security-input]');
  const seen = new Set();
  document.querySelectorAll('label').forEach(l => {
    const txt = (l.textContent || '').replace(/\s+/g, ' ').trim();
    if (!/\*/.test(txt)) return;                       // required is marked with *
    const w = l.closest('.field-wrapper,[class*=field]');
    if (!w) return;
    const c = w.querySelector('input,textarea,select');
    if (!c || c.type === 'hidden') return;
    const key = txt.slice(0, 80);
    if (seen.has(key)) return;                          // nested wrappers repeat the label
    seen.add(key);
    // A value can live in the control, in a react-select chip, or in an upload chip.
    const chip = w.querySelector('[class*=singleValue],[class*=single-value],[class*=multiValue]');
    const file = w.querySelector('[class*=filename]');
    const val = (c.value || '').trim() || (chip ? chip.textContent.trim() : '')
              || (file ? file.textContent.trim() : '');
    const err = w.querySelector('[class*=error],[role=alert]');
    const errTxt = err ? (err.innerText || '').replace(/\s+/g, ' ').trim() : '';
    if (errTxt && /required|invalid|must|select/i.test(errTxt))
      out.errors.push({field: key, error: errTxt.slice(0, 70)});
    if (!val) out.empty.push({field: key, id: c.id || c.name || '', tag: c.tagName});
  });
  return JSON.stringify(out);
})()
"""


def main():
    try:
        res = json.loads(cfx.evaluate(JS) or "{}")
    except Exception as e:  # noqa: BLE001
        print(f"FAIL: could not read the tab ({e}). Is CFX_TAB live and on the form?",
              file=sys.stderr)
        return 2

    print(f"URL {res.get('url', '')[:100]}")
    print(f"CODE_GATE {res.get('code_gate')}")

    empty = res.get("empty", [])
    errors = res.get("errors", [])

    if errors:
        print("\nFIELD_ERRORS:")
        for e in errors:
            print(f"  {e['field'][:70]}\n      -> {e['error']}")

    if empty:
        print("\nEMPTY_REQUIRED — add each of these to the config:")
        for e in empty:
            where = "fill " if e["tag"] in ("TEXTAREA", "INPUT") else "combo"
            print(f"  [{where}] {e['field'][:78]}   (id={e['id'][:28]})")
    else:
        print("\nEMPTY_REQUIRED: none")

    if res.get("code_gate") and not empty and not errors:
        print("\n=> Validation PASSED. This is ONLY the emailed security code:\n"
              "   python3 scripts/fetch_verification_code.py   then type it and re-submit.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
