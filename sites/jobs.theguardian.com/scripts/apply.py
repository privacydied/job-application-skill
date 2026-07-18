#!/usr/bin/env python3
"""apply.py — drive a Guardian Jobs (Madgex) IN-PLATFORM application, autonomously.

Guardian jobs split ~50/50 (measured, logged-in): some apply via an ON-PAGE form
(name/email/CV/cover + reCAPTCHA v2 → "Send application"), others "Apply on website" →
redirect to the employer's OWN ATS (a per-employer account wall). The feed's `guardian-direct`
hint is an OPTIMISTIC DEFAULT, not verified — so this driver CLASSIFIES at apply time and only
drives the in-platform ones; external ones are reported (never a false submit).

Flow (all via shipped tools — atsform for fill/upload, recaptcha.py for the sanctioned v2 solve,
login.py for the session):
  1. ensure logged in (login.py --check; run login.py if not).
  2. open the job → classify:
       IN-PLATFORM  = on-page #application-form (input[name=cv] etc.)  → drive it
       EXTERNAL     = "Apply on website" / redirect off jobs.theguardian.com → report, skip
  3. reach the form (#application-form), fill firstName/lastName/email from apply-defaults.json,
     upload the CV (a plain visible <input type=file> — atsform.upload binds it directly),
     add the cover message, and OPT OUT of the marketing checkboxes.
  4. reCAPTCHA v2 (sanctioned) → recaptcha.py; verify by screenshot.
  5. atsform.review (email gate / empty-required) → "Send application".
  6. capture proof + report.

⛔ Never fabricates, never submits an off-profile role (screen the title with check_title
first — this driver assumes the caller already did). CAPTCHA policy: only the sanctioned
reCAPTCHA v2 auto-solve; anything else halts.

Usage:
    CFX_KEY=.. CFX_TAB=.. python3 sites/jobs.theguardian.com/scripts/apply.py <job-url> \
        --cv uploads/<resume>.pdf [--cover "<message>"] [--no-submit]
  --no-submit  fill everything + solve the reCAPTCHA but STOP before Send (safe verification).
  classify-only:  apply.py <job-url> --classify

Exit: 0 submitted (or --no-submit ready) · 3 external/account-wall (skip) · 2 error/blocked.
"""
import json
import os
import subprocess
import sys
import time

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_here, "..", "..", "_common", "scripts"))
import cfx        # noqa: E402
import atsform    # noqa: E402
import httpfeed   # noqa: E402

LOGIN = os.path.join(_here, "login.py")
RECAPTCHA = os.path.join(_here, "..", "..", "_common", "scripts", "recaptcha.py")
_ROOT = os.path.abspath(os.path.join(_here, "..", "..", ".."))


def _ev(js, tries=8):
    for _ in range(tries):
        try:
            v = cfx.evaluate(js)
            if v is not None:
                return v
        except cfx.CfxError:
            time.sleep(1.2)
    return None


def _fill_facts():
    """firstName/lastName/email from the gitignored apply-defaults.json `fill` block."""
    try:
        fill = json.load(open(os.path.join(_ROOT, "sites", "_common", "apply-defaults.json"),
                              encoding="utf-8")).get("fill", {})
    except (OSError, ValueError):
        fill = {}
    return fill


def ensure_login():
    r = subprocess.run([sys.executable, LOGIN, "--check"], cwd=_ROOT, env=os.environ,
                       capture_output=True, text=True, timeout=60)
    if "logged_in" in (r.stdout or ""):
        return True
    r = subprocess.run([sys.executable, LOGIN], cwd=_ROOT, env=os.environ,
                       capture_output=True, text=True, timeout=180)
    return "logged into Guardian" in (r.stdout or "")


def classify():
    """'in-platform' | 'external' | 'no-apply' for the CURRENT job page."""
    return _ev("(function(){"
               "if(document.querySelector('#application-form,input[name=cv]'))return 'in-platform';"
               "var ext=[].slice.call(document.querySelectorAll('a')).find(function(a){"
               "return /external-redirect-registration/.test(a.getAttribute('href')||'')||"
               "/apply on website/i.test((a.innerText||''));});"
               "if(ext)return 'external';return 'no-apply';})()") or "no-apply"


def _accept_consent():
    _ev("(function(){var b=[].slice.call(document.querySelectorAll('button')).find(function(e){"
        "return /yes, i.?m happy|yes, i accept|accept all/i.test(e.innerText||'');});"
        "if(b){b.click();return 1;}return 0;})()")


def _opt_out():
    """Uncheck the marketing opt-ins (CV database / free review / job alerts)."""
    _ev("(function(){['cvDatabaseOptIn','sendCvForReview','jobAlerts'].forEach(function(n){"
        "var e=document.querySelector('input[name='+n+']');"
        "if(e&&e.checked){e.click();}});return 1;})()")


