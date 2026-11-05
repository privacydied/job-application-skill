#!/usr/bin/env python3
"""turnstile.py — click a Cloudflare Turnstile checkbox via camofox CDP (no solver service).

Cloudflare Turnstile is a reCAPTCHA-v2-class checkbox challenge hosted in a
challenges.cloudflare.com iframe. Like recaptcha.py for Google, this is a
sanctioned in-browser auto-solve (references/captcha-policy.md, "Sanctioned
exception 3"): click the checkbox, wait for Cloudflare to accept it, report
PASS/FAIL. On FAIL (fingerprint distrust — the checkbox may never render —
timeout, or no iframe target) the caller falls through to the halt-and-message
procedure in that policy; this script never retries in a loop.

USAGE (from shell):
  CFX_KEY=... CFX_TAB=... python3 sites/_common/scripts/turnstile.py [sitekey]
      No sitekey: find first [data-sitekey] / challenges.cloudflare.com iframe.
      Prints: PASS | FAIL:<reason>
  Exit: 0 PASS · 1 FAIL · 2 error (not on a Turnstile page)

LIBRARY USE (import into a board driver):
  import turnstile
  if turnstile.present():
      print("Turnstile ->", turnstile.click())   # 'PASS' | 'FAIL:<reason>'
      # if FAIL, record cooldown and halt per policy
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, HERE)
import cfx  # noqa: E402


def _ev(expr, tries=4):
    for _ in range(tries):
        try:
            r = cfx.evaluate(expr)
            if r is not None:
                return r
        except cfx.CfxError:
            pass
        time.sleep(1)
    return None


def _wait(cond, timeout=20, interval=1.5):
    deadline = time.time() + timeout
    r = None
    while time.time() < deadline:
        r = cond()
        if r:
            return r
        time.sleep(interval)
    return r


def _sitekey():
    """Find the Turnstile sitekey: [data-sitekey], iframe ?k= param, or 0x… in HTML."""
    return _ev(r"""(function(){
      var d = document.querySelector('[data-sitekey]');
      if (d) return d.getAttribute('data-sitekey');
      var found = '';
      function walk(root, dep) {
        if (dep > 6 || !root || found) return;
        var e = root.querySelectorAll ? root.querySelectorAll('iframe') : [];
        for (var i = 0; i < e.length && !found; i++) {
          var s = (e[i].src || '') + '';
          var m = s.match(/[?&]k=([^&]+)/);
          if (m && /cloudflare|turnstile/i.test(s)) { found = m[1]; return; }
          var sk = e[i].getAttribute && e[i].getAttribute('data-sitekey');
          if (sk) { found = sk; return; }
        }
      }
      walk(document, 0);
      if (found) return found;
      return (document.documentElement.innerHTML.match(/\b0x[0-9A-Za-z_-]{20,}\b/) || [''])[0];
    })()""") or ""


def _iframe_src():
    """Return the src of the first challenges.cloudflare.com iframe, or ''."""
    return _ev("""(function(){
      var ifs = document.querySelectorAll('iframe');
      for (var i = 0; i < ifs.length; i++)
        if (/challenges\\.cloudflare\\.com|turnstile/i.test(ifs[i].src))
          return ifs[i].src;
      return '';
    })()""") or ""


def present():
    """True if a Turnstile challenge appears to be on the page."""
    return bool(_sitekey()) or bool(_iframe_src()) or _ev("""(function(){
      return document.querySelector('[name*=turnstile], [name*=cf-turnstile], [data-turnstile-sitekey]') !== null;
    })()""")


def _click_checkbox():
    """Find the Turnstile checkbox in the iframe and click it via CDP attach."""
    sk = _sitekey()
    src = _iframe_src()
    if not sk and not src:
        return "FAIL:no sitekey/iframe"

    # Find the iframe target
    import subprocess
    cfx_key = os.environ.get("CFX_KEY")
    cfx_tab = os.environ.get("CFX_TAB")
    if not cfx_key or not cfx_tab:
        return "FAIL:CFX_KEY/CFX_TAB not set"

    # Use the camofox REST API directly to get targets, attach, click
    import urllib.request
    base = os.environ.get("CFX_URL", "http://127.0.0.1:3333")

    def rest(method, path, body=None):
        url = f"{base}{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())

    # Find the Turnstile iframe target
    targets = rest("GET", "/targets")["targetInfos"]
    target_id = None
    for t in targets:
        if t["type"] == "iframe" and ("challenges.cloudflare.com" in t["url"] or "turnstile" in t["url"]):
            target_id = t["targetId"]
            break
    if not target_id:
        return "FAIL:no turnstile iframe target"

    # Attach to it
    sess = rest("POST", f"/targets/{target_id}/attach", {})
    session_id = sess["sessionId"]

    # Enable DOM + Runtime in that session and click the checkbox
    # Turnstile checkbox: .cf-turnstile iframe contains div#challenge-stage > div.cf-checkbox
    r = rest("POST", f"/sessions/{session_id}/Runtime.evaluate", {
        "expression": """
            (function(){
              // Try multiple known selectors for the Turnstile checkbox
              var b = document.querySelector('#checkbox, .cf-turnstile input[type=checkbox],
                                             .cf-turnstile .cf-checkbox,
                                             .cf-turnstile [class*=checkbox]');
              if (!b) {
                // Invisible/compact Turnstile has no visible checkbox — trigger via callback
                if (typeof window.turnstile !== 'undefined' && turnstile.reload) {
                  turnstile.reload('default');
                  return 'reloaded';
                }
                return 'no checkbox found';
              }
              b.click();
              return 'clicked';
            })()
        """
    })
    result = r.get("result", {}).get("value", r)
    return "PASS" if result == "clicked" else f"FAIL:{result}"


def _poll_for_pass(timeout=30):
    """After clicking, poll for the Turnstile to report success."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        # Check for the hidden token field being filled (classic Turnstile)
        token = _ev("""(function(){
          var e = document.querySelector('[name*=turnstile], [name*=cf-turnstile]');
          return e ? e.value : '';
        })()""")
        if token:
            return True
        # Check for "Verified" text or success state in the iframe
        ok = _ev("""(function(){
          var t = document.querySelector('.cf-turnstile-success, [class*=verified], [class*=success]');
          if (t) return true;
          return /verified|success/i.test(document.body.innerText || '');
        })()""")
        if ok:
            return True
        time.sleep(2)
    return False


def click(sitekey=None, timeout=30):
    """Click the Turnstile checkbox and wait for it to pass.

    Returns 'PASS' or 'FAIL:<reason>'.
    """
    if not present():
        return "FAIL:not on a turnstile page"

    result = _click_checkbox()
    if result == "PASS" and not _poll_for_pass(timeout):
        return "FAIL:clicked but no success within {}s".format(timeout)
    return result


def main():
    sk = sys.argv[1] if len(sys.argv) > 1 else None
    result = click(sk)
    print(result)
    return 0 if result == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
