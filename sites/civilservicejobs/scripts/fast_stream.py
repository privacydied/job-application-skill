#!/usr/bin/env python3
"""
fast_stream.py — Civil Service Fast Stream portal driver (apply-civil-service-fast-stream
.service.gov.uk). Separate system from CSJ's TAL eforms: the "Apply at advertiser's site"
button on a Fast Stream advert lands here.

Stages (each is a separate call; each stops for the applicant where the process needs him):
  signup   create the account (done 2026-10-10) (route: Civil Service Fast Stream)   -> this module
  verify   enter the 7-character activation code (mailbox via fetch_verification_code)
  signin   log in with the stored credential (session is lost after a save)
  apply    scheme preferences + background questions                -> not yet built
  tests    two timed online tests (work-based scenarios, case study) -> HARD STOP,
           applicant only. Never driven by this module.
  submit   final submit                                              -> applicant only

Usage:
  CFX_TAB=<tab> python3 fast_stream.py signup [--dry-run]
  CFX_TAB=<tab> python3 fast_stream.py status

Credentials come from ats-credentials.csv (gitignored). The password is never printed.
"""
import argparse
import csv
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "sites" / "_common" / "scripts"))
sys.path.insert(0, str(ROOT / "scripts"))

SITE = "apply-civil-service-fast-stream.service.gov.uk"
SIGNUP_URL = "https://www.apply-civil-service-fast-stream.service.gov.uk/fset-fast-stream/signup"
CREDS_CSV = ROOT / "ats-credentials.csv"
ROUTE_OPTION = "Civil Service Fast Stream"
TERMS_LABEL = "I accept the terms and conditions"
STATEMENTS_LABEL = "I understand and agree with the Civil Service Fast Stream statements"


def load_credential(email=None):
    """Return (email, password) for SITE. Password never leaves this function unprinted."""
    with CREDS_CSV.open(newline="") as f:
        for row in csv.DictReader(f):
            if row["site"] == SITE and (email is None or row["email"] == email):
                return row["email"], row["password"]
    raise SystemExit(f"no ats-credentials.csv row for {SITE}")


def signup_details(first, last, email, password):
    """Field spec for the sign-up page. Labels match the live page text."""
    return {
        "first": ("First name", first),
        "last": ("Last name", last),
        "email": ("Email", email),
        "email_confirm": ("Confirm your email", email),
        "password": ("Enter your password", password),
        "password_confirm": ("Confirm your password", password),
    }


def _fill_text_fields(spec, atsform):
    for key, (label, value) in spec.items():
        if key in ("first", "last", "email", "email_confirm", "password", "password_confirm"):
            atsform.fill(label, value)


def _fill_route_and_terms(atsform):
    atsform.set_radio("Which route do you want to choose?", ROUTE_OPTION)
    atsform.set_checkbox(TERMS_LABEL, "on")
    atsform.set_checkbox(STATEMENTS_LABEL, "on")


def fill_signup(spec, atsform):
    _fill_text_fields(spec, atsform)
    _fill_route_and_terms(atsform)


def _page_text():
    import cfx
    return cfx.evaluate("document.body.innerText.slice(0, 1500)")


def _signup_errors():
    import cfx
    return cfx.evaluate(
        "[...document.querySelectorAll('.govuk-error-summary, .govuk-error-message')]"
        ".map(e => e.innerText.trim()).join(' | ')")


def run_signup(first, last, email, dry_run=False):
    import atsform
    import cfx
    email, password = load_credential(email)
    spec = signup_details(first, last, email, password)
    if dry_run:
        print(json.dumps({"stage": "signup", "dry_run": True, "email": email,
                          "fields": sorted(spec)}))
        return 0
    cfx.goto(SIGNUP_URL)
    fill_signup(spec, atsform)
    atsform.click_button("Create account")
    cfx.poll("document.readyState", timeout=20)
    errs = _signup_errors()
    print(json.dumps({"stage": "signup", "url": cfx.current_url(),
                      "errors": errs, "page": _page_text()[:600]}))
    return 1 if errs else 0


