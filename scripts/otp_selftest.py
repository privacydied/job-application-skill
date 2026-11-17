#!/usr/bin/env python3
"""otp_selftest.py — end-to-end check that ATS email-code retrieval works.

Sends a synthetic Greenhouse-shaped verification email from the applicant's own
mailbox to itself, reads it back with the sanctioned fetch_verification_code.get_code(),
checks the extracted code, then deletes the synthetic email. Prints no secrets.
Requires the `imap...` row in ats-credentials.csv to be a working IMAP account whose
SMTP server accepts the same credential (Gmail app password works for both).
"""
import os
import random
import smtplib
import string
import sys
from email.message import EmailMessage

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for sub in ("scripts", os.path.join("sites", "_common", "scripts")):
    sys.path.insert(0, os.path.join(ROOT, sub))
import email_ingest as ei  # noqa: E402
import fetch_verification_code as vcode  # noqa: E402


def main():
    addr, pw, host = ei._creds()
    code = "V" + "".join(random.choice(string.ascii_uppercase + string.digits) for _ in range(7))
    marker = "hermes-otp-selftest"
    msg = EmailMessage()
    msg["From"] = addr
    msg["To"] = addr
    msg["Subject"] = f"Security code for your application to {marker}"
    msg.set_content(
        f"A verification code was sent to {addr}.\n"
        "Copy and paste this code into the security code field on your application: " + code + "\n"
    )

    with smtplib.SMTP(host.replace("imap.", "smtp."), 587, timeout=30) as smtp:
        smtp.starttls()
        smtp.login(addr, pw)
        smtp.send_message(msg)
    print("TEST_EMAIL_SENT")

    got = vcode.get_code(sender="any", minutes=10, digits=8, wait_s=90, poll_s=5, company=marker)
    print("CODE_EXTRACTED=" + str(bool(got)))
    print("MATCH=" + str(got == code))

    M = ei._connect()
    M.select("INBOX")
    typ, data = M.search(None, f'SUBJECT "{marker}"')
    for num in (data[0].split() if typ == "OK" and data and data[0] else []):
        M.store(num, "+FLAGS", "\\Deleted")
    M.expunge()
    M.logout()
    print("TEST_EMAIL_DELETED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
