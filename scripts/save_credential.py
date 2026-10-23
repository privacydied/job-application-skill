#!/usr/bin/env python3
"""Append a new ATS account to the gitignored ats-credentials.csv.

Usage: python3 scripts/save_credential.py <site> <email>
Generates a strong password, appends `site,email,password,date`, and prints the
password on stdout so the caller can type it into the signup form. Refuses to
add a second row for the same site+email.
"""
import csv
import datetime
import secrets
import string
import sys
from pathlib import Path

CSV = Path(__file__).resolve().parent.parent / "ats-credentials.csv"


def make_password(n=20):
    pools = [string.ascii_lowercase, string.ascii_uppercase, string.digits, "!#%*+-_"]
    chars = [secrets.choice(p) for p in pools]
    chars += [secrets.choice("".join(pools)) for _ in range(n - len(chars))]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


def main():
    if len(sys.argv) != 3:
        sys.exit("usage: save_credential.py <site> <email>")
    site, email = sys.argv[1], sys.argv[2]
    with CSV.open(newline="") as f:
        for row in csv.DictReader(f):
            if row["site"] == site and row["email"] == email:
                sys.exit(f"exists: {site}")
    pw = make_password()
    with CSV.open("a", newline="") as f:
        csv.writer(f).writerow([site, email, pw, datetime.date.today().isoformat()])
    print(pw)


if __name__ == "__main__":
    main()
