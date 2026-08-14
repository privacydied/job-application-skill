#!/usr/bin/env python3
"""
js_health.py — does PAGE JavaScript actually execute in the camofox browser?

Why this exists (2026-08-14). Every JS-driven ATS form fails identically when page scripts
don't run, and each failure LOOKS like a different, board-specific structural wall:

  Greenhouse  "react-select renders zero options headless"
  Ashby       "fields won't commit"
  WTTJ        "Send enabled but fields won't bind"
  Lumesse     "Continue click doesn't advance via synthetic events"
  <any SPA>   "form filled, submit bounces This field is required"

They are one bug wearing eight costumes. Sessions have been spent writing per-board driver
workarounds for a browser that was never running the page's code. This check makes that
condition observable in ONE call, so it gets reported as infrastructure instead of being
laundered into eight `Blocked` rows and a "the agent cannot apply" conclusion.

Usage:
  js_health.py            # verdict + exit code
  js_health.py --json     # machine-readable

Exit codes:  0 = page JS executes (drive normally)
             1 = page JS does NOT execute — INFRA FAULT, do not log widget/driver walls
             2 = could not run the check (backend down, tab failure)
"""
import argparse
import json
import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_here)
sys.path.insert(0, os.path.join(_ROOT, "sites", "_common", "scripts"))

# A page whose own scripts set a known global, so we test real page execution rather than
# only our own injected script (an injected-script-only test can't distinguish "JS is off"
# from "this evaluate runs in an isolated world").
PROBE_URL = "https://job-boards.greenhouse.io/canonical/jobs/7043028"

_PROBE_JS = r"""(() => {
  // 1) did the PAGE's own inline script run? (Greenhouse sets window.ENV)
  const pageGlobal = typeof window.ENV !== 'undefined';
  // 2) did the PAGE's external scripts run? (reCAPTCHA / gapi / Dropbox dropins)
  const extGlobal = ['grecaptcha','gapi','google','Dropbox'].some(k => typeof window[k] !== 'undefined');
  // 3) does a freshly-injected inline script execute?
  let injected = false;
  try {
    const s = document.createElement('script');
    s.textContent = 'window.__js_health = 1;';
    document.body.appendChild(s);
    injected = window.__js_health === 1;
    s.remove();
  } catch (e) { injected = false; }
  return {pageGlobal, extGlobal, injected,
          moduleTags: document.querySelectorAll('script[type=module]').length,
          scripts: document.querySelectorAll('script').length};
})()"""


def check(url=PROBE_URL, keep_tab=False):
    import cfx
    tab = cfx.open_tab(url, session_key="js-health")
    cfx.set_tab(tab)
    try:
        r = cfx.evaluate(_PROBE_JS, timeout=45) or {}
    finally:
        if not keep_tab:
            try:
                cfx.delete("/tabs/" + tab, {"userId": cfx._uid()})
            except Exception:
                pass
    r["js_ok"] = bool(r.get("pageGlobal") or r.get("extGlobal") or r.get("injected"))
    r["url"] = url
    return r


def main(argv=None):
    ap = argparse.ArgumentParser(description="Check that page JavaScript executes in camofox.")
    ap.add_argument("--url", default=PROBE_URL)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--keep-tab", action="store_true")
    a = ap.parse_args(argv)

    try:
        r = check(a.url, keep_tab=a.keep_tab)
    except Exception as e:  # backend down / tab failure — distinct from a JS verdict
        if a.json:
            print(json.dumps({"error": str(e)[:200], "js_ok": None}))
        else:
            print(f"js_health: CANNOT CHECK — {str(e)[:200]}")
        return 2

    if a.json:
        print(json.dumps(r))
    elif r["js_ok"]:
        print("js_health: OK — page JavaScript executes. Widget/driver diagnoses are meaningful.")
    else:
        print("js_health: ⛔ PAGE JAVASCRIPT DOES NOT EXECUTE — INFRASTRUCTURE FAULT.")
        print(f"  page inline global (window.ENV) : {r.get('pageGlobal')}")
        print(f"  external script globals         : {r.get('extGlobal')}")
        print(f"  freshly-injected inline script  : {r.get('injected')}")
        print(f"  <script type=module> in DOM     : {r.get('moduleTags')}")
        print("  → Every JS-driven form will fail and LOOK like a per-board structural wall.")
        print("  → Do NOT log react-select/combobox/'fields won't commit' Blocked rows from")
        print("    this state, and do NOT write per-board driver workarounds for it.")
        print("  → Fix the browser first: references/greenhouse-remix-bundle-stripped-not-reactselect.md")
    return 0 if r["js_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
