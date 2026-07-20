#!/usr/bin/env python3
"""
email_ingest.py — turn inbound email into two feeds: sourcing rows (job-alert emails) and
outcome events (response emails) (feature-roadmap N.5, and the substrate for M.3).

WHY THIS EXISTS. Every board has native job-alert emails, and every application generates
response emails (rejection / assessment invite / interview / offer). Both are PUSH data that
arrives at publication/decision time with ZERO browser cost and ZERO cooldown burn — a
sourcing + outcome channel the funnel wasn't using. This connects to a dedicated mailbox over
IMAP and:
  * `alerts`    — parses job-alert emails into the shared feed-shaped posting rows, so board
                  alerts flow into the SAME merge → precheck → queue funnel as any feed
                  (including boards whose search UIs are hostile — the alert email sidesteps
                  their anti-bot surface entirely).
  * `responses` — classifies response emails into {status, company} outcome events for M.3
                  (outcomes.py), which updates the tracker + conversion stats.

CREDENTIALS. IMAP creds come from ats-credentials.csv (the sanctioned source — never env),
row whose `site` starts with `imap` (e.g. `imap.gmail.com`): email col = address, password
col = an app-password (Gmail requires an app password with IMAP enabled). No row → exits 2
naming the row to add, exactly like the key-gated feeds. No PII is ever hardcoded here.

  Add a row to ats-credentials.csv:  imap.gmail.com,<address>,<app-password>
  (label a Gmail filter to move board alerts + ATS responses into a folder, and point --folder
   at it; default INBOX.)

Pure classification (subject/body → posting rows / outcome status) is unit-testable without a
mailbox: `alerts_from_html(html)` and `classify_response(subject, body)` take strings.

CLI:
  email_ingest.py alerts   [--folder INBOX] [--days 3]   # feed-shaped JSON to stdout
  email_ingest.py responses [--folder INBOX] [--days 14] # outcome events JSON to stdout
  email_ingest.py test                                    # connect + count, no parsing
"""
import json
import os
import re
import sys
from datetime import datetime, timedelta

_here = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_here)
sys.path.insert(0, os.path.join(_ROOT, "sites", "_common", "scripts"))
import httpfeed  # noqa: E402  (creds_row + clean/strip_html)

# board host -> source token (for feed-shaped rows). Only boards the funnel can act on.
BOARD_HOSTS = {
    "linkedin.com/jobs": "linkedin", "reed.co.uk": "reed", "indeed.com": "indeed",
    "adzuna.co.uk": "adzuna", "cv-library.co.uk": "cvlibrary", "totaljobs.com": "totaljobs",
    "welcometothejungle": "wttj", "the-dots.com": "thedots", "remotive.com": "remotive",
    "jobicy.com": "jobicy", "escapethecity.org": "escapecity", "civilservicejobs": "csj",
    "greenhouse.io": "greenhouse", "lever.co": "lever", "ashbyhq.com": "ashby",
}

_HREF_RE = re.compile(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.I | re.S)

# Response classification: order matters — check the most decisive first.
_RESPONSE_RULES = [
    ("Offer", r"\b(pleased to offer|offer of employment|job offer|we would like to offer)\b"),
    ("Interview", r"\b(invit\w* (you )?to (an? )?interview|invitation to interview|"
                  r"interview (invitation|for|with)|schedule (an?|your) interview|"
                  r"book (an?|your) interview|first[- ]stage interview|"
                  r"phone screen|screening call|meet the team)\b"),
    ("Assessment", r"\b(assessment|online test|coding challenge|take[- ]home|"
                   r"complete (a|the) (task|exercise)|hackerrank|testgorilla|codility)\b"),
    ("Rejected", r"\b(unfortunately|not (be )?(progress|moving forward)|"
                 r"decided not to|will not be taking your application|"
                 r"other candidates|unsuccessful on this occasion|not to proceed|"
                 r"regret to inform)\b"),
]


def _creds():
    email, pw = httpfeed.creds_row("imap")
    return email, pw


def alerts_from_html(html, from_addr=""):
    """Pure: a job-alert email's HTML body -> feed-shaped posting rows. Extracts anchors
    pointing at known board hosts, using the anchor text as the title. Dedup by canonical id
    happens downstream in merge_sources — this just harvests candidates."""
    rows = []
    for href, text in _HREF_RE.findall(html or ""):
        url = href.strip()
        low = url.lower()
        source = next((tok for host, tok in BOARD_HOSTS.items() if host in low), None)
        if not source:
            continue
        title = httpfeed.clean(text)
        if not title or len(title) < 3 or title.lower() in ("view job", "apply", "see more"):
            title = ""
        rows.append({
            "id": "", "url": url.split("?")[0] if "utm_" in low else url,
            "title": title, "company": "", "location": "",
            "source": f"email:{source}", "board": source,
        })
    return rows


def classify_response(subject, body):
    """Pure: (subject, body) -> outcome status string or None. Interview/offer/assessment/
    rejection, checked most-decisive-first. Company is extracted best-effort by the caller."""
    blob = f"{subject or ''}\n{body or ''}".lower()
    for status, pat in _RESPONSE_RULES:
        if re.search(pat, blob):
            return status
    return None


