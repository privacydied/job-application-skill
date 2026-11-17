#!/usr/bin/env python3
"""SmartRecruiters batch drive — `apply.py auto` per queue row, one fresh tab each.

Usage: python3 -u sites/smartrecruiters/scripts/batch.py <queue.jsonl> [--limit N] [--dry]

For every row with a jobs.smartrecruiters.com URL that is not already tracked it
  1. mints a FRESH tab (a tab reused after many shadow-DOM clicks wedges: every click then
     times out at 30 s and no dropdown can be read — verified live, Shawbrook 2026-11-17),
  2. runs `apply.py auto <url> --submit` (SR_COMPANY / SR_ROLE name the proof dir),
  3. logs `Applied` with the confirmation screenshot ONLY when the driver printed SUBMIT_OK
     and the proof file exists; rc 7 (unanswerable required question) is left unlogged so a
     human can finish it; anything else is reported, never logged as Applied,
  4. closes the tab.
One drive at a time (the browser tab is a serial resource).
"""
import json
import os
import re
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "sites", "_common", "scripts"))
import cfx  # noqa: E402

APPLY = os.path.join(ROOT, "sites", "smartrecruiters", "scripts", "apply.py")
LOG = os.path.join(ROOT, "sites", "_common", "scripts", "log-application.py")


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def _tracked(url, tracker):
    ids = re.findall(r"\d{6,}", url)
    return bool(ids) and ids[-1] in tracker


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 10**6
    dry = "--dry" in sys.argv
    with open(os.path.join(ROOT, "application-tracker.csv"), encoding="utf-8", errors="ignore") as f:
        tracker = f.read().lower()
    rows = []
    with open(sys.argv[1], encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if "smartrecruiters.com" in (r.get("url") or "") and not _tracked(r["url"], tracker):
                rows.append(r)
    print(f"{len(rows)} untracked SmartRecruiters rows")
    tally = {"applied": 0, "needs_human": 0, "failed": 0}
    for r in rows[:limit]:
        company, role, url = r.get("company", ""), r.get("title", ""), r["url"]
        print(f">>> {company} :: {role}", flush=True)
        if dry:
            continue
        tid = cfx.open_tab("about:blank")
        tid = tid if isinstance(tid, str) else (tid.get("tabId") or tid.get("id"))
        env = dict(os.environ, CFX_TAB=tid, SR_COMPANY=company, SR_ROLE=role)
        try:
            p = subprocess.run([sys.executable, "-u", APPLY, "auto", url, "--submit"], cwd=ROOT,
                               env=env, capture_output=True, text=True, timeout=1200)
            out, rc = p.stdout + p.stderr, p.returncode
        except subprocess.TimeoutExpired:
            out, rc = "TIMEOUT", 3
        slug = _slug(f"{company}-{role}") or "smartrecruiters"
        proof = os.path.join(ROOT, "applications", slug, "confirmation.png")
        if rc == 0 and "SUBMIT_OK" in out and os.path.getsize(proof) > 0:
            lg = subprocess.run([sys.executable, LOG, company, role, "SmartRecruiters", url, "Applied",
                                 "--proof", proof, "--notes", "SmartRecruiters auto driver; EEO=Prefer not to say"],
                                cwd=ROOT, capture_output=True, text=True)
            print("    APPLIED_OK", (lg.stdout.strip().splitlines() or [""])[-1][:100], flush=True)
            tally["applied"] += 1
        elif rc == 7:
            why = [x for x in out.splitlines() if x.startswith("UNANSWERED_REQUIRED")][:4]
            print("    needs human:", " | ".join(w[:70] for w in why), flush=True)
            tally["needs_human"] += 1
        else:
            print(f"    FAILED rc={rc}: {out.strip().splitlines()[-1][:160] if out.strip() else ''}", flush=True)
            tally["failed"] += 1
        try:
            cfx.close_tab(tid)
        except Exception:  # noqa: BLE001
            pass
    print(json.dumps(tally))
    return 0


if __name__ == "__main__":
    sys.exit(main())
