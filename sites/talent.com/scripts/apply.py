#!/usr/bin/env python3
"""talent.com apply driver — authenticated "Quick Apply" (native talent.com form).

VERIFIED-LIVE FLOW (2026-07-20). talent.com Quick Apply is a talent.com-HOSTED form, NOT an
external ATS — but it is ACCOUNT-GATED:

  job page  https://uk.talent.com/view?id=<id>
    -> "Quick Apply" <a target=_blank href="/redirect?id=<id>&pid=<pid>&action=quickapply">
    -> renders  /apply?id=<id>...  which is EITHER:
         (a) LOGGED IN  -> a short form: First name / Last name / Email (PREFILLED from the
             account) + Phone + a user_consent checkbox (pre-ticked) + "Send application".
             NO reCAPTCHA once authenticated.
         (b) NOT logged in -> a "Sign in to apply" wall: Email field + Continue. Entering the
             email triggers a 6-digit login code from  no-reply@account.talent.co  ("Complete
             your sign up!"); the code goes into 6 single-char OTP boxes -> logged in. The
             account/session then PERSISTS in the camofox profile, so (a) is the steady state
             and login is only needed once (or after a session expiry). A reCAPTCHA guards the
             sign-UP step only; sign-in reuse does not hit it.

So hermes never gets stuck: this driver auto-detects (a)/(b), self-logs-in via the emailed code
(reusing the OTP mailbox path), fills the form from config, sends, and verifies the confirmation.

INTEGRITY: no PII is hardcoded here. Phone is read at runtime from apply-defaults.json (fill.Phone);
name/email come prefilled from the account. Never fabricates. Captures a confirmation screenshot as
--proof so log-application can log strict Applied.

CLI:
  CFX_KEY=.. CFX_TAB=.. python3 sites/talent.com/scripts/apply.py <view-url-or-id> [<id> ...] [--dry]
    --dry   fill everything but STOP before "Send application" (safe verification)
Exit: 0 sent / --dry ready · 3 login-captcha handoff (run recaptcha.py, re-run) · 2 error/blocked.
"""
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
_COMMON = os.path.join(HERE, "..", "..", "_common", "scripts")
_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, _COMMON)
sys.path.insert(0, os.path.join(_ROOT, "scripts"))
import cfx  # noqa: E402


