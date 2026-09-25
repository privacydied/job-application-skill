#!/usr/bin/env python3
"""
email_ingest.py — turn inbound email into two feeds: sourcing rows (job-alert emails) and
outcome events (response emails) (feature-roadmap N.5, and the substrate for M.3).

WHY THIS EXISTS. Every board has native job-alert emails, and every application generates
response emails (rejection / assessment invite / interview / offer / plain receipt). All of
that is PUSH data that arrives at publication/decision time with ZERO browser cost and ZERO
cooldown burn — a sourcing + outcome + filing channel the funnel wasn't using. This connects
to a dedicated mailbox over IMAP and:
  * `alerts`    — parses job-alert emails into the shared feed-shaped posting rows, so board
                  alerts flow into the SAME merge → precheck → queue funnel as any feed
                  (including boards whose search UIs are hostile — the alert email sidesteps
                  their anti-bot surface entirely).
  * `responses` — classifies response emails into {status, company} outcome events for M.3
                  (outcomes.py), which updates the tracker + conversion stats.
  * `file`      — moves genuine "thank you for applying" / "we have received your
                  application" RECEIPT emails (distinct from a status decision — see
                  `is_application_confirmation()`) out of the inbox into a dedicated mailbox
                  folder (default `INBOX.Job Applications`), so the inbox stops filling up
                  with these while `responses` keeps seeing decision emails untouched.

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
  email_ingest.py file    [--src INBOX] [--dest "INBOX.Job Applications"] [--days 14]
                          [--dry-run]
                          # moves genuine "thank you for applying" / application-receipt
                          # confirmation emails (NOT rejections/interviews/offers — those
                          # stay in --src for classify_response/outcomes.py to see) from
                          # --src into --dest via IMAP MOVE (COPY + STORE Deleted + EXPUNGE
                          # fallback for servers without MOVE). Idempotent: only touches
                          # --src, so a second run just finds nothing left to move.
  email_ingest.py test     [--folder INBOX]                # connect + count, no parsing
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
                  # NB: no bare "interview with" — a post-interview REJECTION ("thank you
                  # for taking the time to interview with us. Unfortunately…") contains that
                  # phrase, and Interview is checked before Rejected, so it would mask the
                  # rejection. The decisive invite signals (invitation/schedule/book/…) stay.
                  r"interview (invitation|for)|schedule (an?|your) interview|"
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


# ── Application-CONFIRMATION classification (distinct from classify_response above) ─────
# A "thank you for applying" / "we have received your application" receipt is NOT a status
# outcome (no interview/offer/rejection decision has happened yet) — classify_response()
# correctly returns None for it. This is a second, narrower pure classifier for exactly
# that receipt class, so `file` can move it without touching outcomes.py's rejection/
# interview/offer detection or its own confirmation logic elsewhere in the funnel.
_CONFIRMATION_RE = re.compile(
    # ⛔ "thank you for your <anything>" is too loose on its own — live-mailbox probing found
    # it firing on "Thank you for your patience", "…your time", "…your interest" inside status
    # updates, withdrawal notices and even a missed-interview reschedule email, none of which
    # are receipts. Anchor the "thank you" phrasing specifically to "applying"/"application" so
    # a generic pleasantry elsewhere in the body can't trigger it.
    r"\b(thank you for (applying|your application|your recent application)|"
    r"thanks for applying|"
    r"we('| ha)ve received your application|application received|"
    r"application(?:s)? confirmation|your application (?:has been |was )?(?:received|submitted)|"
    r"we('| ha)ve completed your application|"
    r"you'?ve successfully applied|successfully submitted your application|"
    r"confirming (?:receipt of )?your application)\b", re.I)

# A confirmation-shaped subject that is ACTUALLY a later-stage outcome, a withdrawal, or an
# unrelated request must not be filed as a plain receipt — e.g. "Your application outcome for
# the role of X", "Application withdrawn - …", a missed-interview reschedule, or a sift/stage
# progress update that happens to thank the candidate along the way. Decisive non-receipt
# language always wins; checked first and excluded from `is_application_confirmation`.
_OUTCOME_OVERRIDE_RE = re.compile(
    r"\b(application outcome|regarding your application|update on your application|"
    r"following your application|application withdrawn|sift progression|"
    r"missed interview|reschedule|interview request|extra info needed|"
    r"application update)\b", re.I)


def is_application_confirmation(subject, body):
    """Pure: (subject, body) -> True if this looks like a genuine "your application was
    received" receipt — the class of email the user wants auto-filed into a Job Applications
    folder. Deliberately narrower than classify_response: a real interview/offer/rejection
    email is routed by classify_response instead (checked first here so a decision email
    that also happens to open with "thank you for applying" is never miscategorised as a
    plain receipt and hidden from outcomes.py)."""
    subj = subject or ""
    blob = f"{subj}\n{body or ''}"
    if classify_response(subj, body):
        return False
    if _OUTCOME_OVERRIDE_RE.search(subj):
        return False
    return bool(_CONFIRMATION_RE.search(blob))


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
                # Return the host AS WRITTEN — the old code UNCONDITIONALLY stripped a leading
                # "imap.", which turns the documented `imap.gmail.com` into `gmail.com` (does NOT
                # answer IMAP). _connect() now handles the apex-only case with a fallback instead.
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
    # Try the host AS WRITTEN first (so `imap.gmail.com` reaches Gmail), then fall back to the
    # apex (strip a leading `imap.`) for providers whose IMAP answers on the bare domain. A
    # DNS/socket failure moves to the next host; a LOGIN failure (bad password) is not a host
    # problem, so it propagates from the first host that actually connects.
    hosts = [host]
    if host.startswith("imap."):
        hosts.append(host[len("imap."):])
    last = None
    for h in hosts:
        try:
            M = imaplib.IMAP4_SSL(h)
        except OSError as e:
            last = e
            continue
        M.login(email, pw)
        return M
    raise RuntimeError(f"IMAP connect failed for {hosts!r}: {last}")


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


def _parse_headers_and_body(raw_bytes):
    """RFC822 bytes -> (subject, from, body_text). Shared by _fetch and _move_confirmations
    so header-decoding/body-extraction logic lives in exactly one place."""
    import email as emaillib
    from email.header import decode_header
    msg = emaillib.message_from_bytes(raw_bytes)

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
            if part.get_content_type() in ("text/html", "text/plain"):
                try:
                    body += part.get_payload(decode=True).decode("utf-8", "replace")
                except (AttributeError, UnicodeError, TypeError):
                    continue
    else:
        try:
            body = msg.get_payload(decode=True).decode("utf-8", "replace")
        except (AttributeError, UnicodeError, TypeError):
            body = str(msg.get_payload())
    return subject, frm, body


def _imap_move(M, folder, uid, dest):
    """MOVE one message (by UID) from the selected `folder` into `dest`. Uses the IMAP MOVE
    extension (RFC 6851) when the server advertises it; falls back to COPY + STORE \\Deleted +
    EXPUNGE for servers that don't (e.g. older Dovecot/Exchange builds) — same net effect,
    just two round trips instead of one. `dest` is created first if it doesn't exist yet, so
    a fresh mailbox setup doesn't need a manual "create the folder" step."""
    try:
        M.create(dest)  # no-op (server error, ignored) if it already exists
    except Exception:  # noqa: BLE001
        pass
    caps = getattr(M, "capabilities", ()) or ()
    if any(c.upper() == "MOVE" for c in caps):
        typ, _ = M.uid("MOVE", uid, dest)
        return typ == "OK"
    typ, _ = M.uid("COPY", uid, dest)
    if typ != "OK":
        return False
    typ, _ = M.uid("STORE", uid, "+FLAGS", r"(\Deleted)")
    if typ != "OK":
        return False
    M.expunge()
    return True


