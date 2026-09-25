#!/usr/bin/env python3
"""cvl_apply.py — drive a CV-Library.co.uk 1-Click Apply for one or more posting URLs/ids.

Verified working (see NOTES.md "1-Click Apply works with a logged-in account", 2026-09-04).
With `ats-credentials.csv` creds and a fresh `cfx.goto()` nav (candidate name visible in the
header = logged in), the "1-Click Apply" button on a with-CV-on-file posting submits
immediately — no modal, no upload step, page flips straight to "Applied" / "Apply Again".

CRITICAL CV-Library quirk (documented in NOTES.md, carried over here):
  `cfx.click_selector()` on the 1-Click Apply button reliably TIMES OUT (30s) even though
  the element is visible/unobstructed. Fix: skip the Playwright click endpoint and fire a
  plain JS `.click()` via cfx.evaluate, after first removing the OneTrust cookie-consent
  overlay if present (it can eat the first real-mouse click attempt).

⛔ COURSE-SIGNUP TRAP (same class documented on Reed/TotalJobs, 2026-09-25): CV-Library
carries the SAME kind of disguised paid/self-funded "course that leads to employment,
fees apply" postings — found live in the "IT Support Assistant – Training Course" and
"Business Analyst Placement Programme" listings, both from recruiters ("ITOL Recruit")
already flagged on other boards. This driver scans the JD body for course-pitch language
before ever clicking 1-Click Apply — see _COURSE_SIGNUP_RE (same shape as tj_apply.py's;
CV-Library doesn't carry Reed's literal badge either).

⛔ CROSS-BOARD DUPLICATE RISK: CV-Library aggregates many of the SAME original postings
already sourced via Reed/TotalJobs today (same recruiter, same role, different board URL).
precheck.guard() only dedups by URL/canonical id, which differs per board — it CANNOT catch
a cross-board repost. Cross-check (company, role) against the tracker before calling apply()
on a CV-Library candidate; this driver does not do that check itself (same limitation as
reed_apply.py / tj_apply.py).

Usage: python3 cvl_apply.py <job_id_or_url> [<job_id_or_url> ...] [--dry]
  (job_id = the numeric CV-Library posting id, e.g. 225601445, or the full URL)
"""
import re
import subprocess
import sys
import os
import time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "_common", "scripts"))
import cfx  # noqa: E402
import precheck  # noqa: E402

LOGAPP = os.path.join(HERE, "..", "..", "_common", "scripts", "log-application.py")


def ev(expr, tries=6):
    for _ in range(tries):
        try:
            r = cfx.evaluate(expr)
            if r is not None:
                return r
        except Exception:  # noqa: BLE001
            try:
                import json as _json
                out = subprocess.run(
                    ["bash", os.path.join(HERE, "..", "..", "_common", "scripts", "cfx.sh"),
                     "eval", expr], capture_output=True, text=True, timeout=60).stdout
                j = _json.loads(out)
                if isinstance(j, dict) and "result" in j and "error" not in j:
                    return j["result"]
            except Exception:
                pass
        time.sleep(1.5)
    return None


_COURSE_SIGNUP_RE = re.compile(
    r"\b(fully[- ]funded (course|programme|training)|government[- ]funded (course|"
    r"training|programme)|self[- ]funded programme|course fees? appl|job guarantee|"
    r"traineeship|training programme designed to|no (prior )?experience required.{0,40}"
    r"(train|course|programme)|structured pathway into|become job[- ]ready|"
    r"gain (a |your )?(globally recognised |industry[- ]recognised )?(certification|"
    r"qualification)|coding traineeship)\b", re.I)


def _job_url(arg):
    if str(arg).startswith("http"):
        return arg
    return f"https://www.cv-library.co.uk/job/{arg}"


def _scrape_meta():
    """Role = the h1. Company: CV-Library renders it as 'Posted <date> by <Company>' —
    NOT a dedicated .company-class element (a naive `[class*=company]` selector matched a
    byline wrapper and returned the WHOLE 'Posted DD/MM/YYYY by X' string as the company
    name, found live 2026-09-25 — corrupted 6 tracker rows). Parse the 'by <Company>' text
    out of the page body instead."""
    r = ev("""(function(){
      var h=document.querySelector('h1');
      var body = document.body.innerText;
      var m = body.match(/Posted[^\\n]*?\\bby\\s+([^\\n]+)/);
      return JSON.stringify({role:(h?h.innerText:'').trim(), company:(m?m[1]:'').trim()});
    })()""")
    try:
        import json as _json
        m = _json.loads(r) if isinstance(r, str) else {}
    except Exception:  # noqa: BLE001
        m = {}
    return (m.get("role") or "", m.get("company") or "")


def _log_applied(url, job_id, role, company, status="Applied?"):
    role = role or f"CV-Library posting {job_id}"
    company = company or "(unknown employer — CV-Library)"
    try:
        r = subprocess.run(
            [sys.executable, LOGAPP, company, role, "CV-Library", url, status,
             "--notes", "auto-logged by cvl_apply on 1-Click Apply click "
             "(page flipped to Applied/Apply Again)"],
            capture_output=True, text=True, timeout=30)
        print("  log:", (r.stdout or r.stderr).strip().splitlines()[-1][:160] if (r.stdout or r.stderr).strip() else f"rc={r.returncode}")
    except Exception as e:  # noqa: BLE001
        print("  log FAILED (submit stands — log by hand):", str(e)[:120])


def click_one_click_apply():
    """Remove the OneTrust cookie overlay (can eat the first click) then fire a plain JS
    .click() on the 1-Click Apply button — NEVER cfx.click_selector(), which reliably
    times out on this specific board (documented NOTES.md quirk)."""
    return ev("""(function(){
      var ot=document.querySelector('#onetrust-consent-sdk');
      if(ot) ot.remove();
      var b=[...document.querySelectorAll('button,a')].find(x=>/1.?Click Apply|^Apply$/i.test((x.innerText||'').trim()));
      if(b){b.click();return 'clicked:'+b.innerText.trim();}
      return 'none';
    })()""")


def apply(arg, dry=False):
    url = _job_url(arg)
    job_id = url.rstrip("/").split("/")[-1]
    print(f"[{job_id}] nav {url}")
    if precheck.guard(url=url, label="cvlibrary"):
        return f"[{job_id}] SKIP already-applied"
    if dry:
        return "dry"
    cfx.navigate(url)
    time.sleep(3)
    body = ev("document.body.innerText") or ""
    if "Already applied" in str(body) or "Applied" == str(body).strip()[:7]:
        return f"[{job_id}] SKIP already-applied (page shows Applied)"
    if _COURSE_SIGNUP_RE.search(str(body)):
        return f"[{job_id}] SKIP course-signup (JD reads as a training-course pitch, not a real job)"
    role, company = _scrape_meta()
    r = click_one_click_apply()
    if not r or "clicked" not in str(r):
        time.sleep(3)
        r = click_one_click_apply()
    if not r or "clicked" not in str(r):
        return f"[{job_id}] NO APPLY BUTTON ({r})"
    time.sleep(4)
    final = ev("document.body.innerText") or ""
    if "Applied" in str(final) or "Apply Again" in str(final):
        _log_applied(url, job_id, role, company, status="Applied?")
        return f"[{job_id}] SUBMITTED"
    return f"[{job_id}] STUCK (body={str(final)[:200]})"


if __name__ == "__main__":
    args = sys.argv[1:]
    dry = "--dry" in args
    ids = [a for a in args if a != "--dry"]
    for jid in ids:
        print(apply(jid.strip(), dry=dry))
        time.sleep(3)
