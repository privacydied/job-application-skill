#!/usr/bin/env python3
"""sf_apply.py — SAP SuccessFactors (career55.sapsf.eu) application driver.

⛔ WHY THIS IS ONE UNINTERRUPTED SCRIPT (2026-08-16, learned the expensive way).
The SAP session expires FAST. Driving this form interactively — fill a few fields, stop to
inspect, fill a few more — killed the session mid-application, and the symptoms lie:

  * picklists keep reporting aria-expanded=true but their aria-owns container never renders,
  * real keystrokes stop landing,
  * nothing says "expired" until you press Save.

~10 turns were spent diagnosing a "widget quirk" that was a dead session. So the whole
application runs in ONE pass here: sign in → fill → upload → submit, no pauses for analysis.

⛔ THE CV UPLOAD (the other expensive lesson). There is NO input[type=file] in the DOM — not in
shadow roots, not in the raw HTML. It is created LAZILY, and only by a trusted click on the
PLUS-SIGN GLYPH:

    span#<n>:_attachIcon   (role=button)      <-- the real control
    div#<n>:_attachLabel   ("Upload a CV")    <-- text only; clicking it does nothing

After that click the input exists as input[name="fileData1"] and the ordinary
/tabs/<tab>/upload endpoint sets it. No Playwright filechooser hook is needed — an earlier
diagnosis claimed otherwise and was wrong.

WIDGET MAP (SuccessFactors renders NO native <select>):
  text      input#<n>:_txtFld           — label-addressable, use atsform.fill
  picklist  input#<n>:_input role=combobox + button#<n>:_selectButton
            — atsform.combobox_pick's option-click rung drives these

USAGE:
  CFX_KEY=… CFX_TAB=… python3 sites/successfactors/scripts/sf_apply.py <config.json> [--submit]

Exit: 0 applied · 1 needs a human (unanswerable required field) · 2 config/nav error
      · 5 filled but not submitted (no --submit) · 11 off-location/excluded
"""
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
# sites/<board>/scripts -> sites/<board> -> sites -> skill root (THREE levels).
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))
sys.path.insert(0, os.path.join(_ROOT, "sites", "_common", "scripts"))
import cfx        # noqa: E402
import atsform    # noqa: E402
import precheck   # noqa: E402


def _ev(js):
    return cfx.evaluate(js)


def _credential(site_prefix):
    """Look the account up in the gitignored ats-credentials.csv by site prefix."""
    import csv  # noqa: PLC0415
    path = os.path.join(_ROOT, "ats-credentials.csv")
    if not site_prefix or not os.path.exists(path):
        return None
    for row in csv.DictReader(open(path, encoding="utf-8")):
        if (row.get("site") or "").startswith(site_prefix):
            return {"email": row.get("email") or "", "password": row.get("password") or ""}
    return None


def _resolve_fill(cfg):
    """Form-label -> value, with the applicant's REAL values read at runtime.

    ⛔ THE CONFIG MUST NOT CARRY PII (AGENTS.md §PII, config-routing model). runcfg/*.json is
    TRACKED, so a `fill` block holding a real name / phone / street / postcode would commit the
    applicant's address to a public repo — and check-no-pii.sh scans only ALREADY-tracked files,
    so it cannot warn you before the first `git add`. `fill_from_defaults` therefore maps a form
    label to a KEY in the gitignored sites/_common/apply-defaults.json, never to a value.
    `fill` stays for genuinely non-personal literals (e.g. a salary sentence)."""
    out = dict(cfg.get("fill") or {})
    mapping = cfg.get("fill_from_defaults") or {}
    if mapping:
        defaults = (json.load(open(os.path.join(_ROOT, "sites", "_common",
                                                "apply-defaults.json"))) or {}).get("fill", {})
        for label, key in mapping.items():
            if defaults.get(key) is not None:
                out[label] = defaults[key]
    return out


