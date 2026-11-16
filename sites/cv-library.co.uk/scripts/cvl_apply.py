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
import json
import re
import subprocess
import sys
import os
import time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "_common", "scripts"))
import cfx  # noqa: E402
import precheck  # noqa: E402
import screener  # noqa: E402

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
      var b=[...document.querySelectorAll('button,a')].find(x=>x.offsetParent&&/1.?Click Apply|^Apply$|^Apply Now$/i.test((x.innerText||'').trim()));
      if(b){b.click();return 'clicked:'+b.innerText.trim();}
      return 'none';
    })()""")


def _click_text(txt):
    return ev("(function(){var b=[].slice.call(document.querySelectorAll('button')).filter("
              "function(x){return x.offsetParent&&x.innerText.trim()===" + json.dumps(txt) + "})[0];"
              "if(!b)return 'none';b.click();return 'clicked'})()")


def _two_step_flow(job_id):
    """CV-Library's 2026-11 "Apply Now" flow (/job/apply/<id>): Step 1 = CV on file (+ optional
    cover letter) -> Next; Step 2 = per-job Yes/No screening radios -> "Submit application".
    Every radio group is answered ONLY from the shared screener bank (screener.lookup); any
    unanswerable question returns BLOCKED and nothing is submitted. Returns a verdict string to
    stop on, or None to let the caller's Applied check run."""
    if "Step 1 of 2" in str(ev("document.body.innerText") or ""):
        _click_text("Next")
        time.sleep(5)
    groups = ev("""(function(){var seen={},out=[];
      [].slice.call(document.querySelectorAll('input[type=radio]')).forEach(function(r){
        if(seen[r.name]||!r.offsetParent)return; seen[r.name]=1;
        var c=r.closest('fieldset')||r.parentElement; while(c&&c.querySelectorAll('input[type=radio][name="'+r.name+'"]').length<2)c=c.parentElement;
        var opts=[].slice.call(document.querySelectorAll('input[type=radio][name="'+r.name+'"]')).map(function(o){
          var l=(o.labels&&o.labels[0])?o.labels[0].innerText.trim():(o.value||'');return [o.id,l]});
        var q=(c?c.innerText:'').split('\\n')[0].replace(/\\*$/,'').trim();
        out.push({name:r.name,q:q,opts:opts});});
      return JSON.stringify(out)})()""")
    try:
        groups = json.loads(groups or "[]")
    except Exception:  # noqa: BLE001
        groups = []
    unknown = []
    for g in groups:
        hit = screener.lookup(g["q"])
        ans = (hit or {}).get("answer", "").strip().lower()
        oid = next((i for i, l in g["opts"] if l.strip().lower() == ans), None) if ans else None
        if not oid:
            unknown.append(g["q"][:90])
            continue
        ev("(function(){var o=document.getElementById(" + json.dumps(oid) + ");o.click();return o.checked})()")
        print(f"  [{job_id}] screener '{g['q'][:60]}' -> {hit['answer']} ({hit['source']})")
    if unknown:
        return f"[{job_id}] BLOCKED — screening question(s) with no truthful bank answer: {' | '.join(unknown)}"
    if _click_text("Submit application") != "clicked":
        return f"[{job_id}] STUCK (no 'Submit application' button)"
    time.sleep(7)
    return None


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
    if "Already applied" in str(body) or "Applied" == str(body).strip()[:7] or "Apply Again" in str(body):
        return f"[{job_id}] SKIP already-applied (page shows Applied)"
    if _COURSE_SIGNUP_RE.search(str(body)):
        return f"[{job_id}] SKIP course-signup (JD reads as a training-course pitch, not a real job)"
    role, company = _scrape_meta()
    href = ev("(function(){var a=document.querySelector('a[href*=\"/job/apply/\"]');return a?a.href:''})()")
    if href and str(href).startswith("http"):
        # 2026-11 layout: "Apply Now" is an <a> to /job/apply/<id>; a JS .click() on it does
        # not reliably navigate in camofox, so go there directly.
        cfx.navigate(str(href))
        time.sleep(5)
        r = "clicked:nav"
    else:
        r = click_one_click_apply()
    if not r or "clicked" not in str(r):
        time.sleep(3)
        r = click_one_click_apply()
    if not r or "clicked" not in str(r):
        return f"[{job_id}] NO APPLY BUTTON ({r})"
    time.sleep(4)
    final = ev("document.body.innerText") or ""
    for _ in range(5):  # "Apply Now" is a link to /job/apply/<id> — the nav can take >4s
        if "Complete your application" in str(final) or "Applied" in str(final):
            break
        time.sleep(2)
        final = ev("document.body.innerText") or ""
    if "Complete your application" in str(final):
        res = _two_step_flow(job_id)
        if res:
            return res
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
