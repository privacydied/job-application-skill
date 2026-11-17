#!/usr/bin/env python3
"""setup_gmail_imap.py — record a Gmail IMAP app-password row in ats-credentials.csv.

Run this YOURSELF in a terminal (the app password is read with getpass, never echoed
and never passed through chat). It removes any existing `imap...` row and writes one:

    imap.gmail.com,<address>,<16-char app password>

Gmail setup needed first: 2-Step Verification ON, IMAP enabled
(Gmail > Settings > Forwarding and POP/IMAP), then generate an App password
(Google Account > Security > 2-Step Verification > App passwords).
"""
import csv
import getpass
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "sites", "_common", "scripts"))
import fsutil  # noqa: E402

CREDS = os.path.join(ROOT, "ats-credentials.csv")


def main():
    address = input("Gmail address: ").strip()
    if "@" not in address or "," in address:
        sys.exit("Invalid address.")
    app_password = getpass.getpass("Gmail app password (16 chars, hidden): ").strip()
    if len(app_password) != 16:
        sys.exit("App passwords are 16 characters; nothing written.")

    rows = []
    with open(CREDS, newline="", encoding="utf-8") as f:
        for row in csv.reader(f):
            if not row:
                continue
            if row[0].lower().startswith("imap"):
                continue
            rows.append(row)
    rows.append(["imap.gmail.com", address, app_password])

    def _write(f):
        w = csv.writer(f, lineterminator="\n")
        w.writerows(rows)

    with fsutil.file_lock(CREDS):
        fsutil.atomic_write(CREDS, _write)
    print(f"Wrote imap.gmail.com row for {address}. Password was not displayed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
