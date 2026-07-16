#!/usr/bin/env python3
"""
pick.py — select an option in a WTTJ react-select dropdown, safely.

WTTJ's Application Questions form uses react-select components, not native
<select> elements — they render no interactable ref for the option list in the
camofox accessibility snapshot. This opens the dropdown by CSS selector, waits
for the option listbox to mount, clicks the intended option, and VERIFIES the
control now shows it.

Usage:
    CFX_KEY=... CFX_TAB=... python3 pick.py <select-index> <option-text>

<select-index> is the numeric suffix N in the DOM id `react-select-N-input`
(run opts.py first to confirm the index and read exact option text).

Why this is safer than the old version:
  * **Exact match preferred.** An exact (case-insensitive) option match wins.
    Only if there's no exact match does it fall back to substring — and if the
    substring matches MORE THAN ONE option it refuses to guess and reports the
    ambiguity (the old naive `.includes()` would silently click the first, e.g.
    picking "United States" for "United States Minor Outlying Islands", or the
    wrong salary/notice band). Exit code is non-zero on MISS/AMBIGUOUS so an
    autonomous caller notices.
  * **Self-healing open state.** Presses Escape first (clears a stale open
    dropdown that would block options), and polls for the option list instead
    of a fixed sleep.
  * **Verified.** After clicking, it reads the control's displayed value back
    and confirms the choice actually registered (react-select clicks can no-op).
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "_common", "scripts"))
import cfx  # noqa: E402
from opts import list_options  # reuse the same Escape-first + poll opener  # noqa: E402


def choose(options, want):
    """Return (chosen_text, reason). chosen_text is None on MISS/AMBIGUOUS."""
    wl = want.strip().casefold()
    exact = [o for o in options if o.casefold() == wl]
    if exact:
        return exact[0], "exact"
    subs = [o for o in options if wl in o.casefold()]
    if len(subs) == 1:
        return subs[0], "substring"
    if len(subs) == 0:
        return None, "MISS"
    return None, "AMBIGUOUS:" + json.dumps(subs, ensure_ascii=False)


def click_option(idx, chosen):
    expr = f"""
    (() => {{
      const scoped = [...document.querySelectorAll('[id^="react-select-{idx}-option"]')];
      const els = scoped.length ? scoped : [...document.querySelectorAll('[class*=option]')];
      const want = {json.dumps(chosen)};
      const m = els.find(o => o.textContent.trim() === want)
             || els.find(o => o.textContent.trim().includes(want));
      if (!m) return 'MISS';
      m.click();
      return 'CLICKED';
    }})()
    """
    return cfx.evaluate(expr)


def control_value(idx):
    expr = f"""
    (() => {{
      const inp = document.getElementById('react-select-{idx}-input');
      const ctl = inp && inp.closest('[class*=control]');
      return ctl ? ctl.textContent.trim() : '';
    }})()
    """
    return cfx.evaluate(expr) or ""


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    idx, want = sys.argv[1], sys.argv[2]

    try:
        options = list_options(idx)  # Escape-first, open, poll for options
        if not options:
            print(f"MISS: no options mounted for react-select-{idx} (wrong index?)")
            sys.exit(1)

        chosen, reason = choose(options, want)
        if chosen is None:
            print(f"{reason} for {want!r}. Options were: "
                  f"{json.dumps(options, ensure_ascii=False)}")
            cfx.press("Escape")
            sys.exit(1)

        clicked = click_option(idx, chosen)
        if clicked != "CLICKED":
            print(f"FAIL: option {chosen!r} vanished before click ({clicked}).")
            cfx.press("Escape")
            sys.exit(1)

        val = control_value(idx)
        ok = chosen.casefold() in val.casefold()
        print(f"{'OK' if ok else 'UNVERIFIED'} ({reason}): picked {chosen!r}; "
              f"control now shows {val!r}")
        sys.exit(0 if ok else 3)
    except cfx.CfxError as e:
        print(f"ERROR: {e}")
        sys.exit(2)


if __name__ == "__main__":
    main()
