#!/usr/bin/env python3
"""
dismiss_modal.py — close a blocking Indeed SERP modal (the "Get new jobs for this
search by email" job-alert popup, sign-in nudge, app-download interstitial, etc.).

WHY THIS EXISTS: Indeed renders interstitial modals into React portal zones
(`#mosaic-serpModals` / `#mosaic-zone-ssrSerpModals`), overlaying the page and
locking body scroll. The email/job-alert popup in particular blocked a run because
its close (X) has no clean a11y-tree ref (so `cfx.sh click <ref>` can't target it)
and the driver didn't try Escape — so the modal looked "not closable." This tries
every reliable dismissal in order and verifies the page is interactive again.

Usage:
    CFX_KEY=... CFX_TAB=... python3 dismiss_modal.py

Strategy (stops at the first that clears it):
  1. Nothing to do  — no modal open (zones empty + body scroll not locked).
  2. Escape         — the native, most reliable close for Indeed's modals.
  3. Close button   — click an X/"Close"/"Dismiss"/"No thanks" control scoped to the
                      modal zones (JS click; bypasses the missing a11y ref).
  4. Last resort    — strip the modal zone's content and restore body scroll, so a
                      stubborn overlay can't keep blocking the run.
Prints what it did and whether the page is interactive afterwards (exit 0 = clear).
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "_common", "scripts"))
import cfx  # noqa: E402

ZONES = "'#mosaic-serpModals','#mosaic-zone-ssrSerpModals'"

# Is a blocking modal currently open? (visible portal content OR body scroll locked
# OR a visible aria-modal dialog). Returns a short JSON-ish string.
STATE_EXPR = f"""
(() => {{
  const zones = [{ZONES}].map(s => document.querySelector(s)).filter(Boolean);
  const zoneText = zones.map(z => (z.innerText || '').trim()).join('');
  const modalDlg = [...document.querySelectorAll('[role=dialog][aria-modal=true],[aria-modal=true]')]
    .some(e => e.offsetParent !== null);
  const locked = /hidden|clip/.test(getComputedStyle(document.body).overflow)
              || /hidden|clip/.test(getComputedStyle(document.documentElement).overflow);
  const open = !!zoneText || modalDlg || locked;
  return JSON.stringify({{ open, lockedScroll: locked, snippet: zoneText.slice(0, 80) }});
}})()
"""

# Click a close-ish control inside the modal zones. Returns what it clicked, or ''.
CLICK_CLOSE_EXPR = f"""
(() => {{
  const zones = [{ZONES}].map(s => document.querySelector(s)).filter(Boolean);
  const isClose = el => {{
    const t = ((el.getAttribute('aria-label') || '') + ' ' + (el.getAttribute('title') || '')
      + ' ' + (el.textContent || '')).toLowerCase().trim();
    return /(^|\\b)(close|dismiss|no thanks|not now|maybe later|skip)(\\b|$)|^[×✕✖x]$/.test(t);
  }};
  for (const z of zones) {{
    const btns = [...z.querySelectorAll('button,[role=button],a')];
    const target = btns.find(isClose)
      || btns.find(b => b.querySelector('svg') && (b.getAttribute('aria-label') || '').toLowerCase().includes('close'))
      || btns.find(b => b.querySelector('svg') && b.getBoundingClientRect().width < 48);  // top-right X icon
    if (target) {{ target.click(); return (target.getAttribute('aria-label') || target.textContent || 'x-icon').trim().slice(0, 30); }}
  }}
  return '';
}})()
"""

STRIP_EXPR = f"""
(() => {{
  for (const s of [{ZONES}]) {{ const z = document.querySelector(s); if (z) z.innerHTML = ''; }}
  document.body.style.overflow = '';
  document.documentElement.style.overflow = '';
  return 'stripped';
}})()
"""

# Cloudflare-SAFE generic fallback: when a blocking overlay is NOT one of the known Indeed modal
# zones above (a "STILL BLOCKED" survivor — an aria-modal dialog or a full-screen high-z backdrop),
# hide it. NEVER touch a CAPTCHA / Cloudflare challenge (that is a wall, not a dismissable modal —
# report it, don't grind it). Never hide an overlay that CONTAINS job cards (that's the results).
GENERIC_STRIP_EXPR = r"""
(() => {
  const b = (document.body.innerText || '').slice(0, 400);
  if (/just a moment|checking your browser|verify you are human|cf-challenge|are you a robot|hcaptcha|recaptcha/i.test(b))
    return 'challenge';
  let hid = 0;
  document.querySelectorAll('[role=dialog][aria-modal=true],[aria-modal=true]').forEach(d => {
    if (!d.querySelector('[data-jk]')) { d.style.display = 'none'; hid++; }
  });
  [...document.querySelectorAll('div,section')].forEach(e => {
    const s = getComputedStyle(e), r = e.getBoundingClientRect();
    if ((s.position === 'fixed' || s.position === 'absolute')
        && r.width > innerWidth * 0.6 && r.height > innerHeight * 0.5
        && parseInt(s.zIndex || 0) >= 1000 && !e.querySelector('[data-jk]')) {
      e.style.display = 'none'; hid++;
    }
  });
  document.body.style.overflow = '';
  document.documentElement.style.overflow = '';
  return 'generic-hid-' + hid;
})()
"""


def _open():
    import json
    # A malformed / resultless /evaluate response makes cfx.evaluate return None, and
    # json.loads(None) raises TypeError — which the old `except (CfxError, ValueError)`
    # did NOT catch, so it escaped as a traceback and crashed the caller (this runs
    # before every Indeed enumeration). Guard on the type instead (the isinstance
    # pattern used in jd/cfx/check_login); any unreadable state = "assume no modal".
    try:
        raw = cfx.evaluate(STATE_EXPR)
        data = json.loads(raw) if isinstance(raw, str) else {}
        return bool(isinstance(data, dict) and data.get("open"))
    except (cfx.CfxError, ValueError):
        return False


def main():
    try:
        if not _open():
            print("clear: no modal open.")
            return 0

        # 2) Escape
        cfx.press("Escape")
        time.sleep(0.8)
        if not _open():
            print("dismissed via Escape.")
            return 0

        # 3) close button in the modal zone
        clicked = cfx.evaluate(CLICK_CLOSE_EXPR)
        if clicked:
            time.sleep(0.8)
            if not _open():
                print(f"dismissed via close control ({clicked!r}).")
                return 0

        # 4) strip the known Indeed modal zones + unlock
        cfx.evaluate(STRIP_EXPR)
        time.sleep(0.4)
        if not _open():
            print("dismissed via last-resort strip (overlay removed, scroll restored).")
            return 0

        # 5) generic Cloudflare-SAFE fallback for a survivor outside the known zones (a stray
        #    aria-modal dialog / full-screen backdrop). A CAPTCHA/Cloudflare challenge is a WALL,
        #    not a modal — report it, never grind it.
        try:
            r = cfx.evaluate(GENERIC_STRIP_EXPR)
        except cfx.CfxError:
            r = None
        if r == "challenge":
            print("BLOCKED: Indeed is showing a CAPTCHA/Cloudflare challenge — a wall, not a "
                  "dismissable modal. Halt Indeed; do NOT grind it.")
            return 2
        time.sleep(0.4)
        if not _open():
            print(f"dismissed via generic overlay fallback ({r}).")
            return 0

        print("STILL BLOCKED: modal survived Escape + close-click + strip + generic fallback — "
              "screenshot the tab.")
        return 1
    except cfx.CfxError as e:
        print(f"ERROR: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
