#!/usr/bin/env python3
"""
probe_widget.py — self-diagnosing widget probe: turn a "stump" into a recorded capability.

Given a field LABEL (a substring of its visible label) or a CSS/#id selector, on the live
CFX_TAB it:
  1. dumps the widget's DOM descriptor (tag / role / aria wiring / classes / current value),
  2. runs the interaction LADDER one rung at a time and reports WHICH strategy opened it and
     the options it exposed, then
  3. appends a one-line capability record to references/scratch-probes-and-capability-index.md
     so the next encounter with that variant is instant — never rediscovered.

DOCTRINE (SKILL.md · references/camofox-form-filling-pitfalls.md): a widget that won't drive
is a CAPABILITY GAP this script closes — NEVER a "structural limit" or a `Blocked`. Only an
eligibility question with no truthful answer is a legitimate widget stop. Run this BEFORE you
ever consider a combobox undrivable.

READ-ONLY by default: it opens the widget to read options, then closes it; it does NOT commit
a selection. Pass `--pick "<option>"` to also select (a live end-to-end confirm).

Usage:
  CFX_KEY=... CFX_TAB=... python3 scripts/probe_widget.py "<label|css/#id>" [--pick "<option>"]
"""
import json
import os
import sys
import time

_here = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_here)
sys.path.insert(0, os.path.join(_ROOT, "sites", "_common", "scripts"))
import cfx        # noqa: E402
import atsform    # noqa: E402  — reuse the ONE engine's templates + helpers

CAP_INDEX = os.path.join(_ROOT, "references", "scratch-probes-and-capability-index.md")

_DESCRIBE = r"""
(() => {
  const i = document.querySelector('[data-ats-target]') || document.querySelector('[data-ats-native]');
  if (!i) return JSON.stringify({found:false});
  const ctrl = i.closest && i.closest('[class*="control"]');
  const cur = ctrl ? [...ctrl.querySelectorAll('[class*="singleValue"],[class*="multi-value__label"],[class*="multiValueLabel"]')].map(v=>(v.textContent||'').trim()) : [];
  return JSON.stringify({
    found:true, tag:i.tagName, id:i.id||'', role:i.getAttribute('role')||'',
    ariaAutocomplete:i.getAttribute('aria-autocomplete')||'', ariaControls:i.getAttribute('aria-controls'),
    inputClass:(i.className||'').toString().slice(0,50),
    controlClass:ctrl?(ctrl.className||'').toString().slice(0,60):null,
    current:cur, url:location.host,
  });
})()
""".strip()

_CLOSE = "(()=>{document.body.dispatchEvent(new MouseEvent('mousedown',{bubbles:true}));" \
         "if(document.activeElement&&document.activeElement.blur)document.activeElement.blur();})()"


def _resolve(target):
    js = atsform._COMBO_RESOLVE.replace("__TARGET__", atsform._js(target)).replace(
        "__FIND__", atsform._FIND_CONTROL)
    try:
        return json.loads(cfx.evaluate(js))
    except Exception as e:  # noqa: BLE001
        return {"kind": "none", "_error": str(e)}


def _try_rung(name, run):
    """Run one open rung in isolation and return (name, n_options, sample). Closes any menu
    first so each rung's result is attributable to that rung alone."""
    cfx.evaluate(_CLOSE)
    time.sleep(0.3)
    try:
        run()
    except Exception as e:  # noqa: BLE001
        return {"rung": name, "opened": False, "n": 0, "sample": [], "err": str(e)[:50]}
    cfx.poll(atsform._COMBO_READ_OPTS,
             predicate=lambda r: isinstance(r, str) and r not in ("", "[]"), timeout=2.5)
    opts = atsform._combo_options()
    return {"rung": name, "opened": bool(opts), "n": len(opts), "sample": opts[:8]}


def _record(target, desc, winner, ladder):
    tried = ", ".join("{}={}".format(r["rung"], "ok" if r["opened"] else "no") for r in ladder)
    line = (f"- **combobox** `{target}` @ `{desc.get('url','?')}` "
            f"(role={desc.get('role','')}, aria-controls={desc.get('ariaControls')}, "
            f"ctrl={desc.get('controlClass','')}) → opened via **{winner or 'NONE'}**; "
            f"tried {tried} [{time.strftime('%Y-%m-%d')}]\n")
    try:
        with open(CAP_INDEX, "a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass
    return line


def main():
    argv = sys.argv[1:]
    if not argv:
        print(__doc__)
        return 1
    target = argv[0]
    pick = argv[argv.index("--pick") + 1] if "--pick" in argv and argv.index("--pick") + 1 < len(argv) else None

    info = _resolve(target)
    if info.get("kind") == "none":
        print(f"NO WIDGET resolved for {target!r} "
              f"({info.get('_error','not found on this page')}). "
              f"Check the label substring / that the form is loaded.")
        return 2
    desc = json.loads(cfx.evaluate(_DESCRIBE))
    print(f"== widget: {target!r} ==")
    print(f"  kind={info['kind']}  " + json.dumps({k: desc.get(k) for k in
          ("tag", "role", "ariaAutocomplete", "ariaControls", "controlClass", "current")}))

    if info["kind"] == "native":
        print("  native <select> — driven by prototype value setter (no ladder needed).")
        _record(target, desc, "native-select", [])
        return 0

    # run the ladder rungs in isolation to find (and record) the winning strategy
    ladder = [
        _try_rung("pointer-mousedown", lambda: cfx.evaluate(atsform._COMBO_POINTER_OPEN)),
        _try_rung("arrowdown", lambda: (atsform._combo_focus(), cfx.press("ArrowDown"))),
        _try_rung("trusted-click", lambda: cfx.click_selector('[data-ats-target]')),
    ]
    winner = next((r["rung"] for r in ladder if r["opened"]), None)
    for r in ladder:
        print(f"  {r['rung']:<18} {'OPENED' if r['opened'] else 'no menu':<8} "
              f"n={r['n']:<3} {r.get('err','') or r['sample']}")
    print(f"  → winning strategy: {winner or 'NONE (type-to-filter may be needed — combobox_pick tries it)'}")
    _record(target, desc, winner, ladder)
    print(f"  recorded → {os.path.relpath(CAP_INDEX, _ROOT)}")

    if pick is not None:
        cfx.evaluate(_CLOSE); time.sleep(0.3)
        print(f"\n== --pick {pick!r} (live commit) ==")
        rc = atsform.combobox_pick(target, pick, multi=bool(info.get("isMulti")))
        print(f"  combobox_pick rc={rc}")
        return rc
    cfx.evaluate(_CLOSE)
    return 0 if winner else 3


if __name__ == "__main__":
    sys.exit(main())
