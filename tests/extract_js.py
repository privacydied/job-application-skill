#!/usr/bin/env python3
"""extract_js.py — dump atsform's injected JavaScript as JSON for tests/dom_checks.js.

The JS lives in two places: module-level constants (`_COMBO_RESOLVE`, `_UNANSWERED`, …) and
f-strings built at CALL time inside `set_radio` / `set_checkbox`. The second kind can only be
obtained by calling the function with `cfx.evaluate` stubbed out, which is what this does — so
dom_checks.js tests the REAL string that would be sent to the browser, not a copy that can
drift from it.

USAGE:
  python3 tests/extract_js.py > /tmp/atsform-js.json
  node tests/dom_checks.js /tmp/atsform-js.json
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "sites", "_common", "scripts"))


def main():
    import atsform

    captured = []
    orig = atsform.cfx.evaluate
    atsform.cfx.evaluate = lambda js, *a, **k: (captured.append(js), "NOT_FOUND")[1]
    try:
        # stdout is the JSON payload, so keep the drivers' own chatter off it
        devnull = open(os.devnull, "w")
        real_stdout, sys.stdout = sys.stdout, devnull
        try:
            atsform.set_checkbox("Man", quiet_notfound=True)
        finally:
            sys.stdout = real_stdout
            devnull.close()
    finally:
        atsform.cfx.evaluate = orig

    out = {
        "COMBO_RESOLVE": atsform._COMBO_RESOLVE,
        "COMBO_CLICK": atsform._COMBO_CLICK,
        "COMBO_FREETEXT_COMMIT": atsform._COMBO_FREETEXT_COMMIT,
        "UNANSWERED": atsform._UNANSWERED,
        "CHECKBOX_MAN": captured[0] if captured else "",
    }
    json.dump(out, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
