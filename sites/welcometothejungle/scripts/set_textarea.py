#!/usr/bin/env python3
"""
set_textarea.py — cleanly set a WTTJ textarea/input value (e.g. Cover Letter).

The plain camofox `type` action can double up existing text instead of
replacing it on WTTJ's controlled React inputs (observed on the Xelix cover
letter field: typing appended to a previous fill, producing a duplicated
paragraph). This bypasses that: it clears the field, sets the value via the
native HTMLTextAreaElement/HTMLInputElement value setter, and dispatches
input/change/blur so React's controlled state updates AND any on-blur validation
(which enables the Save/Send button) fires.

Usage:
    CFX_KEY=... CFX_TAB=... python3 set_textarea.py <element-id> <text-file-or-->

Pass a path to a UTF-8 text file, or `-` to read text from stdin. Prints
PASS/FAIL by comparing the resulting field length to the source length and exits
non-zero on any mismatch or a missing element — so an autonomous caller can tell
the set didn't take (the old version only printed both numbers for a human to
eyeball). Reads the source as UTF-8 explicitly so curly quotes / accented names
/ emoji in a cover letter aren't mangled by the host locale's default encoding.

Finding <element-id>: dump the textareas first, e.g.:
    cfx.sh eval "JSON.stringify([...document.querySelectorAll('textarea')].map(e=>({id:e.id,len:e.value.length})))"
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "_common", "scripts"))
import cfx  # noqa: E402


def set_value(el_id: str, text: str):
    expr = f"""
    (() => {{
      const el = document.getElementById({json.dumps(el_id)});
      if (!el) return -1;
      const proto = el.tagName === 'TEXTAREA'
        ? window.HTMLTextAreaElement.prototype
        : window.HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
      el.focus();
      setter.call(el, '');                                   // clear first
      el.dispatchEvent(new Event('input', {{bubbles: true}}));
      setter.call(el, {json.dumps(text)});                   // then set
      el.dispatchEvent(new Event('input', {{bubbles: true}}));
      el.dispatchEvent(new Event('change', {{bubbles: true}}));
      el.dispatchEvent(new Event('blur', {{bubbles: true}}));
      return el.value.length;
    }})()
    """
    return cfx.evaluate(expr)


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    el_id, src = sys.argv[1], sys.argv[2]
    if src == "-":
        text = sys.stdin.read()
    else:
        with open(src, encoding="utf-8") as f:
            text = f.read()

    try:
        result = set_value(el_id, text)
    except cfx.CfxError as e:
        print(f"ERROR: {e}")
        sys.exit(2)

    if result == -1:
        print(f"NOT_FOUND: no element with id {el_id!r} on the page.")
        sys.exit(1)

    got = int(result)
    # HTML <textarea>/<input> .value normalizes CRLF/CR line endings to LF, so a
    # source authored with Windows/mixed line endings over-counts vs the field and
    # would spuriously FAIL a clean set (and exit non-zero, tripping the caller).
    # Measure against the same normalization the browser applies. LF-only text
    # (the common case) is unchanged.
    want = len(text.replace("\r\n", "\n").replace("\r", "\n"))
    if got == want:
        print(f"PASS: set {got} chars into #{el_id}.")
        sys.exit(0)
    print(f"FAIL: #{el_id} ended up {got} chars but source is {want} "
          f"(controlled-state set didn't take cleanly — re-run or inspect).")
    sys.exit(1)


if __name__ == "__main__":
    main()
