#!/usr/bin/env python3
"""fetch_verification_code.py — the ONE primitive that pulls an ATS email-verification code
from the applicant mailbox, so an account-less Greenhouse / applicationtrack.com submission
can be completed. Importable `get_code()` + a CLI; gh_apply and the applicationtrack drivers
call THIS — no per-driver copy.

WHY THIS EXISTS. Greenhouse (and MI5/applicationtrack.com) gate submission behind a short
code emailed to the applicant. The form fills 100% but submit is rejected until the code is
entered. The mailbox is reachable over IMAP; email_ingest.py already connects. See
references/greenhouse-verification-gate.md.

CREDS — read at runtime, NEVER hardcoded here (keeps this file PII-free): an `imap...` row in
ats-credentials.csv (email col = address, password col = an app-password), consumed via
email_ingest._connect(). No row -> get_code() returns '' with a WARN; the CLI exits 2.

USAGE:
  python3 scripts/fetch_verification_code.py [--sender greenhouse] [--minutes 20]
                                             [--digits N] [--company Acme] [--wait 90]
  prints the most-recent matching code, or exits 1 (NO_CODE) / 2 (no IMAP creds).

IMPORT (the driver path — poll after a submit that surfaced the code prompt):
  import fetch_verification_code as vcode
  code = vcode.get_code(sender="greenhouse-mail.io", company="Acme", digits=8, wait_s=90)

Side-effect-free: only READS the mailbox (SELECT readonly).
"""
import email as emaillib
import os
import re
import sys
import time
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
sys.path.insert(0, os.path.join(_ROOT, "sites", "_common", "scripts"))
sys.path.insert(0, os.path.join(_ROOT, "scripts"))

import email_ingest as ei  # noqa: E402  — reuse _connect() (IMAP creds + login)

# tokens the length-regex would grab that are never a real code
_STOP = {"security", "submit", "resubmit", "greenhouse", "application", "verify",
         "verification", "confirm", "continue", "street"}


def _body_text(msg):
    """Plain text of an email body (HTML stripped)."""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() in ("text/plain", "text/html"):
                try:
                    body += part.get_payload(decode=True).decode("utf-8", "replace")
                except Exception:  # noqa: BLE001
                    continue
    else:
        try:
            body = msg.get_payload(decode=True).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            body = str(msg.get_payload())
    try:
        import httpfeed
        return httpfeed.strip_html(body)
    except Exception:  # noqa: BLE001
        return body


def _extract(text, digits=None):
    """The verification code — prefer one right after 'code'/'security code'/'code is', else
    the first plausible token, skipping English stop-words. `digits` pins the exact length
    (Greenhouse = 8); None accepts 6-8 alnum."""
    span = ("{%d}" % digits) if digits else "{6,8}"
    near = re.search(r"(?:verification code|security code|code is|your code|\bcode\b)"
                     r"[^A-Za-z0-9]{0,15}([A-Za-z0-9]" + span + r")", text, re.I)
    if near and _plausible_code(near.group(1)):
        return near.group(1)
    for c in re.findall(r"\b([A-Za-z0-9]" + span + r")\b", text):
        if _plausible_code(c):
            return c
    return ""


def _plausible_code(tok):
    """⛔ SHAPE TEST, NOT A WORDLIST (2026-08-15). The fallback scan used to accept any
    length-matching token that wasn't in a hand-maintained `_STOP` list, which cannot cover
    English: probing the live mailbox for an 8-char Greenhouse code returned the WORD
    **"applying"**. That is worse than finding nothing — gh_apply would have typed it into the
    security-code box as if it were the code.

    Real codes are machine-generated (Greenhouse's look like `vC3N4JMk`), so test the SHAPE:
    a token qualifies only if it contains a digit, or mixes upper and lower case. Every
    ordinary English word in a marketing email fails both, with no wordlist to maintain."""
    if not tok:
        return False
    if tok.lower() in _STOP:                       # keep the explicit denylist as a floor
        return False
    has_digit = any(c.isdigit() for c in tok)
    mixed_case = any(c.islower() for c in tok) and any(c.isupper() for c in tok)
    return has_digit or mixed_case


def _within_window(date_hdr, minutes, now=None):
    """True if the email's Date header is within the last `minutes` — the REAL freshness
    window. The IMAP SINCE term is only date-granular (whole calendar day), so without this
    a stale same-day code (e.g. a prior apply to the same company, or an earlier code that
    has since expired) is the newest match and gets returned instead of waiting for the fresh
    one. Fail-open: a missing/unparseable Date returns True (never over-filter a real code)."""
    if not date_hdr:
        return True
    try:
        dt = parsedate_to_datetime(date_hdr)
    except (TypeError, ValueError):
        return True
    if dt is None:
        return True
    if dt.tzinfo is None:               # naive Date -> interpret as local
        dt = dt.astimezone()
    now = now or datetime.now().astimezone()
    # CLOCK-SKEW TOLERANCE (2026-07-25): the NAS host clock lags wall time by
    # ~20h, so a freshly-emailed code's Date header reads as being in the FUTURE
    # relative to the NAS `now`. The plain `dt >= now - window` check then rejects
    # a brand-new code (it looks "too new"), causing get_code() to return '' and
    # the Greenhouse driver to log CODE_MISSING even though the code is in the
    # mailbox. Fail-open: if the email appears newer than `now` at all, it is by
    # definition fresh under skew — accept it. (SINCE already restricts to today,
    # and get_code picks the freshest matching email, so this can't return a
    # stale code that a newer one would've superseded.)
    return dt >= now - timedelta(minutes=minutes) or dt > now


