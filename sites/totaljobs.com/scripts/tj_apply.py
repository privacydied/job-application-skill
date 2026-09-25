#!/usr/bin/env python3
"""tj_apply.py — drive a TotalJobs.com Smart Apply for one or more posting URLs/ids.

Verified working 2026-09-25 (mirrors the already-verified manual flow documented in
sites/totaljobs.com/NOTES.md "STALE ABOVE" section, promoted to a real driver so a batch
doesn't need per-posting manual cfx calls). With the `totaljobs.com (StepStone)` row in
ats-credentials.csv already authenticated in the browser profile, clicking a listing's
"Apply" button routes straight into an already-authenticated Smart Apply flow
(name/email/phone/CV pre-filled from the account) -> "Send application" ->
`/application/confirmation/success` showing "Application sent!".

Flow (observed):
  job page -> click "Apply" (exact text, button or a) -> Smart Apply form
    (pre-filled Contact details + CV; a "Poor Fit"/"Strong Fit" AI match banner is
    informational only, not a gate) -> click "Send application" -> confirmation page
    showing "Application sent!" + Applied badge on the job card.

⛔ COURSE-SIGNUP TRAP (same class documented in sites/reed.co.uk/NOTES.md, 2026-09-25):
some postings across UK job boards are disguised paid/government-funded training-course
sign-ups, not real jobs. TotalJobs doesn't carry Reed's literal "Training Course" badge, so
this driver scans the JD body text for course-shaped language before ever clicking Apply —
see _COURSE_SIGNUP_RE. Extend that regex here (not a copy in reed_apply.py) if a new
disguise phrasing is found on THIS board; the two boards' signal shapes differ (badge text
vs. body language) so each driver keeps its own detector, per NOTES.md's guidance to extend
in place rather than fork.

Usage: python3 tj_apply.py <job_url> [<job_url> ...] [--dry]
  (job_url = full https://www.totaljobs.com/job/... URL, as sourced by feed.py)
"""
import re
import subprocess
import sys
import os
import time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "_common", "scripts"))
import cfx  # noqa: E402
import precheck  # noqa: E402  (mandatory pre-submit dedup gate)

LOGAPP = os.path.join(HERE, "..", "..", "_common", "scripts", "log-application.py")
APPS = os.path.join(HERE, "..", "..", "..", "applications")


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


# Course-signup body-language detector (TotalJobs shape — no literal badge like Reed's
# "Training Course"; the JD text itself reads as a course pitch). Kept deliberately
# specific to avoid false-positiving a genuine training/certification MENTION inside a
# real job's requirements ("CompTIA A+ desirable" is fine; "gain a CompTIA
# certification" as the offer itself is the trap).
_COURSE_SIGNUP_RE = re.compile(
    r"\b(fully[- ]funded (course|programme|training)|government[- ]funded (course|"
    r"training|programme)|self[- ]funded programme|course fees? appl|job guarantee|"
    r"traineeship|training programme designed to|no (prior )?experience required.{0,40}"
    r"(train|course|programme)|structured pathway into|become job[- ]ready|"
    r"gain (a |your )?(globally recognised |industry[- ]recognised )?(certification|"
    r"qualification)|coding traineeship)\b", re.I)


def _scrape_meta():
    r = ev("""(function(){
      var h=document.querySelector('h1');
      var c=document.querySelector('[class*=company],[data-at*=company]');
      return JSON.stringify({role:(h?h.innerText:'').trim(),company:(c?c.innerText:'').trim()});
    })()""")
    try:
        import json as _json
        m = _json.loads(r) if isinstance(r, str) else {}
    except Exception:  # noqa: BLE001
        m = {}
    return (m.get("role") or "", m.get("company") or "")


def _log_applied(url, job_id, role, company, status="Applied?"):
    role = role or f"TotalJobs posting {job_id}"
    company = company or "(unknown employer — TotalJobs)"
    try:
        r = subprocess.run(
            [sys.executable, LOGAPP, company, role, "TotalJobs", url, status,
             "--notes", "auto-logged by tj_apply on SUBMIT (Send application clicked, "
             "confirmation page reached)"],
            capture_output=True, text=True, timeout=30)
        print("  log:", (r.stdout or r.stderr).strip().splitlines()[-1][:160] if (r.stdout or r.stderr).strip() else f"rc={r.returncode}")
    except Exception as e:  # noqa: BLE001
        print("  log FAILED (submit stands — log by hand):", str(e)[:120])


def click_apply():
    return ev("""(function(){
      var b=[...document.querySelectorAll('button,a')].find(x=>x.innerText.trim()==='Apply');
      if(b){b.click();return 'clicked';}
      return 'none';
    })()""")


def click_send_application():
    return ev("""(function(){
      var b=[...document.querySelectorAll('button')].find(x=>x.innerText.trim()==='Send application');
      if(b){b.click();return 'clicked';}
      return 'none';
    })()""")


def _screening_questions_text():
    """The Smart Apply review page can show an 'Additional questions' / 'Action required'
    block with role-specific Yes/No screeners (e.g. 'strong commercial experience with
    Angular and TypeScript?', 'hands-on experience using NgRx?'). Unlike Reed's generic
    'X years experience?' style, these name SPECIFIC tech stacks/tools this driver has no
    way to verify against the applicant's real skills — blind-answering risks an
    untruthful Yes (found live 2026-09-25: Gazelle Global Frontend Developer asked about
    Angular/NgRx/RxJS, none of which the applicant has — see applicant-profile.md). Return
    the block's text (empty string if no such block) so apply() can refuse to blind-answer."""
    return ev("""(function(){
      var all = document.body.innerText;
      var idx = all.indexOf('Additional questions');
      if (idx < 0) return '';
      return all.slice(idx, idx + 800);
    })()""") or ""


