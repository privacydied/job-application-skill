#!/usr/bin/env python3
"""Re-authenticate a dead CSJ/TAL session (scriptable, per csj-tal-eform-notes.md).
Opens a FRESH tab, navigates to login.cgi, fills creds from ats-credentials.csv,
clicks Sign in, verifies the logged-in state ("Sign out" present).
"""
import sys, time, csv, json, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "sites", "_common", "scripts"))
import cfx

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

def ev(expr, tries=5):
    for _ in range(tries):
        try:
            r = cfx.evaluate(expr)
            if r is not None:
                return r
        except Exception:
            pass
        time.sleep(2)
    return None

def main():
    cred = None
    for row in csv.reader(open(os.path.join(ROOT, "ats-credentials.csv"))):
        if row and "civilservicejobs" in row[0]:
            cred = row
            break
    if not cred:
        print("NO_CREDS"); return 1
    email, pw = cred[1], cred[2]

    cfx.set_tab(cfx.open_tab(session_key="job-apply"))   # fresh tab required
    time.sleep(2)
    cfx.navigate("https://www.civilservicejobs.service.gov.uk/csr/login.cgi")
    time.sleep(5)

    SET = """(name,val)=>{const e=document.querySelector('input[name="'+name+'"]');if(!e)return 'NO:'+name;const s=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;s.call(e,val);e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));return 'OK:'+name;}"""
    # pass args as a single JSON array to avoid % formatting collisions
    def call(expr_fn, *args):
        arg_json = "[" + ",".join(json.dumps(a) for a in args) + "]"
        return ev("(" + expr_fn + ").apply(null," + arg_json + ")")
    print("user:", call(SET, "username", email))
    print("pass:", call(SET, "password_login_window", pw))
    print("click:", ev("(()=>{const b=document.querySelector('input[name=login_button]');if(!b)return 'NOBTN';b.click();return 'CLICKED';})()"))
    time.sleep(6)
    title = ev("document.title")
    body = ev("document.body.innerText.slice(0,200)")
    print("title:", title)
    print("body:", repr(body)[:280])
    if body and ("Sign out" in body or "Account details" in body or "just_logged_in" in (title or "")):
        print("LOGIN_OK")
    else:
        print("LOGIN_STATE_UNKNOWN")
    return 0

if __name__ == "__main__":
    sys.exit(main())
