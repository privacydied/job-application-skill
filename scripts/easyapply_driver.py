#!/usr/bin/env python3
"""Hardened LinkedIn Easy Apply batch driver — volume path for big-target runs.

Reads a queue file (one posting per line:  TAG|Role|Company|URL ) and, for each,
drives the Easy Apply modal end-to-end:
  nav -> open -> dismiss-save -> walk steps (auto-answer known screeners) ->
  upload base resume -> submit -> poll "Application sent" -> screenshot proof ->
  log Applied (--proof) via log-application.py.

This is a drop-in improvement over the original easyapply_batch.py. It adds three
lessons from the 2026-07-14 100-target run that the original driver lacked:

  * BAIL on BLOCKED_UNANSWERED_REQUIRED. The original looped forever when a 2nd
    unanswerable screener appeared (e.g. Persistent Systems: sponsorship OK, but
    "Do you have Native-level French/Italian proficiency?" had no answer). This
    driver detects the blocked signal and exits NEEDS_HUMAN for that posting
    instead of spinning until timeout.
  * PERSIST the healed tab id back to .jobenv.run. camofox tabs die mid-batch
    (404/500); the driver self-heals with cfx.ensure_tab() but the ORIGINAL
    easyapply_batch.py only updated os.environ in-process, so the next shell
    call (or a later re-run) read a STALE CFX_TAB from .jobenv.run and died.
    This driver rewrites the CFX_TAB line in .jobenv.run after every heal.
  * RE-UPLOAD resume on the Resume step (persistence across sessions) and capture
    a confirmation screenshot as --proof before logging.

Queue line:  EA|Product Designer|Acme|https://www.linkedin.com/jobs/view/123456789/
Usage:
  source .jobenv.run && python3 scripts/easyapply_driver.py <queue.txt>
"""
import sys
import os
import time
import json
import subprocess
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                       # skill root
sys.path.insert(0, os.path.join(ROOT, "_common", "scripts"))
import cfx  # noqa: E402

QUEUE = sys.argv[1] if len(sys.argv) > 1 else "/tmp/ea_queue.txt"
RESUME = "/uploads/base-resume.pdf"
TRACKER = os.path.join(ROOT, "application-tracker.csv")
ENV_FILE = os.path.join(ROOT, ".jobenv.run")

# Known screener answers. Keys are lowercased SUBSTRINGS of the question text.
RADIO_KEYS = ("sponsorship", "authorized to work", "right to work",
              "willing to relocate", "notice period", "available to start",
              "require sponsorship", "visa sponsorship", "currently employed")
KNOWN = {
    "sponsorship": "No",
    "require sponsorship": "No",
    "visa sponsorship": "No",
    "authorized to work": "Yes",
    "right to work": "Yes",
    "willing to relocate": "No",
    "notice period": "Immediately",
    "available to start": "Immediately",
    "currently employed": "Yes",
    "current location": "London, United Kingdom",
    "location": "London, United Kingdom",
    "city": "London",
    "years of experience": "5",
    "email alerts": "No",
}


def ea(*a):
    r = subprocess.run([sys.executable, os.path.join(ROOT, "sites", "linkedin", "scripts", "easyapply.py"), *a],
                       capture_output=True, text=True)
    return r.stdout.strip()


def state():
    try:
        return json.loads(ea("state"))
    except Exception:
        return {}


def persist_tab(tid):
    """Rewrite CFX_TAB in .jobenv.run so the NEXT shell call uses the live tab."""
    try:
        s = open(ENV_FILE, encoding="utf-8").read()
        s = re.sub(r"export CFX_TAB='[^']*'", f"export CFX_TAB='{tid}'", s)
        open(ENV_FILE, "w", encoding="utf-8").write(s)
    except Exception as e:
        print(f"  (warn) could not persist tab {tid}: {e}")


def heal_and_nav(url, tries=3):
    for _ in range(tries):
        try:
            cfx.current_url()
        except Exception:
            pass
        try:
            cfx.navigate(url)
            return True
        except Exception as e:
            if "404" in str(e) or "500" in str(e):
                try:
                    t = cfx.set_tab(cfx.ensure_tab(persist=False))
                    persist_tab(t)
                except Exception:
                    pass
                time.sleep(3)
                continue
            raise
    return False


def already_done(company, role):
    try:
        txt = open(TRACKER, encoding="utf-8", errors="replace").read()
    except FileNotFoundError:
        return False
    for line in txt.splitlines():
        if company in line and role in line and ",Applied" in line:
            return True
    return False


