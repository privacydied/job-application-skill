#!/usr/bin/env python3
"""
canary.py — nightly end-to-end smoke test of the browser + fill path (feature-roadmap H.6).

WHY. A degraded camofox backend or a rotted selector doesn't announce itself — a live run
just starts burning passes misdiagnosing it (the whole CONTAMINATION class). A canary run
BEFORE a live run catches "the backend is blank-rendering" or "atsform's fill path is broken"
up front, and writes canary-status.json so the preflight / dashboard can read the last known
health without re-probing.

Checks (each best-effort; the worst determines the verdict):
  1. backend health fingerprint (cfx.health_fingerprint) — connected + eval works.
  2. render: cfx.goto a stable control URL and assert innerText>0 (the open-tab-nav trap).
  3. click path: cfx.engine_click_healthy — is the mouse-input path actually delivering.
  4. fill path (--full): inject a tiny labeled form into the loaded page and drive
     atsform.fill on it, asserting the typed value persists — exercises the real selector +
     fill primitive end-to-end (selector-rot canary).

verdict ∈ healthy | degraded | skipped(no CFX_KEY). Written to canary-status.json:
    {verdict, checked_at, checks:{health,render,click,fill}, details}

CRON (nightly, before the morning run; sources env + a tab like warm_queue):
  0 6 * * * cd /…/job-application && . ./.jobenv 2>/dev/null; \
            python3 scripts/canary.py --full >> canary.log 2>&1

Usage: canary.py [--full] [--url https://example.com]
"""
import json
import os
import sys
import time

_here = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_here)
sys.path.insert(0, os.path.join(_ROOT, "sites", "_common", "scripts"))
from fsutil import file_lock, atomic_write  # noqa: E402

STATUS = os.path.join(_ROOT, "canary-status.json")
CONTROL_URL = "https://example.com/"

# a tiny labeled form injected into the loaded page; atsform.fill targets the visible label.
_INJECT = """(function(){
  var d=document.createElement('div'); d.id='__canaryForm';
  d.innerHTML='<label for="__cf">Canary Field</label>'+
    '<input id="__cf" name="__cf" type="text" value="">';
  document.body.appendChild(d); return true;})()"""


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _write(status):
    try:
        with file_lock(STATUS):
            atomic_write(STATUS, lambda f: f.write(json.dumps(status, ensure_ascii=False, indent=2)))
    except OSError:
        pass


def main():
    argv = sys.argv[1:]
    full = "--full" in argv
    url = argv[argv.index("--url") + 1] if "--url" in argv else CONTROL_URL

    if not os.environ.get("CFX_KEY"):
        status = {"verdict": "skipped", "checked_at": _now(),
                  "checks": {}, "details": "no CFX_KEY in env (source .jobenv)"}
        _write(status)
        print(json.dumps(status)); return 0

    import cfx
    checks, details = {}, {}

    # 1) health fingerprint
    try:
        fp = cfx.health_fingerprint()
        checks["health"] = (fp.get("degraded") is not True)
        details["health"] = fp
    except Exception as e:  # noqa: BLE001
        checks["health"] = False
        details["health"] = str(e)

    # ensure a tab, then 2) render check
    try:
        cfx.set_tab(cfx.ensure_tab(persist=False))
        res = cfx.goto(url)
        checks["render"] = bool(res.get("ok"))
        details["render"] = res
    except Exception as e:  # noqa: BLE001
        checks["render"] = False
        details["render"] = str(e)

    # 3) click path
    try:
        checks["click"] = bool(cfx.engine_click_healthy())
    except Exception as e:  # noqa: BLE001
        checks["click"] = False
        details["click"] = str(e)

    # 4) fill path (--full): inject a labeled field, drive atsform.fill, assert it persisted.
    if full and checks.get("render"):
        try:
            import atsform
            cfx.evaluate(_INJECT)
            atsform.fill("Canary Field", "canary-ok")
            got = cfx.evaluate("(document.getElementById('__cf')||{}).value||''")
            checks["fill"] = (got == "canary-ok")
            details["fill"] = {"got": got}
            cfx.evaluate("(function(){var e=document.getElementById('__canaryForm');"
                         "if(e)e.remove();return true;})()")
        except Exception as e:  # noqa: BLE001
            checks["fill"] = False
            details["fill"] = str(e)

    core = [v for k, v in checks.items() if k in ("health", "render", "click")]
    fill_ok = checks.get("fill", True)  # only counts when --full ran
    verdict = "healthy" if (all(core) and fill_ok) else "degraded"
    status = {"verdict": verdict, "checked_at": _now(), "checks": checks, "details": details}
    _write(status)
    print(f"canary: {verdict}  checks={checks}")
    if verdict == "degraded":
        print("⚠️ backend/selector rot detected — do NOT trust terminal 'blocked/exhausted' "
              "verdicts from a live run until this is healthy (contamination rule). "
              "Wait ~90s idle + re-run, or cfx.py restart-engine.", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
