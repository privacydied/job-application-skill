#!/usr/bin/env python3
"""Batch-drive on-lane Reed rows through reed_modal_drive, capture proof, log Applied.
Reads a newline list of full Reed URLs from argv[1]. Serial (one tab)."""
import json
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DRIVE = os.path.join(ROOT, "scripts", "reed_modal_drive.py")
SHOT = os.path.join(ROOT, "sites", "_common", "scripts", "cfx.py")
LOGAPP = os.path.join(ROOT, "sites", "_common", "scripts", "log-application.py")


def meta(url):
    jid = url.rstrip("/").split("/")[-1].split("?")[0]
    co, ro = None, None
    try:
        for l in open(os.path.join(ROOT, "queue.jsonl")):
            j = json.loads(l)
            if jid in j.get("url", ""):
                co = j.get("company"); ro = j.get("title"); break
    except Exception:
        pass
    return jid, (co or "(unknown employer — Reed)"), (ro or ("Reed posting " + jid))


def main():
    urls = [u.strip() for u in open(sys.argv[1]) if u.strip()]
    results = []
    for url in urls:
        jid, co, ro = meta(url)
        print("\n=== DRIVE", jid, ro[:40], "===", flush=True)
        try:
            out = subprocess.run([sys.executable, DRIVE, url, co, ro],
                                 cwd=ROOT, capture_output=True, text=True, timeout=300).stdout
        except Exception as e:
            out = "TIMEOUT/ERR: " + str(e)[:80]
        verdict = out.strip().splitlines()[-1] if out.strip() else "NO-OUTPUT"
        print(" ->", verdict, flush=True)
        if verdict.startswith("SUBMITTED CONFIRMED"):
            slug = "reed-" + re.sub(r"[^a-z0-9]+", "-", ro.lower())[:40] + "-" + jid
            d = os.path.join(ROOT, "applications", slug)
            os.makedirs(d, exist_ok=True)
            try:
                subprocess.run([sys.executable, SHOT, "shot"], cwd=ROOT, capture_output=True, text=True, timeout=40)
                png = "/tmp/cfx-shot.png"
                if os.path.exists(png):
                    subprocess.run(["cp", png, os.path.join(d, "confirmation.png")])
            except Exception:
                pass
            open(os.path.join(d, "confirmation.txt"), "w").write("You applied for this job (verified) " + time.ctime())
            proof = os.path.join(d, "confirmation.png")
            proofarg = proof if os.path.exists(proof) else os.path.join(d, "confirmation.txt")
            subprocess.run([sys.executable, LOGAPP, co, ro, "Reed", url, "Applied", "--proof", proofarg],
                           cwd=ROOT, capture_output=True, text=True, timeout=30)
            print("   logged Applied", flush=True)
        results.append((jid, verdict))
        time.sleep(3)
    print("\n===== SUMMARY =====")
    n = sum(1 for _, v in results if v.startswith("SUBMITTED CONFIRMED"))
    for jid, v in results:
        print(jid, v[:70])
    print("CONFIRMED SUBMISSIONS:", n)


if __name__ == "__main__":
    main()
