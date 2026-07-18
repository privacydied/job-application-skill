#!/usr/bin/env python3
"""login.py — log into Guardian Jobs (Madgex) via PASSWORD, going DIRECT to the password page.

WHY THIS EXISTS. `profile.theguardian.com/signin` DEFAULTS to email-OTP, and the "Sign in with
a password instead" link is a plain `<a>` that camofox's accessibility SNAPSHOT does not
surface — so a snapshot-driven agent can't find it, clicks "Continue with email", lands on the
OTP/passcode page (a code it can't read), and wrongly concludes "Guardian = OTP-only, can't log
in". This driver bypasses ALL of that: it navigates STRAIGHT to
`profile.theguardian.com/signin/password` (email + password fields), fills the Madgex creds
from ats-credentials.csv (`jobs.theguardian.com (Madgex)` row), and submits.

⛔ CAPTCHA POLICY: the submit is gated by a reCAPTCHA that distrusts the camofox fingerprint
(it silently blocks — valid creds, no error, stays on the page). This driver drives everything
UP TO the reCAPTCHA and then HANDS OFF to a one-time human noVNC pass — it NEVER grinds the
CAPTCHA. After the human pass, the session persists in the camofox profile and the logged-in
apply path is testable. See references/guardian-board-reality.md.

Usage:
    CFX_KEY=.. CFX_TAB=<tab> python3 sites/jobs.theguardian.com/scripts/login.py [--check]
      --check   only report whether a Guardian session is already active; don't fill anything.

Exit: 0 already/now logged in · 3 reached the reCAPTCHA wall (hand to noVNC) · 2 error/no creds.
"""
import json
import os
import sys
import time
from urllib.parse import quote

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_here, "..", "..", "_common", "scripts"))
import cfx        # noqa: E402
import httpfeed   # noqa: E402  (creds_row — the sanctioned credential source)

PW_URL = "https://profile.theguardian.com/signin/password"
VNC = "http://nasirjones:6080/vnc.html"


def _ev(js, tries=6):
    for _ in range(tries):
        try:
            v = cfx.evaluate(js)
            if v is not None:
                return v
        except cfx.CfxError:
            time.sleep(1.2)
    return None


def _signed_in():
    """Best-effort: is a Guardian session active? (redirected off the auth host, or a
    signed-in marker on the page.)"""
    st = _ev("(function(){var b=document.body?document.body.innerText:'';"
             "return JSON.stringify({onAuth:/profile\\.theguardian\\.com/.test(location.host),"
             "signedIn:/sign out|your account|edit profile|comment activity|manage my account/i.test(b)});})()")
    try:
        d = json.loads(st) if isinstance(st, str) else {}
    except ValueError:
        d = {}
    return (not d.get("onAuth")) or d.get("signedIn", False)


def main():
    argv = sys.argv[1:]
    if not os.environ.get("CFX_KEY"):
        print("ERROR: no CFX_KEY (source .jobenv).", file=sys.stderr)
        return 2

    if "--check" in argv:
        print("logged_in" if _signed_in() else "not_logged_in")
        return 0 if _signed_in() else 3

    email, pw = httpfeed.creds_row("jobs.theguardian.com")
    if not (email and pw):
        print("ERROR: no Guardian creds — add a `jobs.theguardian.com (Madgex)` row "
              "(email,password) to ats-credentials.csv.", file=sys.stderr)
        return 2

    # DIRECT to the password page (email pre-filled) — bypasses OTP + the snapshot-invisible link.
    res = cfx.goto(f"{PW_URL}?signInEmail={quote(email)}")
    if not res.get("ok"):
        print(f"ERROR: could not load the Guardian password page ({res}).", file=sys.stderr)
        return 2
    time.sleep(1)

    # accept a Sourcepoint cookie-consent overlay if present (best-effort; never hide it)
    _ev("(function(){var b=[...document.querySelectorAll('button')].find(function(e){"
        "return /yes, i.?m happy|yes, i accept|accept all/i.test(e.innerText||'');});"
        "if(b){b.click();return 'consent';}return 'none';})()")
    time.sleep(1)

    # fill email + password (native setter → the framework reads on change), then Sign in
    filled = _ev(
        "(function(){function set(sel,val){var e=document.querySelector(sel);if(!e)return 0;"
        "var s=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;"
        "s.call(e,val);e.dispatchEvent(new Event('input',{bubbles:true}));"
        "e.dispatchEvent(new Event('change',{bubbles:true}));return e.value.length;}"
        "return set('input[type=email],input[name=email]', %s)+'/'+"
        "set('input[type=password],input[name=password]', %s);})()"
        % (json.dumps(email), json.dumps(pw)))
    print(f"filled email/password fields ({filled})")
    _ev("(function(){var b=[...document.querySelectorAll('button[type=submit],button')]"
        ".find(function(e){return /^\\s*sign in\\b/i.test(e.innerText||'');});"
        "if(b){b.click();return 'clicked';}return 'no-btn';})()")
    time.sleep(6)

    if _signed_in():
        print("✓ logged into Guardian via password (session persists in the camofox profile).")
        return 0

    # not signed in + reCAPTCHA present ⇒ the fingerprint-distrust wall → hand to noVNC (policy).
    has_captcha = _ev("!!document.querySelector('[data-sitekey],iframe[src*=recaptcha],"
                      ".g-recaptcha,iframe[src*=turnstile],iframe[src*=hcaptcha]')")
    if has_captcha:
        print(f"⛔ reCAPTCHA is gating the Guardian sign-in and this camofox fingerprint can't "
              f"clear it (creds filled, no error). HAND OFF to a human: open noVNC ({VNC}) on "
              f"the password page — a real pointer passes the reCAPTCHA — then click Sign in. "
              f"Do NOT grind the CAPTCHA. After the pass, the session persists.", file=sys.stderr)
        return 3
    err = _ev("(function(){var b=document.body?document.body.innerText:'';"
              "return (b.match(/(incorrect|not recognised|invalid|too many|error)[^.\\n]{0,50}/i)||[''])[0];})()")
    print(f"⚠️ sign-in did not complete (no reCAPTCHA detected). Page note: {err or '(none)'}. "
          f"Check the creds / try noVNC ({VNC}).", file=sys.stderr)
    return 3


if __name__ == "__main__":
    sys.exit(main())