def fetch_activation_code(wait_s=150):
    """Read the 7-character activation code from the applicant mailbox (never written to disk)."""
    import fetch_verification_code as fvc
    return fvc.get_code(sender="any", digits=7, company="fast stream", wait_s=wait_s, want="code")


def run_verify(wait_s=150):
    import atsform
    import cfx
    code = fetch_activation_code(wait_s)
    if not code:
        print(json.dumps({"stage": "verify", "error": "no activation code arrived"}))
        return 2
    atsform.fill("Enter activation code", code)
    atsform.click_button("Activate account")
    cfx.poll("document.readyState", timeout=20)
    print(json.dumps({"stage": "verify", "url": cfx.current_url(), "page": _page_text()[:400]}))
    return 0


def run_signin(email=None):
    """Sign in with the stored credential. Used when the session is lost mid-application."""
    import atsform
    import cfx
    email, password = load_credential(email)
    atsform.fill("Email", email)
    atsform.fill("Password", password)
    atsform.click_button("Sign in")
    cfx.poll("document.readyState", timeout=20)
    print(json.dumps({"stage": "signin", "url": cfx.current_url(), "page": _page_text()[:300]}))
    return 1 if "signin" in cfx.current_url() else 0


PERSONAL_TEXT = {
    "firstName": "Jane", "lastName": "Doe", "preferredName": "Jane",
    "dateOfBirth.day": "3", "dateOfBirth.month": "3", "dateOfBirth.year": "1995",
    "address.line1": "Flat 3, The Forge Building", "address.line2": "22 Wharf Road",
    "address.line3": "London", "postCode": "[postcode]", "phone": "07804605448",
}
SET_NATIVE_JS = """(([n, v]) => {
  const e = document.querySelector('[name="' + n + '"]');
  const s = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
  s.call(e, v); e.dispatchEvent(new Event('input', {bubbles: true}));
  e.dispatchEvent(new Event('change', {bubbles: true})); return e.value.length;
})"""
CIVIL_SERVANT_JS = """(() => {
  const r = document.querySelector('input[name="civilServiceExperienceDetails.applicable"][value="true"]');
  r.click(); return r.checked;
})()"""


def fill_personal_details(cfx):
    """Set every personal-details text field natively, then the civil-servant radio."""
    import json
    for name, value in PERSONAL_TEXT.items():
        cfx.evaluate("(%s)(%s)" % (SET_NATIVE_JS, json.dumps([name, value])))
    return cfx.evaluate(CIVIL_SERVANT_JS)


def run_details(civil_servant_yes=True):
    """Fill and save the Add personal details page in one pass (session can drop on save)."""
    import cfx
    cfx.goto("https://www.apply-civil-service-fast-stream.service.gov.uk/fset-fast-stream/application/details/continue")
    cfx.poll("document.readyState", timeout=10)
    if not civil_servant_yes:
        raise SystemExit("civil_servant_yes=False not implemented: answer is recorded only as Yes")
    radio = fill_personal_details(cfx)
    cfx.evaluate("(() => { document.querySelector('input[name=firstName]').form.requestSubmit(); return 1; })()")
    cfx.poll("document.readyState", timeout=20)
    print(json.dumps({"stage": "details", "radio_yes": radio, "url": cfx.current_url(),
                      "page": _page_text()[:300]}))
    return 0


def run_status():
    import cfx
    print(json.dumps({"url": cfx.current_url(), "page": _page_text()[:600]}))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("signup")
    s.add_argument("--first", default="Jane")
    s.add_argument("--last", default="Doe")
    s.add_argument("--email", default="you@example.com")
    s.add_argument("--dry-run", action="store_true")
    sub.add_parser("verify")
    sub.add_parser("signin")
    sub.add_parser("details")
    sub.add_parser("status")
    a = p.parse_args(argv)
    if a.cmd == "signup":
        return run_signup(a.first, a.last, a.email, a.dry_run)
    if a.cmd == "verify":
        return run_verify()
    if a.cmd == "signin":
        return run_signin()
    if a.cmd == "details":
        return run_details()
    return run_status()


if __name__ == "__main__":
    sys.exit(main())