def _sign_in(email, password):
    """Sign in on the SF login page. Returns True once past it."""
    if "Sign In" not in (_ev("document.title") or ""):
        return True
    atsform.fill("Email Address", email, quiet_notfound=True)
    _ev("(()=>{const p=document.querySelector('#password'); if(!p) return 0;"
        "const s=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;"
        "s.call(p, " + json.dumps(password) + ");"
        "p.dispatchEvent(new Event('input',{bubbles:true}));"
        "p.dispatchEvent(new Event('change',{bubbles:true})); return p.value.length;})()")
    _ev("(()=>{const b=[...document.querySelectorAll('input[type=submit],button,a')]"
        ".find(e=>/sign in/i.test(e.value||e.innerText||'')); if(b) b.click(); return 1;})()")
    time.sleep(8)
    return "Sign In" not in (_ev("document.title") or "")


def _session_alive():
    """A dead SAP session is the #1 cause of 'the widget stopped working'. Check it CHEAPLY
    and OFTEN rather than re-diagnosing widget behaviour."""
    return "expired" not in (_ev("document.title") or "").lower()


def _cv_present(path):
    """Is the CV already attached? SF keeps documents on the CANDIDATE PROFILE, so a re-drive
    finds last run's file still there. Checking the whole page for the filename (rather than a
    narrow '* CV …' window, which the confirmed state pushes the name out of) avoids re-uploading
    — and avoids reporting CV_UPLOAD_FAIL for a CV that is present and confirmed."""
    stem = os.path.basename(path).rsplit(".", 1)[0].lower()
    body = (_ev("document.body?document.body.innerText:''") or "").lower()
    return stem in body and "download document" in body


def _upload_cv(path):
    """Click the plus-sign glyph to force SF to create its file input, then upload."""
    if _cv_present(path):
        print("OK= CV already attached to the candidate profile — skipping upload")
        return ""
    icon = _ev("(()=>{const s=[...document.querySelectorAll('span,div')]"
               ".find(e=>/addAttachments/.test((e.className||'').toString()));"
               "return s?s.id:'';})()")
    if not icon:
        return "no attach icon"
    cfx.click_selector(f'span[id="{icon}"]')
    time.sleep(4)
    got = _ev("(()=>{const f=document.querySelector('input[name=\"fileData1\"]');"
              "return f?'yes':'no';})()")
    if got != "yes":
        return "file input never appeared after clicking the plus glyph"
    cfx.post(f"/tabs/{cfx._tab()}/upload",
             {"userId": cfx._uid(), "selector": 'input[name="fileData1"]', "path": path})
    for _ in range(12):
        time.sleep(3)
        txt = _ev("(()=>{const t=document.body.innerText||'';"
                  "return (t.match(/\\* CV.{0,90}/)||[''])[0];})()") or ""
        if _cv_present(path):
            return ""
    return "CV chip never confirmed"


def _expand(js_label):
    _ev("(()=>{const b=[...document.querySelectorAll('button,a,span,div')]"
        ".find(e=>/expand all sections/i.test((e.innerText||'').trim()));"
        "if(b) b.click(); return 1;})()")
    time.sleep(5)


