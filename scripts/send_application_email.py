#!/usr/bin/env python3
"""send_application_email.py - send an email-only job application over SMTP.

Creds come ONLY from the `imap...` row of ats-credentials.csv (email col = address and
login, password col = password). SMTP host is probed from that row's host: smtp./mail./apex,
port 465 (SSL) then 587 (STARTTLS). Nothing is hardcoded.

  python3 scripts/send_application_email.py --to jobs@out.land --subject "..." \
      --body-file applications/<slug>/cover-letter.md --attach applications/<slug>/resume.pdf \
      --proof applications/<slug>/confirmation.txt [--dry-run]

Exit 0 only if the SMTP server ACCEPTED the message. The proof file holds Message-ID,
headers, recipients and the server's accept result. A copy is appended to the IMAP Sent
folder when possible (best effort).
"""
import argparse
import csv
import os
import smtplib
import ssl
import sys
from datetime import datetime
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def creds():
    with open(os.path.join(ROOT, "ats-credentials.csv"), newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            site = (r.get("site") or "").strip()
            if site.lower().startswith("imap"):
                return (r["email"].strip(), r["password"].strip(), site.split(",")[0].strip())
    raise SystemExit("no imap row in ats-credentials.csv")


def hosts(imap_host):
    apex = imap_host[5:] if imap_host.startswith("imap.") else imap_host
    out = []
    for h in (imap_host.replace("imap.", "smtp.", 1), "mail." + apex, apex, imap_host):
        if h not in out:
            out.append(h)
    return out


def build(addr, a):
    m = EmailMessage()
    m["From"] = addr
    m["To"] = a.to
    if a.bcc:
        m["Bcc"] = a.bcc
    m["Subject"] = a.subject
    m["Date"] = formatdate(localtime=True)
    m["Message-ID"] = make_msgid(domain=addr.split("@")[1])
    with open(a.body_file, encoding="utf-8") as f:
        m.set_content(f.read())
    for p in a.attach:
        with open(p, "rb") as f:
            m.add_attachment(f.read(), maintype="application", subtype="pdf",
                             filename=a.attach_name if len(a.attach) == 1 and a.attach_name
                             else os.path.basename(p))
    return m


def _open(h, port):
    if port == 465:
        return smtplib.SMTP_SSL(h, 465, timeout=30, context=ssl.create_default_context())
    s = smtplib.SMTP(h, 587, timeout=30)
    s.starttls(context=ssl.create_default_context())
    return s


def smtp_send(msg, addr, pw, imap_host, rcpts):
    last = None
    for h in hosts(imap_host):
        for port in (465, 587):
            try:
                s = _open(h, port)
                s.login(addr, pw)
            except (OSError, smtplib.SMTPException) as e:
                last = f"{h}:{port} {type(e).__name__} {e}"
                continue
            refused = s.send_message(msg, to_addrs=rcpts)
            s.quit()
            return f"{h}:{port}", refused
    raise SystemExit(f"SMTP failed on all hosts; last: {last}")


def save_sent(msg, addr, pw, imap_host):
    import imaplib
    import time
    apex = imap_host[5:] if imap_host.startswith("imap.") else imap_host
    for h in (imap_host, apex):
        try:
            M = imaplib.IMAP4_SSL(h)
            M.login(addr, pw)
            for box in ("Sent", "INBOX.Sent", "Sent Items"):
                if M.append(box, "\\Seen", imaplib.Time2Internaldate(time.time()),
                            msg.as_bytes())[0] == "OK":
                    return box
        except (OSError, imaplib.IMAP4.error):
            continue
    return "not-saved"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--to", required=True)
    ap.add_argument("--bcc", default="")
    ap.add_argument("--subject", required=True)
    ap.add_argument("--body-file", required=True)
    ap.add_argument("--attach", action="append", default=[])
    ap.add_argument("--attach-name", default="")
    ap.add_argument("--proof", required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    addr, pw, imap_host = creds()
    msg = build(addr, a)
    if a.dry_run:
        print(msg.as_string()[:1500])
        return 0
    rcpts = [x for x in (a.to + "," + a.bcc).split(",") if x.strip()]
    via, refused = smtp_send(msg, addr, pw, imap_host, rcpts)
    if refused:
        raise SystemExit(f"recipients refused: {refused}")
    sent = save_sent(msg, addr, pw, imap_host)
    hdr = "".join(f"{k}: {v}\n" for k, v in msg.items())
    with open(a.proof, "w", encoding="utf-8") as f:
        f.write(f"Application sent - SMTP ACCEPTED via {via} at {datetime.now().isoformat()} (no recipients refused)\n"
                f"Sent-folder copy: {sent}\nAttachments: {[os.path.basename(p) for p in a.attach]}\n\n{hdr}")
    print("SENT", msg["Message-ID"], "via", via, "sent-copy:", sent)
    return 0


if __name__ == "__main__":
    sys.exit(main())