# Corporate-suffix noise that appears in tracker company names but rarely in the employer's
# own transactional email, plus words too generic to identify anybody on their own.
_COMPANY_NOISE = {
    "agency", "group", "ltd", "limited", "llc", "inc", "plc", "co", "com", "corp",
    "holdings", "labs", "technologies", "technology", "solutions", "services", "systems",
    "digital", "global", "international", "the", "and", "uk", "us",
}


def _company_tokens(comp):
    """The identifying tokens of a company name, longest first. 'OLIVER Agency' -> ['oliver'];
    'Blockchain.com' -> ['blockchain']. Empty when the name is all noise, in which case the
    caller falls back to the full-string test rather than matching everything."""
    parts = [p for p in re.split(r"[^a-z0-9]+", comp.lower()) if p]
    toks = [p for p in parts if len(p) >= 4 and p not in _COMPANY_NOISE]
    return sorted(toks, key=len, reverse=True)


def _company_matches(comp, subj, body_low):
    """True if this email plausibly belongs to `comp`: the full name appears, or its most
    distinctive token does. See the call site for why the full-string test alone was wrong."""
    if comp in subj or comp in body_low:
        return True
    toks = _company_tokens(comp)
    if not toks:
        return False
    lead = toks[0]
    return bool(re.search(r"(^|[^a-z0-9])" + re.escape(lead) + r"([^a-z0-9]|$)",
                          subj + " " + body_low))


def get_code(sender="greenhouse", minutes=20, digits=None, company=None,
             wait_s=0, poll_s=6):
    """Freshest verification code from the applicant mailbox (newest first), or ''.
      sender  : substring required in the From header ('any' = no sender filter).
      company : if set, also require it in the subject or body (disambiguates concurrent apps).
      digits  : exact code length (Greenhouse = 8); None = 6-8 alnum.
      wait_s  : >0 -> POLL until a code lands or wait_s elapses (the email lags the submit).
    Reads IMAP creds from ats-credentials.csv via email_ingest — no hardcoded address.
    Never raises; returns '' on any mailbox error (prints a WARN)."""
    comp, snd = (company or "").lower(), (sender or "").lower()
    deadline = time.time() + max(0, wait_s)
    while True:
        try:
            M = ei._connect()
        except Exception as e:  # noqa: BLE001
            print(f"  VCODE_CREDS_WARN {e}", file=sys.stderr)
            return ""
        try:
            M.select("INBOX", readonly=True)
            since = (datetime.now() - timedelta(minutes=minutes)).strftime("%d-%b-%Y")
            typ, data = M.search(None, f"(SINCE {since})")
            nums = data[0].split() if (typ == "OK" and data and data[0]) else []
            for num in reversed(nums):  # newest first
                typ, md = M.fetch(num, "(RFC822)")
                if typ != "OK" or not md or not md[0]:
                    continue
                msg = emaillib.message_from_bytes(md[0][1])
                # Enforce the real N-minute freshness window (SINCE is only date-granular),
                # so a stale same-day code isn't returned before the fresh email lands.
                if not _within_window(msg.get("Date"), minutes):
                    continue
                frm = (msg.get("From") or "").lower()
                subj = (msg.get("Subject") or "").lower()
                if snd != "any" and snd not in frm:
                    continue
                text = _body_text(msg)
                # COMPANY MATCH IS TOKEN-BASED (2026-08-15). Requiring the WHOLE tracker
                # company string to appear meant any suffix the employer doesn't use in its
                # own email killed the match: "OLIVER Agency" vs an email saying "OLIVER",
                # "Blockchain.com" vs "Blockchain". The code was sitting in the mailbox and
                # gh_apply still printed CODE_MISSING, then logged a fully-correct
                # application as Blocked — 7 of them in a single drain. Accept the full
                # string OR its most distinctive token. Still safely scoped: sender must be
                # Greenhouse and the mail must be inside the freshness window, and we take
                # the newest first.
                if comp and not _company_matches(comp, subj, text.lower()):
                    continue
                code = _extract(text, digits)
                if code:
                    return code
        finally:
            try:
                M.logout()
            except Exception:  # noqa: BLE001
                pass
        if time.time() >= deadline:
            return ""
        time.sleep(poll_s)


def main():
    argv = sys.argv[1:]

    def opt(flag, default):
        return next((argv[i + 1] for i, a in enumerate(argv) if a == flag and i + 1 < len(argv)), default)

    digits_s = opt("--digits", "")
    # distinguish "no IMAP creds" (exit 2) from "no code" (exit 1) for the CLI contract
    try:
        ei._connect().logout()
    except Exception as e:  # noqa: BLE001
        print(f"FAIL: {e}", file=sys.stderr)
        return 2
    code = get_code(sender=opt("--sender", "greenhouse"), minutes=int(opt("--minutes", "20")),
                    digits=int(digits_s) if digits_s.isdigit() else None,
                    company=opt("--company", None), wait_s=int(opt("--wait", "0")))
    if code:
        print(code)
        return 0
    print("NO_CODE", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