# ── IMAP layer (only reached at runtime; the pure fns above are what tests target) ──────
def _creds():
    # Read the IMAP row directly so we get (email, password, host) — the host lives in
    # the `site` column (e.g. "imap.example.com"), not derivable from the address.
    import csv as _csv
    path = os.path.join(_ROOT, "ats-credentials.csv")
    with open(path, newline="", encoding="utf-8") as f:
        for row in _csv.DictReader(f):
            if (row.get("site") or "").strip().lower().startswith("imap"):
                site = (row.get("site") or "").strip()
                host = site.split(":", 1)[-1].split(",", 1)[0].strip()
                if host.startswith("imap."):
                    host = host[len("imap."):]
                return (row.get("email") or "").strip(), \
                       (row.get("password") or "").strip(), host
    raise RuntimeError("no IMAP row (site starts with 'imap') in ats-credentials.csv")


def _connect():
    import imaplib
    email, pw, host = _creds()
    if not email or not pw or not host:
        raise RuntimeError(
            "no IMAP creds — add a row to ats-credentials.csv whose `site` starts "
            "with `imap` (e.g. `imap.example.com,<address>,<app-password>`).")
    M = imaplib.IMAP4_SSL(host)
    M.login(email, pw)
    return M


def _fetch(folder, days):
    """[(subject, from, html_or_text)] for messages in `folder` since `days` ago."""
    import email as emaillib
    from email.header import decode_header
    M = _connect()
    out = []
    try:
        M.select(folder, readonly=True)
        since = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
        typ, data = M.search(None, f'(SINCE {since})')
        if typ != "OK":
            return out
        for num in (data[0].split() if data and data[0] else []):
            typ, msgdata = M.fetch(num, "(RFC822)")
            if typ != "OK" or not msgdata or not msgdata[0]:
                continue
            msg = emaillib.message_from_bytes(msgdata[0][1])

            def _dh(v):
                if not v:
                    return ""
                parts = decode_header(v)
                return "".join(p.decode(enc or "utf-8", "replace") if isinstance(p, bytes) else p
                               for p, enc in parts)
            subject = _dh(msg.get("Subject"))
            frm = _dh(msg.get("From"))
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    ct = part.get_content_type()
                    if ct in ("text/html", "text/plain"):
                        try:
                            body += part.get_payload(decode=True).decode("utf-8", "replace")
                        except (AttributeError, UnicodeError, TypeError):
                            continue
            else:
                try:
                    body = msg.get_payload(decode=True).decode("utf-8", "replace")
                except (AttributeError, UnicodeError, TypeError):
                    body = str(msg.get_payload())
            out.append((subject, frm, body))
    finally:
        try:
            M.logout()
        except Exception:  # noqa: BLE001
            pass
    return out


def _company_from(subject, frm):
    """Best-effort employer name from an 'X at Company' subject or the From display name."""
    m = re.search(r"\bat\s+([A-Z][\w&.\- ]{1,40})", subject or "")
    if m:
        return m.group(1).strip(" .")
    m = re.match(r'\s*"?([^"<]+?)"?\s*<', frm or "")
    return m.group(1).strip() if m else ""


def main():
    argv = sys.argv[1:]
    cmd = argv[0] if argv else ""

    def opt(flag, default):
        return argv[argv.index(flag) + 1] if flag in argv and argv.index(flag) + 1 < len(argv) else default

    folder = opt("--folder", "INBOX")

    if cmd == "test":
        try:
            msgs = _fetch(folder, int(opt("--days", "1")))
            print(f"connected OK; {len(msgs)} message(s) in {folder} in the window.")
            return 0
        except Exception as e:  # noqa: BLE001
            print(f"FAIL: {e}", file=sys.stderr)
            return 2
    if cmd == "alerts":
        try:
            msgs = _fetch(folder, int(opt("--days", "3")))
        except Exception as e:  # noqa: BLE001
            print("[]"); print(f"ERROR: {e}", file=sys.stderr); return 2
        rows = []
        for subject, frm, body in msgs:
            rows.extend(alerts_from_html(body, frm))
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        print(f"\n{len(rows)} job link(s) harvested from {len(msgs)} alert email(s). Pipe "
              f"into merge_sources + precheck like any feed.", file=sys.stderr)
        return 0 if rows else 1
    if cmd == "responses":
        try:
            msgs = _fetch(folder, int(opt("--days", "14")))
        except Exception as e:  # noqa: BLE001
            print("[]"); print(f"ERROR: {e}", file=sys.stderr); return 2
        events = []
        for subject, frm, body in msgs:
            status = classify_response(subject, httpfeed.strip_html(body))
            if status:
                events.append({"status": status, "company": _company_from(subject, frm),
                               "subject": subject[:120]})
        print(json.dumps(events, ensure_ascii=False, indent=2))
        print(f"\n{len(events)} outcome event(s) from {len(msgs)} email(s). Feed to "
              f"outcomes.py apply.", file=sys.stderr)
        return 0
    print("Usage: email_ingest.py alerts|responses|test [--folder INBOX] [--days N]",
          file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