def main():
    cfg = json.load(open(sys.argv[1]))
    do_submit = "--submit" in sys.argv
    blk = precheck.drive_block(location=cfg.get("location"), url=cfg.get("url"),
                               company=cfg.get("company"), title=cfg.get("role"))
    if blk:
        print(f"OFF_LOCATION {cfg.get('company')} | {cfg.get('role')} — {blk}")
        return 11

    # Resume on a tab already signed in and sitting on the form (avoids re-navigating, which
    # spawns a new tab and can outrun the session).
    if cfg.get("already_on_form"):
        pass
    elif not cfx.goto(cfg["url"]).get("ok"):
        print("NAV_FAIL")
        return 2
    if not cfg.get("already_on_form"):
        time.sleep(3)
        _ev("(()=>{const a=[...document.querySelectorAll('a,button')]"
            ".find(e=>/apply now/i.test(e.innerText||'')); if(a) a.click(); return 1;})()")
        time.sleep(8)

    # ⛔ CREDENTIALS ARE READ AT RUNTIME, NEVER STORED IN THE CONFIG (config-routing model,
    # AGENTS.md §PII). runcfg/*.json is TRACKED — embedding an email+password there would put a
    # live secret one `git add` away from a public repo, and check-no-pii.sh only scans files
    # that are ALREADY tracked, so it would not catch the untracked file beforehand. The config
    # carries a LOOKUP KEY; the secret stays in the gitignored ats-credentials.csv.
    cred = _credential(cfg.get("credential_site", ""))
    if not cred:
        print(f"NO_CREDENTIAL for {cfg.get('credential_site')!r} in ats-credentials.csv")
        return 2
    if not _sign_in(cred["email"], cred["password"]):
        print("SIGNIN_FAIL")
        return 2
    time.sleep(4)
    _expand(None)

    d = _resolve_fill(cfg)
    for label, value in d.items():
        atsform.fill(label, value, quiet_notfound=True)

    err = _upload_cv(cfg.get("cv", "/uploads/base-resume.pdf"))
    if err:
        print(f"CV_UPLOAD_FAIL {err}")
        return 1
    if not _session_alive():
        print("SESSION_EXPIRED during upload — re-run; do not continue")
        return 1

    # Text fields re-render (and CLEAR) after the upload — refill before the picklists.
    for label, value in d.items():
        atsform.fill(label, value, quiet_notfound=True)

    # ⛔ DEMOGRAPHIC ANSWERS COME FROM THE GITIGNORED CONFIG, NEVER FROM THIS CONFIG FILE.
    # AGENTS.md §PII bans a demographic (gender / ethnicity / RELIGION / age band / …) in any
    # tracked file, and check-no-pii.sh explicitly CANNOT catch these: demographic words are
    # ordinary English, so the routing convention is the only defence. `picklists_from_applicant`
    # maps a form label to a KEY in apply-defaults.json -> applicant.
    picks = dict(cfg.get("picklists") or {})
    amap = cfg.get("picklists_from_applicant") or {}
    if amap:
        applicant = (json.load(open(os.path.join(_ROOT, "sites", "_common",
                                                 "apply-defaults.json"))) or {}).get("applicant", {})
        for label, key in amap.items():
            if applicant.get(key) is not None:
                picks[label] = applicant[key]

    for q, a in picks.items():
        try:
            atsform.combobox_pick(q, a)
        except Exception as e:  # noqa: BLE001
            print(f"  picklist {q[:40]!r}: {str(e)[:60]}")
        if not _session_alive():
            print("SESSION_EXPIRED mid-fill — re-run; do not continue")
            return 1

    if cfg.get("eeo"):
        try:
            atsform.fill_eeo()
        except Exception as e:  # noqa: BLE001
            print(f"  eeo: {str(e)[:60]}")

    errs = _ev("(()=>{const e=[...document.querySelectorAll('[role=alert],[class*=ValidationMsg]')]"
               ".filter(x=>x.offsetParent!==null).map(x=>(x.innerText||'').replace(/\\s+/g,' ').trim())"
               ".filter(Boolean); return JSON.stringify([...new Set(e)].slice(0,10));})()")
    print(f"VALIDATION: {errs}")
    if not do_submit:
        print("filled; not submitting (pass --submit).")
        return 5

    btn = _ev("(()=>{const b=[...document.querySelectorAll('span,button,input')]"
              ".find(e=>/^Apply$/i.test((e.value||e.innerText||'').trim()));"
              "return b?b.id:'';})()")
    if not btn:
        print("NO_APPLY_BUTTON")
        return 1
    cfx.click_selector(f'span[id="{btn}"]')
    time.sleep(12)
    if not _session_alive():
        print("SESSION_EXPIRED at submit — nothing was submitted")
        return 1
    body = _ev("document.body?document.body.innerText:''") or ""
    ok = any(k in body.lower() for k in ("thank you for applying", "application received",
                                         "successfully submitted", "your application has been"))
    slug = cfg.get("slug") or "sf-application"
    appdir = os.path.join(_ROOT, "applications", slug)
    os.makedirs(appdir, exist_ok=True)
    shot = os.path.join(appdir, "confirmation.png" if ok else "submit-attempt.png")
    cfx.shot(shot, full_page=True)
    print(("APPLIED_OK " if ok else "SUBMIT_NO_CONFIRM ") + f"proof={shot}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
