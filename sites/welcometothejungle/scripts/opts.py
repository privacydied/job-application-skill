#!/usr/bin/env python3
"""
opts.py — list the options of a WTTJ react-select dropdown without selecting one.

Use this before pick.py to confirm you have the right select-index and to read
the exact option text to match on (e.g. currency codes, notice-period bands).

Usage:
    CFX_KEY=... CFX_TAB=... python3 opts.py <select-index>

<select-index> is the numeric suffix N in the DOM id `react-select-N-input`.

Robustness (vs the old fixed-sleep version): presses Escape FIRST to clear any
stale open dropdown (a still-open previous listbox used to make this return an
empty list — that's now self-healed, not a manual step), opens the select, then
POLLS for the option list to mount instead of a fragile fixed 0.8s wait, and
presses Escape afterward so the dropdown is left CLOSED and won't block the next
field. Options are scoped to this select's own ids where possible so a different
open select can't leak its options into the result.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "_common", "scripts"))
import cfx  # noqa: E402


def options_expr(idx: str) -> str:
    # Prefer this select's own option ids (react-select-<idx>-option-*); fall
    # back to the generic class match only if that yields nothing.
    return f"""
    (() => {{
      const scoped = [...document.querySelectorAll('[id^="react-select-{idx}-option"]')];
      const els = scoped.length ? scoped : [...document.querySelectorAll('[class*=option]')];
      return els.map(o => o.textContent.trim());
    }})()
    """


def list_options(idx: str):
    cfx.press("Escape")            # clear any stale open dropdown first
    cfx.click_selector(f"#react-select-{idx}-input")
    opts = cfx.poll(
        options_expr(idx),
        predicate=lambda r: isinstance(r, list) and len(r) > 0,
        timeout=3.0,
    )
    return opts if isinstance(opts, list) else []


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    idx = sys.argv[1]
    try:
        opts = list_options(idx)
    except cfx.CfxError as e:
        print(f"ERROR: {e}")
        sys.exit(2)
    finally:
        try:
            cfx.press("Escape")    # leave the dropdown closed for the next field
        except cfx.CfxError:
            pass
    print(json.dumps(opts, ensure_ascii=False))
    if not opts:
        print("(empty — no options mounted; wrong select-index, or the field "
              "isn't a react-select. Re-check the index with a textareas/inputs dump.)")
        sys.exit(1)


if __name__ == "__main__":
    main()