def main():
    argv = sys.argv[1:]
    urls = [a for a in argv if a.startswith("http")]
    if not urls:
        print(__doc__)
        return 2
    url = urls[0]

    def opt(flag, default=None):
        return argv[argv.index(flag) + 1] if flag in argv and argv.index(flag) + 1 < len(argv) else default

    cv = opt("--cv")
    cover = opt("--cover")
    no_submit = "--no-submit" in argv
    classify_only = "--classify" in argv

    if not os.environ.get("CFX_KEY"):
        print("ERROR: no CFX_KEY.", file=sys.stderr)
        return 2

    if not classify_only and not ensure_login():
        print("BLOCKED: not logged into Guardian — run login.py (may need a one-time noVNC "
              "reCAPTCHA pass).", file=sys.stderr)
        return 2

    res = cfx.goto(url)
    if not res.get("ok"):
        print(f"ERROR: could not open {url} ({res}).", file=sys.stderr)
        return 2
    time.sleep(2)
    _accept_consent()

    kind = classify()
    print(f"apply-type: {kind}")
    if classify_only:
        return 0 if kind == "in-platform" else 3
    if kind == "external":
        print("⏭  EXTERNAL — 'Apply on website' redirects to the employer's own ATS (a "
              "per-employer account wall). Not an in-platform submit; log as external, skip.",
              file=sys.stderr)
        return 3
    if kind != "in-platform":
        print("BLOCKED: no apply control found.", file=sys.stderr)
        return 2

    # reach the on-page form (click the in-platform Apply → #application-form)
    _ev("(function(){var a=[].slice.call(document.querySelectorAll('a,button')).find(function(e){"
        "var t=(e.innerText||'').trim();return /apply/i.test(t)&&!/website|no thanks/i.test(t);});"
        "if(a)a.click();return 1;})()")
    time.sleep(2)
    if not _ev("!!document.querySelector('input[name=cv]')"):
        print("BLOCKED: in-platform form did not render its fields.", file=sys.stderr)
        return 2

    # fill name/email from config
    f = _fill_facts()
    for label, key in (("First name", "First name"), ("Last name", "Last name"),
                       ("email address", "Email")):
        if f.get(key):
            atsform.fill(label, f[key])
    # CV upload (required) — plain visible file input; atsform.upload binds it directly
    if not cv:
        print("BLOCKED: --cv <resume.pdf> is required for a Guardian application.", file=sys.stderr)
        return 2
    up = atsform.upload("Your CV", os.path.basename(cv))
    if not _ev("(function(){var e=document.querySelector('input[name=cv]');"
               "return e&&e.files&&e.files.length?1:0;})()"):
        print(f"BLOCKED: CV upload did not bind ({up}).", file=sys.stderr)
        return 2
    if cover:
        atsform.fill("cover message", cover)
    _opt_out()

    # reCAPTCHA v2 (sanctioned) — solve + verify by screenshot
    if _ev("!!document.querySelector('[data-sitekey],iframe[src*=recaptcha],.g-recaptcha')"):
        print("reCAPTCHA present — attempting the sanctioned recaptcha.py v2 solve...")
        subprocess.run([sys.executable, RECAPTCHA, "click"], cwd=_ROOT, env=os.environ,
                       timeout=90, capture_output=True)
        subprocess.run([sys.executable, RECAPTCHA, "wait-token"], cwd=_ROOT, env=os.environ,
                       timeout=120, capture_output=True)
        has_token = _ev("(function(){var t=document.querySelector('textarea[name=g-recaptcha-response]');"
                        "return t&&t.value&&t.value.length>20?1:0;})()")
        print("reCAPTCHA token issued:" , bool(has_token))
        if not has_token:
            print("⛔ reCAPTCHA did not issue a token for this fingerprint. Everything else is "
                  "filled — hand the final reCAPTCHA + Send to noVNC "
                  "(http://nasirjones:6080/vnc.html). Do NOT grind it.", file=sys.stderr)
            return 3

    if no_submit:
        print("✓ --no-submit: all fields filled, CV bound, reCAPTCHA handled. NOT sending. "
              "Remove --no-submit to submit.")
        return 0

    # Send application + capture proof
    _ev("(function(){var b=[].slice.call(document.querySelectorAll('button,input[type=submit]'))"
        ".find(function(e){return /send application/i.test((e.innerText||e.value||''));});"
        "if(b)b.click();return 1;})()")
    time.sleep(5)
    ok = _ev("(function(){var b=document.body?document.body.innerText:'';"
             "return /application (sent|submitted|received)|thank you|we have received/i.test(b)?1:0;})()")
    if ok:
        print("✓ application sent (confirmation detected). Capture proof + log via "
              "log-application.py --proof.")
        return 0
    print("⚠️ Send clicked but no confirmation detected — verify on the account dashboard "
          "(app.welcometothejungle... no: jobs.theguardian.com account/applications) before "
          "logging Applied.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