def file_confirmations(src="INBOX", dest="INBOX.Job Applications", days=14, dry_run=False):
    """Move genuine application-confirmation emails ("thank you for applying", "we have
    received your application", …) from `src` into `dest` over IMAP. Returns the list of
    {subject, from} dicts that were (or, in dry-run, would be) moved. Rejection/interview/
    offer/assessment emails are left untouched — classify_response() already owns those for
    outcomes.py, and is_application_confirmation() explicitly excludes anything it recognises
    as a decision so a single email is never double-handled by two different consumers.

    Side effects (unless dry_run): moves matching messages in `src`. Never deletes anything
    outright — MOVE/COPY+EXPUNGE relocates the message, it doesn't discard it."""
    M = _connect()
    moved = []
    try:
        M.select(src, readonly=False)
        since = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
        typ, data = M.uid("SEARCH", None, f"(SINCE {since})")
        uids = data[0].split() if (typ == "OK" and data and data[0]) else []
        for uid in uids:
            typ, msgdata = M.uid("FETCH", uid, "(RFC822)")
            if typ != "OK" or not msgdata or not msgdata[0] or not isinstance(msgdata[0], tuple):
                continue
            subject, frm, body = _parse_headers_and_body(msgdata[0][1])
            if not is_application_confirmation(subject, httpfeed.strip_html(body)):
                continue
            moved.append({"subject": subject, "from": frm})
            if not dry_run:
                _imap_move(M, src, uid, dest)
    finally:
        try:
            M.logout()
        except Exception:  # noqa: BLE001
            pass
    return moved


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
    if cmd == "file":
        src = opt("--src", "INBOX")
        dest = opt("--dest", "INBOX.Job Applications")
        dry = "--dry-run" in argv
        try:
            moved = file_confirmations(src=src, dest=dest,
                                        days=int(opt("--days", "14")), dry_run=dry)
        except Exception as e:  # noqa: BLE001
            print("[]"); print(f"ERROR: {e}", file=sys.stderr); return 2
        print(json.dumps(moved, ensure_ascii=False, indent=2))
        verb = "would move" if dry else "moved"
        print(f"\n{verb} {len(moved)} application-confirmation email(s) from {src!r} "
              f"to {dest!r}.", file=sys.stderr)
        return 0
    print("Usage: email_ingest.py alerts|responses|file|test "
          "[--folder|--src INBOX] [--dest \"INBOX.Job Applications\"] [--days N] [--dry-run]",
          file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
