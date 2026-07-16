#!/usr/bin/env python3
"""Batch LinkedIn Easy Apply driver — volume path for a 100-application run.

Reads a queue file (one posting per line:  TAG|Role|Company|URL ) and, for each,
drives the Easy Apply modal end-to-end:
  nav -> open -> dismiss-save -> walk steps (auto-answer known screeners) ->
  upload base resume -> submit -> confirm "Application sent" -> screenshot proof ->
  log Applied (--proof) via log-application.py.

Why this exists: the 100-target run proved that sourcing LinkedIn WITH f_AL=true
(Easy Apply only) plus this driver is the fastest automatable path — Easy Apply is
login-free and uses Jane's LinkedIn profile, whereas "Apply" redirects to a heavier
external ATS per posting. This script encodes the four pitfalls that ate turns on
the first attempt (see references/easyapply-batch-pitfalls.md):
  * sponsorship / authorised-to-work / willing-to-relocate / notice ARE RADIOS, not
    text fields — easyapply.py fill() matches labelOf(el).includes(want) and the
    input's label often omits the trailing "Required", so passing the full state
    label fails with NO_FIELD. Answer them with `easyapply.py radio`, falling back
    to `fill` only if the radio isn't found.
  * after `submit`, the modal shows a SPINNER for several seconds; reading state()
    immediately returns the REVIEW step, not "sent". Poll state() for ~15s for
    "Application sent" before declaring success — otherwise the app silently isn't
    logged.
  * camofox tabs die mid-run (HTTP 404). Self-heal with cfx.ensure_tab() and RETRY
    the SAME posting (do not skip it) — but first check the tracker so an already
    Applied row isn't double-submitted.
  * a resume uploaded in a previous session PERSISTS; re-upload uploads/base-resume.pdf
    on the Resume step and confirm via the Review step.

Usage:
  CFX_KEY=... CFX_TAB=... python3 scripts/easyapply_batch.py <queue.txt>
Queue line:  EA|Product Designer|Acme|https://www.linkedin.com/jobs/view/123456789/
The script updates the ambient tab via cfx.set_tab() after any self-heal (no file
write needed within one run).
"""
import sys, os, time, json, subprocess, re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                       # skill root (sites/..)
sys.path.insert(0, os.path.join(ROOT, "_common", "scripts"))
import cfx

QUEUE = sys.argv[1] if len(sys.argv) > 1 else "/tmp/ea_queue.txt"
RESUME = "/uploads/base-resume.pdf"
TRACKER = os.path.join(ROOT, "application-tracker.csv")

# Known screener answers. Keys are lowercased SUBSTRINGS of the question text.
# RADIO_KEYS are answered with `easyapply.py radio` first (fallback to fill).
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


def alive_tab():
    try:
        cfx.current_url()
        return True
    except Exception:
        return False


def heal_and_nav(url, tries=3):
    """Open (or reuse) a live tab and navigate, self-healing 404/500 by reopening."""
    for _ in range(tries):
        if not alive_tab():
            t = cfx.set_tab(cfx.ensure_tab(persist=False))
        try:
            cfx.navigate(url)
            return True
        except Exception as e:
            if "404" in str(e) or "500" in str(e):
                t = cfx.set_tab(cfx.ensure_tab(persist=False))
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
            time.sleep(1.5)
            ea("next"); time.sleep(2)
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
        st = state()
        if "sent" in ((st.get("step", "") or "") + (st.get("header", "") or "")).lower():
            sent = True; break
    if not sent:
        try:
            txt = cfx.evaluate("(document.body.innerText||'').toLowerCase()")
            if "your application was sent" in txt or "applied" in txt:
                sent = True
        except Exception:
            pass

    slug = re.sub(r"[^a-z0-9]+", "-", (company + "-" + role).lower()).strip("-")
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
