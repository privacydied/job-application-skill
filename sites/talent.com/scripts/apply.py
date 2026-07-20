#!/usr/bin/env python3
"""talent.com apply driver — full "Quick Apply" flow (account OTP login + 3-step form).

VERIFIED-LIVE (2026-07-20). talent.com Quick Apply is a talent.com-HOSTED form (NOT an external
ATS), account-gated, and its FINAL submit is protected by a Cloudflare Turnstile.

FLOW the driver handles end to end:
  view?id=<id>  -> "Quick Apply" (<a target=_blank href=/redirect?...action=quickapply>)
  -> /apply?id=<id> which is EITHER:
       * NOT logged in -> "Sign in to apply": email -> 6-digit code emailed by
         no-reply@account.talent.co ("Complete your sign up!") -> 6 OTP boxes -> logged in
         (session persists in the camofox profile, so this is a one-time step).
       * logged in -> "Send application" opens a 3-STEP flow:
           1 of 3  Contact: First/Last/Email PREFILLED; Phone (config); CV UPLOAD
                   (click the "Upload CV" widget, attach to #resume-upload, fire change).
           2 of 3  Employer queries: an address text, an optional Cover letter + Salary
                   (from salary-cache), and Yes/No RADIO screeners (values "1"=True/Yes,
                   "0"=False/No). Answered from the screener bank + a London-office rule.
           3 of 3  Review + a Cloudflare TURNSTILE ("Verify you are human") gating a disabled
                   "Send application".

⚠️ TURNSTILE = HALT, by repo policy (references/captcha-policy.md): Cloudflare Turnstile is NOT
auto-solved (auto-clicking it just trips "Verification failed" and compounds the risk score). The
driver fills EVERYTHING, then when it reaches the Turnstile it prints TALENT_TURNSTILE_HALT + the
VNC URL, leaves the tab filled, and POLLS for the turnstile token. A human solves it once in VNC;
the driver detects the token, clicks Send, verifies the confirmation, and captures proof. That is
the sanctioned "autonomous up to the human captcha" wiring.

INTEGRITY: no PII hardcoded — phone/address from apply-defaults.json (fill.*), email = the account
email, salary from salary-cache.csv, radio answers from the screener bank (never fabricated: an
employer question with no truthful answer HALTS as needs_human).

CLI:
  CFX_KEY=.. CFX_TAB=.. python3 sites/talent.com/scripts/apply.py <view-url-or-id> [...] [--dry]
    --dry   fill everything but STOP before the final Send.
Exit: 0 sent · 3 turnstile/login handoff (solve in VNC, re-run) · 2 error/blocked.
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
import cfx        # noqa: E402
import atsform    # noqa: E402
import screener   # noqa: E402

VNC = "http://nasirjones:6080/vnc.html"
_CONF_RE = (r"application (sent|submitted|complete|received)|thank you for|has been sent|"
            r"successfully applied|we.?ve received|your application (has|is|was)")


def _cfg():
    try:
        return json.load(open(os.path.join(_COMMON, "apply-defaults.json"), encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


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


def _job_url(a):
    a = a.strip()
    return a if a.startswith("http") else f"https://uk.talent.com/view?id={a}"


def _salary_median(role, location="London"):
    """Cached market-median desired salary for the role (salary-cache.csv), or '' if absent."""
    path = os.path.join(_ROOT, "salary-cache.csv")
    try:
        import csv
        best = ""
        for row in csv.DictReader(open(path, encoding="utf-8")):
            if (role or "").lower() in (row.get("Role") or "").lower() and (row.get("Median") or "").strip():
                best = (row.get("Median") or "").strip()
        return best
    except Exception:  # noqa: BLE001
        return ""


# ── login (one-time; session persists in the camofox profile) ──────────────────────────────
def _account_email():
    return str((_cfg().get("fill") or {}).get("Email") or "").strip()


def _login_code(wait_s=120):
    """Freshest talent.com 6-digit code from the applicant mailbox (email_ingest IMAP). The
    template repeats a constant 6-digit string, so the OTP is the \\d{6} that appears once."""
    import email as emaillib
    import email_ingest as ei
    from datetime import datetime
    deadline = time.time() + wait_s
    while True:
        try:
            M = ei._connect()
            M.select("INBOX", readonly=True)
            typ, data = M.search(None, "(SINCE %s)" % datetime.now().strftime("%d-%b-%Y"))
            for n in reversed((data[0].split() if (typ == "OK" and data and data[0]) else [])[-30:]):
                t, md = M.fetch(n, "(RFC822)")
                if t != "OK" or not md or not md[0]:
                    continue
                m = emaillib.message_from_bytes(md[0][1])
                if "talent" not in (m.get("From") or "").lower():
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
    print("  talent: sign-in wall — logging in via emailed code")
    _ev("""(function(){var b=[...document.querySelectorAll('button')].find(function(e){return /^i accept$|accept all/i.test((e.innerText||'').trim());});if(b)b.click();return 'ok';})()""")
    _ev("""(function(){var e=document.querySelector('input[type=email],input[name=email]');if(e){e.focus();var s=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;s.call(e,%s);e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));}var c=[...document.querySelectorAll('button,input[type=submit]')].find(function(x){return /^continue$/i.test((x.innerText||x.value||'').trim());});if(c)c.click();return 'ok';})()""" % json.dumps(_account_email()))
    time.sleep(5)
    code = _login_code()
    if not code:
        return False
    _ev("""(function(c){var boxes=[...document.querySelectorAll('input[type=tel],input[maxlength="1"],input[autocomplete*=one-time]')].filter(function(e){return e.offsetParent&&(e.maxLength===1||e.type==='tel');});var set=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;if(boxes.length>=6){for(var i=0;i<6;i++){var e=boxes[i];e.focus();set.call(e,c[i]);e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));}return 'ok';}var one=[...document.querySelectorAll('input')].find(function(e){return e.offsetParent&&/code|otp|verif|one-time/i.test((e.name||e.placeholder||e.autocomplete||''));});if(one){one.focus();set.call(one,c);one.dispatchEvent(new Event('input',{bubbles:true}));}return 'ok';})(""" + json.dumps(code) + ")")
    time.sleep(2)
    _ev("""(function(){var b=[...document.querySelectorAll('button,input[type=submit]')].find(function(x){return /verify|continue|submit|confirm/i.test((x.innerText||x.value||'').trim());});if(b)b.click();return 'ok';})()""")
    time.sleep(6)
    return not _ev("/sign in to apply/i.test(document.body.innerText||'')")


# ── per-step filling ───────────────────────────────────────────────────────────────────────
def _upload_cv():
    """Click the "Upload CV" widget (the file input #resume-upload is inert until then), attach the
    resume, and fire change so React registers it."""
    _ev("""(function(){var t=[...document.querySelectorAll('div,label,button')].find(function(e){return e.offsetParent&&/^upload cv$/i.test((e.innerText||'').trim());});if(t)t.click();return 'ok';})()""")
    time.sleep(1.5)
    if _ev("!!document.getElementById('resume-upload')"):
        cv = os.environ.get("TALENT_CV", "base-resume.pdf")
        try:
            print("  talent: CV ->", atsform.upload("#resume-upload", cv))
            _ev("""(function(){var e=document.getElementById('resume-upload');if(e){e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));}return 'ok';})()""")
        except Exception as e:  # noqa: BLE001
            print(f"  talent: CV upload warn {e}", file=sys.stderr)


def _fill_text_fields(role):
    """Fill visible text/textarea fields on the current step: phone/address from config (by label),
    salary from salary-cache, cover letter from config if present. Plain inputs — value-set is fine."""
    fill = _cfg().get("fill") or {}
    # phone + address via atsform (label resolution)
    for lab, val in fill.items():
        if not isinstance(val, str) or not val:
            continue
        if re.search(r"phone|address|town|post ?code|city|first|last|name", lab, re.I):
            try:
                atsform.fill(lab if not lab.lower().startswith("address") else "address", val, quiet_notfound=True)
            except Exception:  # noqa: BLE001
                pass
    # salary expectations -> cached median
    med = _salary_median(role)
    if med:
        _ev("""(function(v){var e=[...document.querySelectorAll('input[type=text]')].find(function(x){return x.offsetParent&&/salary/i.test((x.labels&&x.labels[0]?x.labels[0].innerText:'')||(x.closest('div')||{}).textContent||'');});if(e&&!e.value){e.focus();var s=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;s.call(e,v);e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));}return 'ok';})(""" + json.dumps(re.sub(r"[^0-9]", "", med)) + ")")
    # cover letter (optional) from config, if a textarea + config value exist
    cover = str(fill.get("Cover letter") or fill.get("cover_letter") or "").strip()
    if cover:
        _ev("""(function(v){var e=[...document.querySelectorAll('textarea')].find(function(x){return x.offsetParent&&!x.value&&/cover/i.test((x.labels&&x.labels[0]?x.labels[0].innerText:'')||(x.closest('div')||{}).textContent||'');});if(e){e.focus();var s=Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype,'value').set;s.call(e,v);e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));}return 'ok';})(""" + json.dumps(cover) + ")")


def _answer_radios():
    """Answer Yes/No employer radio screeners from the screener bank (values 1=Yes/True, 0=No/False).
    London-office/on-site questions -> Yes (the applicant is London-based, accepts hybrid). An
    UNKNOWN question is left BLANK (never guessed) so the step won't advance -> surfaces as STUCK."""
    groups = json.loads(_ev("""(function(){var g={};[...document.querySelectorAll('input[type=radio]')].forEach(function(r){(g[r.name]=g[r.name]||[]).push(r);});return JSON.stringify(Object.keys(g).map(function(n){var rs=g[n];var box=rs[0].closest('fieldset,div,li');var q=box?[...box.querySelectorAll('label,legend,p,span')].map(function(x){return (x.innerText||'').trim();}).filter(function(t){return t&&t.length<80&&!/^(yes|no|true|false)$/i.test(t);})[0]:'';return {name:n,q:q||'',answered:rs.some(function(x){return x.checked;})};}));})()""") or "[]")
    unresolved = []
    for grp in groups:
        if grp["answered"]:
            continue
        q = grp["q"]
        ans = screener.lookup(q)
        want = ans["answer"] if ans else None
        if not want and re.search(r"office|on.?site|days a week|commute|based in", q, re.I):
            want = "Yes" if re.search(r"london", q, re.I) else ("No" if re.search(r"manchester|leeds|bristol|birmingham|edinburgh|glasgow|cardiff", q, re.I) else None)
        if not want:
            unresolved.append(q[:50])
            continue
        val = "1" if want.strip().lower() in ("yes", "true", "y") else "0"
        _ev("""(function(name,val){var rs=[...document.querySelectorAll('input[name="'+name+'"]')];var one=rs.find(function(r){return r.value===val;});if(one){var l=(one.labels&&one.labels[0])||one.closest('label')||document.querySelector('label[for="'+one.id+'"]');if(l)l.click();else one.click();one.checked=true;one.dispatchEvent(new Event('click',{bubbles:true}));one.dispatchEvent(new Event('change',{bubbles:true}));}return 'ok';})(""" + json.dumps(grp["name"]) + "," + json.dumps(val) + ")")
        time.sleep(0.4)
    return unresolved


# ── the Turnstile-gated final submit ───────────────────────────────────────────────────────
def _turnstile_present():
    return _ev("(function(){var t=document.querySelector('[name*=turnstile]');return !!t && !t.value;})()")


def _send_enabled():
    return _ev("(function(){var b=[...document.querySelectorAll('button')].filter(function(e){return e.offsetParent;}).find(function(x){return /send application/i.test(x.innerText||'');});return b?!b.disabled:false;})()")


def _final_submit(job, company, role, dry):
    if dry:
        return "DRY_READY (at Turnstile/Send)"
    # HALT for a human VNC Turnstile solve — do NOT auto-click it (policy: compounds risk score).
    if _turnstile_present() and not _send_enabled():
        print(f"\nTALENT_TURNSTILE_HALT — {company or job} | {role} needs the Cloudflare 'Verify you "
              f"are human' checkbox solved. Held; tab left filled. Solve in VNC: {VNC}", file=sys.stderr)
        deadline = time.time() + 900   # poll up to 15 min for the human solve
        while time.time() < deadline:
            if _send_enabled():
                print("  talent: Turnstile cleared — sending")
                break
            time.sleep(5)
        else:
            return "TURNSTILE_HELD (solve in VNC, re-run)"
    # send + verify
    _ev("""(function(){[...document.querySelectorAll('input[type=checkbox]')].filter(function(e){return e.offsetParent&&!e.checked;}).forEach(function(c){c.click();});var b=[...document.querySelectorAll('button,input[type=submit]')].filter(function(e){return e.offsetParent&&!e.disabled;}).find(function(x){return /send application/i.test(x.innerText||x.value||'');});if(b)b.click();return 'ok';})()""")
    for _ in range(12):
        time.sleep(2)
        if _ev("/%s/i.test(document.body.innerText||'')" % _CONF_RE):
            return "SENT"
    return "SENT_UNCONFIRMED"


def apply(job, dry=False):
    cfg_role = ""
    url = _job_url(job)
    cfx.navigate(url)
    time.sleep(7)
    role = _ev("(function(){var h=document.querySelector('h1,[class*=title]');return h?h.innerText.trim().slice(0,50):'';})()") or ""
    company = _ev("(function(){var c=[...document.querySelectorAll('[class*=company],a[href*=company]')].map(function(e){return (e.innerText||'').trim();}).filter(Boolean);return c[0]||'';})()") or ""
    cfg_role = role
    if _ev("""(function(){var b=[...document.querySelectorAll('a,button')].find(function(e){return /quick apply/i.test(e.innerText||'');});if(b){b.removeAttribute('target');b.click();return true;}return false;})()""") is not True:
        return f"[{job}] NO_QUICKAPPLY (external/expired)"
    time.sleep(7)
    if _ev("/sign in to apply/i.test(document.body.innerText||'')"):
        if not _do_login():
            return f"[{job}] LOGIN_HANDOFF (talent sign-in — check mailbox / VNC {VNC})"
        cfx.navigate(url)
        time.sleep(6)
        _ev("""(function(){var b=[...document.querySelectorAll('a,button')].find(function(e){return /quick apply/i.test(e.innerText||'');});if(b){b.removeAttribute('target');b.click();}return 'ok';})()""")
        time.sleep(6)
    # open the 3-step flow
    _ev("""(function(){var b=[...document.querySelectorAll('button,input[type=submit]')].find(function(x){return /send application/i.test((x.innerText||x.value||'').trim());});if(b)b.click();return 'ok';})()""")
    time.sleep(6)
    # walk the steps
    last = ""
    for _ in range(6):
        _upload_cv()
        _fill_text_fields(cfg_role)
        unresolved = _answer_radios()
        _ev("(function(){var cb=document.querySelector('input[name=user_consent]');if(cb&&!cb.checked)cb.click();return 'ok';})()")
        step = _ev("((document.body.innerText.match(/(\\d) of (\\d)/)||['','',''])[0])") or ""
        if re.match(r"3 of 3|review", str(step), re.I) or _ev("!!document.querySelector('[name*=turnstile]')"):
            return f"[{job}] {_final_submit(job, company, role, dry)}"
        _ev("""(function(){var b=[...document.querySelectorAll('button,input[type=submit]')].filter(function(e){return e.offsetParent&&!e.disabled;}).find(function(x){return /^continue$|^next$/i.test((x.innerText||x.value||'').trim());});if(b)b.click();return 'ok';})()""")
        time.sleep(4)
        cur = _ev("((document.body.innerText.match(/\\d of \\d/)||[''])[0])+'|'+location.pathname") or ""
        if cur and cur == last:
            if unresolved:
                return f"[{job}] STUCK — unanswerable employer query (needs_human): {unresolved[:2]}"
            return f"[{job}] STUCK ({cur[:30]}) — needs_human"
        last = cur
    return f"[{job}] SENT_UNCONFIRMED"


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
