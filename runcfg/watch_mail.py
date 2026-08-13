#!/usr/bin/env python3
"""Watch the IMAP mailbox for new Greenhouse code emails for ~6 min.
Logs subject + snippet so we can tell if a verification code was emailed
during a live gh_apply submit."""
import sys, time, csv, imaplib, email
sys.path.insert(0, 'scripts')
import email_ingest as ei
import os
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

seen = set()
end = time.time() + 360
print("watching mailbox for greenhouse code emails...", flush=True)
while time.time() < end:
    try:
        conn = ei._connect()
        conn.select('INBOX')
        since = (time.time() - 400)
        import datetime
        d = (datetime.datetime.utcnow() - datetime.timedelta(minutes=7)).strftime('%d-%b-%Y')
        typ, data = conn.search(None, 'SINCE', d)
        for num in data[0].split():
            typ, msgd = conn.fetch(num, '(RFC822)')
            m = email.message_from_bytes(msgd[0][1])
            frm = m.get('From','')
            subj = m.get('Subject','')
            mid = m.get('Message-ID','')
            if mid in seen: continue
            if 'greenhouse' in (frm+subj).lower() or 'verification' in subj.lower() or 'security code' in (m.get('Subject','')+'').lower():
                # grab snippet
                body=''
                if m.is_multipart():
                    for p in m.walk():
                        if p.get_content_type()=='text/plain':
                            try: body=p.get_payload(decode=True).decode('utf-8','replace')
                            except: pass
                            break
                else:
                    try: body=m.get_payload(decode=True).decode('utf-8','replace')
                    except: pass
                import re
                code=re.findall(r'\b([A-Za-z0-9]{6,8})\b', body)
                seen.add(mid)
                print(f"NEW: from={frm[:50]} subj={subj[:60]} code_candidates={code[:5]}", flush=True)
        conn.logout()
    except Exception as e:
        print("WATCH_ERR", type(e).__name__, str(e)[:120], flush=True)
    time.sleep(15)
print("watch done", flush=True)