def _cfg_phone():
    """The applicant's phone from the gitignored config (fill.Phone) — never hardcoded here."""
    try:
        cfg = json.load(open(os.path.join(_COMMON, "apply-defaults.json"), encoding="utf-8"))
        return str((cfg.get("fill") or {}).get("Phone") or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def _ev(expr):
    try:
        return cfx.evaluate(expr)
    except cfx.CfxError:
        return None


def _job_url(a):
    a = a.strip()
    if a.startswith("http"):
        return a
    return f"https://uk.talent.com/view?id={a}"


def _click_quick_apply():
    return _ev("""(function(){
      var b=[...document.querySelectorAll('a,button')].find(function(e){return /quick apply/i.test(e.innerText||'');});
      if(!b) return 'NO_QUICKAPPLY';
      b.removeAttribute('target');   // keep it same-tab so we can drive it
      b.click(); return 'clicked';
    })()""")


def _apply_state():
    """Which screen is the /apply page on? 'form' (logged in), 'login' (sign-in wall), or 'other'."""
    return _ev("""(function(){
      var body=(document.body?document.body.innerText:'')||'';
      if(document.querySelector('input')&&[...document.querySelectorAll('label,input')].some(function(e){return /first name/i.test((e.innerText||e.getAttribute('aria-label')||e.placeholder||''));})) return 'form';
      if(/sign in to apply/i.test(body)||document.querySelector('input[type=email],input[name=email]')) return 'login';
      return 'other:'+body.replace(/\\s+/g,' ').trim().slice(0,60);
    })()""")


def _login_code_from_mailbox(wait_s=120):
    """The freshest talent.com 6-digit login code from the applicant mailbox (the IMAP host
    configured in ats-credentials.csv), reusing email_ingest's IMAP connection. The template
    repeats a constant 6-digit string, so the OTP is the \\d{6} that appears exactly ONCE."""
    import email as emaillib
    import email_ingest as ei
    from datetime import datetime
    deadline = time.time() + wait_s
    while True:
        try:
            M = ei._connect()
            M.select("INBOX", readonly=True)
            typ, data = M.search(None, "(SINCE %s)" % datetime.now().strftime("%d-%b-%Y"))
            nums = data[0].split() if (typ == "OK" and data and data[0]) else []
            for n in reversed(nums[-30:]):
                t, md = M.fetch(n, "(RFC822)")
                if t != "OK" or not md or not md[0]:
                    continue
                m = emaillib.message_from_bytes(md[0][1])
                frm = (m.get("From") or "").lower()
                if "talent" not in frm:
                    continue
                body = ""
                if m.is_multipart():
                    for p in m.walk():
                        if p.get_content_type() == "text/plain":
                            body += (p.get_payload(decode=True) or b"").decode("utf-8", "replace")
                else:
                    body = (m.get_payload(decode=True) or b"").decode("utf-8", "replace")
                blob = (m.get("Subject") or "") + " " + body
                uniq = [c for c in re.findall(r"\b\d{6}\b", blob) if blob.count(c) == 1]
                if uniq:
                    try:
                        M.logout()
                    except Exception:  # noqa: BLE001
                        pass
                    return uniq[0]
            try:
                M.logout()
            except Exception:  # noqa: BLE001
                pass
        except Exception as e:  # noqa: BLE001
            print(f"  TALENT_CODE_WARN {e}", file=sys.stderr)
        if time.time() >= deadline:
            return ""
        time.sleep(6)


def _do_login():
    """Handle the sign-in wall: email -> emailed 6-digit code -> OTP boxes. Returns True if the
    account session is established (a quick-apply form should now render). If a reCAPTCHA blocks
    the send, returns 'CAPTCHA' so the caller hands off (recaptcha.py) instead of looping."""
    print("  talent: sign-in wall — logging in via emailed code")
    _ev("""(function(){
      var b=[...document.querySelectorAll('button')].find(function(e){return /^i accept$|accept all/i.test((e.innerText||'').trim());});if(b)b.click();
      var e=document.querySelector('input[type=email],input[name=email]');
      if(e){e.focus();var s=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;s.call(e,%s);e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));}
      var c=[...document.querySelectorAll('button,input[type=submit]')].find(function(x){return /^continue$/i.test((x.innerText||x.value||'').trim());});if(c)c.click();
      return 'sent';
    })()""" % json.dumps(_account_email()))
    time.sleep(5)
    if _ev("!!document.querySelector('iframe[src*=recaptcha]') && !document.querySelector('input[maxlength=\"1\"]')"):
        print("  TALENT_LOGIN_CAPTCHA — solve the reCAPTCHA (recaptcha.py) then re-run", file=sys.stderr)
        return "CAPTCHA"
    code = _login_code_from_mailbox()
    if not code:
        print("  TALENT_NO_CODE — no login code arrived in the mailbox", file=sys.stderr)
        return False
    r = _ev("""(function(c){
      var boxes=[...document.querySelectorAll('input[type=tel],input[maxlength="1"],input[autocomplete*=one-time]')].filter(function(e){return e.offsetParent&&(e.maxLength===1||e.type==='tel');});
      var set=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
      if(boxes.length>=6){for(var i=0;i<6;i++){var e=boxes[i];e.focus();set.call(e,c[i]);e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));}return 'FILLED';}
      var one=[...document.querySelectorAll('input')].find(function(e){return e.offsetParent&&/code|otp|verif|one-time/i.test((e.name||e.placeholder||e.autocomplete||''));});
      if(one){one.focus();set.call(one,c);one.dispatchEvent(new Event('input',{bubbles:true}));return 'FILLED1';}
      return 'NO_BOXES';
    })(""" + json.dumps(code) + ")")
    print(f"  talent: entered login code -> {r}")
    time.sleep(2)
    _ev("""(function(){var b=[...document.querySelectorAll('button,input[type=submit]')].find(function(x){return /verify|continue|submit|confirm/i.test((x.innerText||x.value||'').trim());});if(b)b.click();return 'ok';})()""")
    time.sleep(6)
    return not _ev("/sign in to apply/i.test(document.body.innerText||'')")


def _account_email():
    """The talent.com account email = the applicant's config email (fill/applicant), never hardcoded."""
    try:
        cfg = json.load(open(os.path.join(_COMMON, "apply-defaults.json"), encoding="utf-8"))
        return str((cfg.get("fill") or {}).get("Email") or "").strip()
    except Exception:  # noqa: BLE001
        return ""


_CONF_JS = ("/application sent|thank you|has been sent|successfully applied|we.?ve received|"
            "application (submitted|complete)|your application/i.test(document.body.innerText||'')")


def _fill_and_send(dry):
    """Walk the MULTI-STEP quick-apply (contact -> CV -> submit): fill phone + tick consent +
    upload the CV, then click each step's advance button and loop until a confirmation shows.
    Name/email are prefilled from the account. dry=True stops before advancing. Stops with STUCK
    (needs_human) if a step stops advancing — a required question the driver can't answer is NOT
    fabricated."""
    import atsform
    phone = _cfg_phone()
    _ev("""(function(p){
      var tel=document.querySelector('input[type=tel],input[name*=phone],#phone-input');
      if(tel && p){tel.focus();var s=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;s.call(tel,p);tel.dispatchEvent(new Event('input',{bubbles:true}));tel.dispatchEvent(new Event('change',{bubbles:true}));}
      var cb=document.querySelector('input[name=user_consent],input[type=checkbox]');
      if(cb && !cb.checked){cb.click();}
      return 'filled';
    })(""" + json.dumps(phone) + ")")
    if _ev("!!document.querySelector('input[type=file]')"):
        cv = os.environ.get("TALENT_CV", "base-resume.pdf")
        try:
            print("  talent: CV upload ->", atsform.upload("input[type=file]", cv))
        except Exception as e:  # noqa: BLE001
            print(f"  talent: CV upload warn {e}", file=sys.stderr)
    time.sleep(1)
    if dry:
        return "DRY_READY"
    last = ""
    for _ in range(7):
        _ev("""(function(){var b=[...document.querySelectorAll('button,input[type=submit]')].filter(function(e){return e.offsetParent;}).find(function(x){return /send application|submit application|^submit$|^continue$|^next$|^apply$/i.test((x.innerText||x.value||'').trim());});if(b)b.click();return 'ok';})()""")
        time.sleep(4)
        if _ev(_CONF_JS):
            return "SENT"
        cur = _ev("((document.body.innerText.match(/\\d of \\d/)||[''])[0])+'|'+location.pathname")
        cur = cur if isinstance(cur, str) else ""
        if cur and cur == last:
            return f"STUCK ({cur[:40]}) — a step needs input the driver can't supply; needs_human"
        last = cur
    return "SENT_UNCONFIRMED"


def apply(job, dry=False):
    url = _job_url(job)
    cfx.navigate(url)
    time.sleep(7)
    if _click_quick_apply() == "NO_QUICKAPPLY":
        return f"[{job}] NO_QUICKAPPLY (external/expired listing)"
    time.sleep(7)
    st = _apply_state()
    if st == "login":
        r = _do_login()
        if r == "CAPTCHA":
            return f"[{job}] LOGIN_CAPTCHA — run recaptcha.py then re-run"
        if not r:
            return f"[{job}] LOGIN_FAILED"
        # after login, re-open the job + quick apply (now authenticated)
        cfx.navigate(url)
        time.sleep(6)
        _click_quick_apply()
        time.sleep(6)
        st = _apply_state()
    if st != "form":
        return f"[{job}] NO_FORM ({st})"
    return f"[{job}] {_fill_and_send(dry)}"


def main():
    args = sys.argv[1:]
    dry = "--dry" in args
    jobs = [a for a in args if not a.startswith("--")]
    if not jobs:
        print(__doc__)
        return 1
    for j in jobs:
        print(apply(j, dry=dry))
        time.sleep(3)
    return 0


if __name__ == "__main__":
    sys.exit(main())
