#!/usr/bin/env python3
"""eFinancialCareers in-platform apply driver (modal flow).

Verified live 2026-11-17 on a peer host. Flow: job page -> "Apply now" -> optional
"Candidate Assessment" step (one free-text field) -> CV step (either "Select a CV" dropdown of
saved CVs, or "Upload CV" Filestack panel) -> optional cover letter -> contact names ->
"Apply for this role" (NOT "Apply and become searchable", which is a profile opt-in) ->
"Your application has been sent successfully!" / "You have already applied".

Usage:
    python3 sites/efinancialcareers.co.uk/scripts/apply.py <url> "<Company>" "<Role>" <pdf-basename> [cover.md]

The PDF must already be staged in uploads/ (bare basename). Names and the salary answer come
from the gitignored sites/_common/apply-defaults.json `fill` block ("First Name"/"Last Name",
"Salary expectation") — nothing personal is hardcoded; a missing value aborts rather than
submitting a placeholder.
"""
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
COMMON = os.path.abspath(os.path.join(HERE, "..", "..", "_common", "scripts"))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, COMMON)
import cfx  # noqa: E402

LOGAPP = os.path.join(COMMON, "log-application.py")
DEFAULTS = json.load(open(os.path.join(ROOT, "sites", "_common", "apply-defaults.json")))
FILL = DEFAULTS.get("fill", {})


def _fill(*keys):
    for k in keys:
        if FILL.get(k):
            return FILL[k]
    return None


def ev(expr):
    return cfx.evaluate(expr)


def click_text(sel, text, exact=True):
    """Dispatched MouseEvent click (a bare .click() does not fire React handlers here)."""
    op = "===" if exact else ".includes"
    return ev("(function(){var e=[...document.querySelectorAll(%r)].find(x=>(x.innerText||'').trim()%s%r);"
              "if(!e)return 'miss';e.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true,view:window}));"
              "return 'ok';})()" % (sel, op, text))


def setval(tag, el_id, value):
    proto = "HTMLInputElement" if tag == "input" else "HTMLTextAreaElement"
    return ev("(function(){var e=document.getElementById(%r);if(!e)return 'miss';"
              "var s=Object.getOwnPropertyDescriptor(%s.prototype,'value').set;s.call(e,%r);"
              "e.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText',data:e.value}));"
              "e.dispatchEvent(new Event('change',{bubbles:true}));return 'ok:'+e.value.length;})()"
              % (el_id, proto, value))


def dialogs(n):
    return ev("(function(){var ds=[...document.querySelectorAll('[role=dialog]')];"
              "return ds.map(x=>x.innerText).join(' || ').slice(0,%d)})()" % n) or ""


def apply(url, company, role, pdf, cover):
    first, last = _fill("First Name", "FirstName"), _fill("Last Name", "Surname")
    if not (first and last):
        return "NO_NAME_IN_APPLY_DEFAULTS"
    cfx.goto(url)
    time.sleep(4)
    if click_text("a,button", "Apply now") != "ok":
        return "NO_APPLY_BUTTON"
    time.sleep(3)
    if "Candidate Assessment" in dialogs(1500):
        salary = _fill("Salary expectation", "Expected salary")
        if not salary:
            return "ASSESSMENT_NEEDS_SALARY_IN_APPLY_DEFAULTS"
        ids = ev("[...document.querySelectorAll('[role=dialog] input[type=text]')].map(e=>e.id).slice(0,3).join('|')")
        ids = [i for i in (ids or "").split("|") if i]
        if not ids:
            return "ASSESSMENT_NO_FIELD"
        setval("input", ids[0], salary)
        time.sleep(0.5)
        if click_text("[role=dialog] button", "Continue") != "ok":
            return "ASSESSMENT_NO_CONTINUE"
        time.sleep(3)
    d = dialogs(1200)
    base = os.path.basename(pdf)
    if "Select a CV" in d:
        if click_text("[role=dialog] button", "Select a CV", False) != "ok":
            return "NO_CV_BUTTON"
        time.sleep(1)
        r = ev("(function(){var e=[...document.querySelectorAll('li[role=menuitem]')].find("
               "x=>(x.textContent||'').includes(%r));if(!e)return 'miss';"
               "e.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true,view:window}));"
               "return 'ok';})()" % base)
        if r != "ok":
            return "CV_NOT_IN_DROPDOWN"
        time.sleep(2)
    elif "Upload CV" in d:
        if click_text("[role=dialog] button", "Upload CV", False) != "ok":
            return "NO_UPLOAD_BUTTON"
        time.sleep(1)
        if not ev("Boolean(document.getElementById('fsp-fileUpload'))"):
            return "NO_FILE_INPUT"
        try:
            cfx.post(f"/tabs/{cfx._tab()}/upload", {"userId": cfx._uid(),
                     "selector": "#fsp-fileUpload", "path": cfx.upload_path(base)})
        except Exception as e:  # noqa: BLE001
            return "UPLOAD_ERR " + str(e)[:80]
        time.sleep(1)
        ev("(function(){var e=document.querySelector('[data-e2e=upload]');if(e)e.click();return 'ok';})()")
        time.sleep(4)
    if base not in (ev("document.body.innerText") or "") and "Uploaded on" not in (ev("document.body.innerText") or ""):
        return "CV_NOT_SELECTED"
    if cover and ev("Boolean(document.getElementById('coverLetterContent'))"):
        if click_text("[role=dialog] button", "Write Cover Letter") == "ok":
            time.sleep(1.5)
        setval("textarea", "coverLetterContent", cover)
        time.sleep(0.5)
    setval("input", "firstname", first)
    setval("input", "lastname", last)
    time.sleep(1)
    if ev("document.getElementById('firstname')&&document.getElementById('firstname').value") != first:
        return "NAME_NOT_SET"
    if click_text("[role=dialog] button", "Apply for this role") != "ok":
        return "NO_SUBMIT"
    time.sleep(7)
    body = (ev("document.body.innerText") or "").lower()
    if "sent successfully" not in body and "already applied" not in body and "application submitted" not in body:
        return "SUBMIT_NO_CONFIRM"
    return "APPLIED"


def main():
    if len(sys.argv) < 5:
        print(__doc__)
        return 2
    url, company, role, pdf = sys.argv[1:5]
    cover = open(sys.argv[5]).read().strip() if len(sys.argv) > 5 else ""
    verdict = apply(url, company, role, pdf, cover)
    print(verdict)
    if verdict != "APPLIED":
        return 1
    slug = re.sub(r"[^a-z0-9]+", "-", (company + "-" + role).lower()).strip("-")[:70]
    d = os.path.join(ROOT, "applications", slug)
    os.makedirs(d, exist_ok=True)
    proof = os.path.join(d, "confirmation.png")
    cfx.shot(proof)
    open(os.path.join(d, "confirmation.txt"), "w").write(
        f"Applied via eFinancialCareers in-platform apply; confirmation shown ({time.ctime()}).\n")
    subprocess.run([sys.executable, LOGAPP, company, role, "eFinancialCareers", url,
                    "Applied", "--proof", proof], cwd=ROOT, capture_output=True, text=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