def drive(job_id, company, role):
    url = f"https://www.linkedin.com/jobs/view/{job_id}/"
    if already_done(company, role):
        print(f"  SKIP_DUP {company} {role} (already Applied)"); return "dup"
    if not heal_and_nav(url):
        print(f"  TAB_DEAD {company} {role}"); return "dead"
    time.sleep(11)
    print("  open:", ea("open"))
    ea("dismiss-save")

    for _ in range(15):
        st = state()
        step = st.get("step", "") or ""
        labels = st.get("labels", []) or []
        if "Additional Questions" in step:
            answered = False
            for lab in labels:
                low = (lab or "").lower()
                for k, v in KNOWN.items():
                    if k in low:
                        if k in RADIO_KEYS:
                            r = ea("radio", k, v)
                            if not r.startswith("OK"):
                                r = ea("fill", k, v)
                        else:
                            r = ea("fill", k, v)
                        print(f"    ans [{k}]={v} -> {r[:30]}")
                        answered = True
                        break
            if not answered:
                print(f"  UNKNOWN_SCREENER: {labels}")
                return "human"
            r = ea("next")
            # If still blocked on an unanswered required question, bail — don't loop.
            if "BLOCKED_UNANSWERED_REQUIRED" in r:
                q = st.get("errors") or [lbl for lbl in labels if lbl not in KNOWN]
                print(f"  BLOCKED_REQUIRED: {q}")
                return "human"
            time.sleep(2)
            continue
        if "Resume" in step:
            print("  upload:", ea("upload", RESUME))
            ea("next"); time.sleep(2)
            continue
        if "Review" in step:
            print("  REVIEW reached"); break
        ea("next"); time.sleep(2)

    print("  submit:", ea("submit"))
    sent = False
    for _ in range(8):           # up to ~16s polling the spinner
        time.sleep(2)
        try:
            st = state()
        except Exception:
            heal_and_nav(url); continue
        # WORD-BOUNDARY "sent" ("Application sent") — a bare substring test also matched
        # "conSENT"/"preSENT"/"repreSENTed", which could log a false Applied for a modal
        # that was still on a consent step and never actually submitted.
        if re.search(r"\bsent\b", (st.get("step", "") or "") + " " + (st.get("header", "") or ""), re.I):
            sent = True; break
        # fallback: job page button now reads "Applied"
        try:
            btns = cfx.evaluate("""(()=>[...document.querySelectorAll('button')].map(x=>x.innerText.trim()).filter(t=>/applied/i.test(t)))()""")
            if btns:
                sent = True; break
        except Exception:
            pass

    slug = re.sub(r"[^a-z0-9]+", "-", (company + "-" + role).lower()).strip("-")
    base_slug = slug
    n = 2
    while os.path.exists(os.path.join(ROOT, "applications", slug)):
        slug = f"{base_slug}-{n}"; n += 1
    appdir = os.path.join(ROOT, "applications", slug)
    os.makedirs(appdir, exist_ok=True)
    proof = os.path.join(appdir, "confirmation.png")
    subprocess.run(["bash", os.path.join(ROOT, "_common", "scripts", "cfx.sh"), "shot", proof],
                   capture_output=True, text=True)
    if sent:
        log = subprocess.run([sys.executable,
            os.path.join(ROOT, "_common", "scripts", "log-application.py"),
            company, role, "LinkedIn Easy Apply", url, "Applied",
            "--proof", proof, "--notes", "Easy Apply auto-submitted; base-resume.pdf"],
            capture_output=True, text=True)
        print(f"  LOG: {(log.stdout or log.stderr).strip()}")
        return "applied"
    print(f"  UNCONFIRMED (no 'sent' state) — proof at {proof}, verify manually")
    return "unconfirmed"


def main():
    n = {"applied": 0, "dup": 0, "human": 0, "dead": 0, "unconfirmed": 0}
    with open(QUEUE) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 4:
                continue
            _, role, company, url = parts[0], parts[1], parts[2], parts[3]
            jid = re.search(r"/view/(\d+)", url)
            jid = jid.group(1) if jid else url
            print(f"### {company} :: {role} (jid={jid})")
            res = drive(jid, company, role)
            n[res] = n.get(res, 0) + 1
            time.sleep(2)
    print(f"DONE applied={n['applied']} dup={n['dup']} human={n['human']} dead={n['dead']} unconfirmed={n['unconfirmed']}")


if __name__ == "__main__":
    main()