def apply(url, dry=False):
    job_id = "".join(re.findall(r"job(\d+)$", url)) or url.rstrip("/").split("/")[-1]
    print(f"[{job_id}] nav {url}")
    if precheck.guard(url=url, label="totaljobs"):
        return f"[{job_id}] SKIP already-applied"
    if dry:
        return "dry"
    cfx.navigate(url)
    time.sleep(4)
    body = ev("document.body.innerText") or ""
    if _COURSE_SIGNUP_RE.search(str(body)):
        return f"[{job_id}] SKIP course-signup (JD reads as a training-course pitch, not a real job)"
    role, company = _scrape_meta()
    r = click_apply()
    if not r or "clicked" not in str(r):
        time.sleep(3)
        r = click_apply()
    if not r or "clicked" not in str(r):
        return f"[{job_id}] NO APPLY BUTTON ({r})"
    time.sleep(4)
    # TWO apply-flow shapes exist on TotalJobs (found live 2026-09-25): most postings land
    # on a Smart Apply REVIEW form needing a second "Send application" click; some go
    # straight through to a confirmation/"Application summary" page from the single Apply
    # click (one-click variant) — reaching "NO SEND-APPLICATION BUTTON" is EXPECTED there,
    # not a failure. Check for a terminal state before assuming a second click is needed.
    body_after_apply = ev("document.body.innerText") or ""
    href_after_apply = ev("location.href") or ""
    already_terminal = ("Application summary" in str(body_after_apply)
                         or "Did all go well" in str(body_after_apply)
                         or "Application sent" in str(body_after_apply)
                         or "confirmation/success" in str(href_after_apply))
    if not already_terminal:
        qtext = _screening_questions_text()
        if qtext:
            return (f"[{job_id}] BLOCKED — role-specific screening question(s) on the "
                     f"review form, never blind-answered: {qtext[:250]}")
        r2 = click_send_application()
        if not r2 or "clicked" not in str(r2):
            time.sleep(3)
            r2 = click_send_application()
        if not r2 or "clicked" not in str(r2):
            # Re-check terminal state once more before giving up — the poll above may have
            # landed mid-transition.
            body_after_apply = ev("document.body.innerText") or ""
            href_after_apply = ev("location.href") or ""
            already_terminal = ("Application summary" in str(body_after_apply)
                                 or "Did all go well" in str(body_after_apply)
                                 or "Application sent" in str(body_after_apply)
                                 or "confirmation/success" in str(href_after_apply))
            if not already_terminal:
                return f"[{job_id}] NO SEND-APPLICATION BUTTON reached ({r2})"
    # The confirmation page shows an interstitial ("Sending your application... this should
    # only take a few seconds") before the real "Application sent!" banner renders — a single
    # short sleep can read the interstitial and misreport STUCK on a genuinely-submitted
    # application (found live 2026-09-25). Poll up to ~15s for either terminal signal.
    final, href = "", ""
    for _ in range(6):
        time.sleep(2.5)
        final = ev("document.body.innerText") or ""
        href = ev("location.href") or ""
        if "Application sent" in str(final) or "confirmation/success" in str(href):
            break
        if "Sending your application" not in str(final):
            break  # settled on something else — stop polling, report what we see
    # ⛔ NEITHER "Did all go well with your application?" NOR a bare confirmation/success
    # URL / "Application summary" page is a reliable submit signal on its own (found live
    # 2026-09-25, multiple postings incl. Hackajob Ltd x2, Arup CWS, Southern Housing,
    # Rocket): all of these can render even when the posting is an EXTERNAL-ATS redirect
    # that never actually completed — the job listing still showed plain "Apply" (never
    # flipped to "Already applied") and the posting never appeared in the account's
    # "Applications" Today list, in every case checked. Only the literal "Application
    # sent!" banner (the Smart Apply review-form flow's real terminal state) is trusted as
    # SUBMITTED here. Everything else — bare confirmation/success, "Application summary",
    # "Did all go well" — is reported UNVERIFIED so a human/later pass cross-checks the
    # account's Applications list (https://www.totaljobs.com/ -> "N applications" link)
    # before counting it as a real Applied. Do not loosen this without re-verifying live.
    if "Application sent" in str(final):
        _log_applied(url, job_id, role, company, status="Applied?")
        return f"[{job_id}] SUBMITTED (url={href})"
    if ("Did all go well" in str(final) or "Application summary" in str(final)
            or "confirmation/success" in str(href)):
        return (f"[{job_id}] UNVERIFIED — confirmation-shaped page reached but no "
                f"'Application sent!' banner; cross-check the job listing ('Already "
                f"applied'?) and account Applications list before logging Applied "
                f"(url={href})")
    return f"[{job_id}] STUCK (href={href} body={str(final)[:150]})"


if __name__ == "__main__":
    args = sys.argv[1:]
    dry = "--dry" in args
    urls = [a for a in args if a != "--dry"]
    for u in urls:
        print(apply(u.strip(), dry=dry))
        time.sleep(3)
