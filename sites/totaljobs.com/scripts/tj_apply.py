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

Usage: python3 tj_apply.py <job_url> [<job_url> ...] [--dry] [--answers answers.json]
  (--answers: {"question substring": "truthful answer"} for role-specific screeners)
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


def _external_url():
    """On the UNVERIFIED 'Did all go well?' page, click 'Company website' and report the
    employer/agency URL it opens (new tab), closing the leaked tab. Read-only: lets the
    caller route the posting to the right ATS driver instead of guessing."""
    try:
        before = {t.get("tabId") for t in cfx.list_tabs()}
        ev("""(()=>{const b=[...document.querySelectorAll('button,a')].find(e=>/Company website/i.test(e.innerText));if(b)b.click();})()""")
        time.sleep(4)
        for t in cfx.list_tabs():
            if t.get("tabId") not in before and "totaljobs.com" not in (t.get("url") or ""):
                u = t.get("url")
                try:
                    cfx.close_tab(t["tabId"])
                except Exception:  # noqa: BLE001
                    pass
                return u
    except Exception as e:  # noqa: BLE001
        return f"ERR:{str(e)[:60]}"
    return "none"


def _log_applied(url, job_id, role, company, status="Applied?"):
    role = role or f"TotalJobs posting {job_id}"
    if not company:  # selector misses on the new layout — the URL slug always carries it
        m = re.search(r"/job/[^/]+/(.+?)-job\d+", url or "")
        if m:
            company = " ".join(w.capitalize() for w in m.group(1).split("-"))
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
      var b=[...document.querySelectorAll('button,a')].find(x=>x.innerText.trim()==='Apply')
          ||[...document.querySelectorAll('button,a')].find(x=>x.innerText.trim()==='Continue application');
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


ANSWERS = {}   # per-run question-substring -> answer map (--answers file.json); checked BEFORE the bank


def _map_answer(q):
    ql = (q or "").lower()
    for k, v in ANSWERS.items():
        if k.lower() in ql:
            return v
    return None


def _answer_text_questions():
    """Fill EMPTY free-text screeners (notice period, salary expectation, 'why are you suited',
    convictions…) on the Smart Apply review page. Answer source, in order: the per-run
    --answers map (role-specific text the caller wrote truthfully), then the shared screener
    bank. Any empty required text field with no answer is returned (apply() then refuses) —
    nothing is invented here. Returns '' when every empty text field got an answer."""
    import json as _json
    import screener  # noqa: E402
    raw = ev("""(function(){
      var h=[...document.querySelectorAll('h1,h2,h3,h4,p,span,div')].find(function(x){return x.childElementCount===0&&x.innerText&&x.innerText.trim()==='Additional questions'});
      if(!h) return '[]';
      var els=[...document.querySelectorAll('textarea,input[type=text],input[type=number],input:not([type])')]
        .filter(function(e){return e.offsetParent!==null && !e.value
          && (h.compareDocumentPosition(e) & Node.DOCUMENT_POSITION_FOLLOWING)});
      return JSON.stringify(els.map(function(e,i){
        e.setAttribute('data-tjq',String(i));
        var lab=(e.labels&&e.labels[0])?e.labels[0]:null;
        for(var a=e,k=0;!lab&&a&&k<5;k++,a=a.parentElement){var p=a.previousElementSibling; while(p&&!p.innerText.trim()) p=p.previousElementSibling; if(p) lab=p;}
        return {i:i,num:e.type==='number',q:(lab?lab.innerText:'').split('\\n')[0].replace(/\\*\\s*$/,'').trim()};
      }));
    })()""")
    try:
        fields = _json.loads(raw) if isinstance(raw, str) else []
    except ValueError:
        fields = []
    missing = []
    for f in fields:
        q = f.get("q") or ""
        ans = _map_answer(q)
        if ans is None and q:
            hit = screener.lookup(q)
            ans = hit["answer"] if hit else None
        if ans is None:
            missing.append(q or "(unlabelled text field)")
            continue
        if f.get("num"):   # <input type=number> rejects "£40,000" — keep the first number only
            m = re.search(r"\d[\d,]*", str(ans))
            if not m:
                missing.append(q)
                continue
            ans = m.group(0).replace(",", "")
        ev("""(function(){var e=document.querySelector('[data-tjq="%d"]'); if(!e) return 'none';
          var proto=e.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;
          Object.getOwnPropertyDescriptor(proto,'value').set.call(e,%s);
          e.dispatchEvent(new Event('input',{bubbles:true})); e.dispatchEvent(new Event('change',{bubbles:true}));
          e.dispatchEvent(new Event('blur',{bubbles:true})); return 'ok';})()""" % (f["i"], _json.dumps(ans)))
        print(f"    text: {q[:70]!r} -> {str(ans)[:60]!r}")
    return " | ".join(missing)


def _answer_screeners_from_bank():
    """Answer the 'Additional questions' Yes/No radios ONLY from the shared truthful screener
    bank (sites/_common/scripts/screener.py — profile-derived rows like right-to-work,
    sponsorship, SC eligibility). Every question must have a bank answer that matches one of
    its options; if ANY is unknown, nothing is guessed and its text is returned so apply()
    refuses (same no-blind-answer contract as before — a tech-stack question like
    'commercial Angular experience?' has no bank row and still blocks). Returns '' when all
    questions were answered."""
    import json as _json
    import screener  # noqa: E402  (same dir as cfx/precheck on sys.path)
    # The Smart Apply renderer draws each answer as <button role=radio> inside a
    # <div role=group> labelled by the preceding <label> ("1. Do you have the right…*") — no
    # native <input type=radio> exists (verified 2026-10-15, Mercator UI/UX Designer). Groups
    # are addressed by index; native radio groups are handled too for older templates.
    GROUPS_JS = """(function(){
      var gs=[...document.querySelectorAll('[role=group],[role=radiogroup],fieldset')]
        .filter(function(g){return g.querySelector('[role=radio],input[type=radio]')
          && !g.parentElement.closest('[role=group],[role=radiogroup],fieldset')});
      return gs;
    })()"""
    raw = ev("""(function(){
      var gs=%s;
      return JSON.stringify(gs.map(function(g){
        var lab=null, id=g.getAttribute('aria-labelledby');
        if(id) lab=document.getElementById(id.split(' ')[0]);
        if(!lab) lab=g.querySelector('label,legend');
        for(var a=g,k=0;!lab&&a&&k<4;k++,a=a.parentElement){var p=a.previousElementSibling; while(p&&!p.innerText.trim()) p=p.previousElementSibling; if(p) lab=p;}
        var q=(lab?lab.innerText:'').split('\\n')[0].replace(/\\*\\s*$/,'').trim();
        var rs=[...g.querySelectorAll('[role=radio],input[type=radio]')];
        return {q:q,opts:rs.map(function(r){var l=r.labels&&r.labels[0];return (r.tagName==='INPUT'?(l?l.innerText:r.value):r.innerText).trim()})};
      }));
    })()""" % GROUPS_JS)
    try:
        groups = _json.loads(raw) if isinstance(raw, str) else []
    except ValueError:
        groups = []
    if not groups:
        return "(could not read the screening questions)"
    plan, missing = [], []
    for gi, g in enumerate(groups):
        hit = screener.lookup(re.sub(r"^\d+\.\s*", "", g["q"])) if g["q"] else None
        ans = _map_answer(g["q"]) or (hit or {}).get("answer", "")
        oi = next((i for i, o in enumerate(g["opts"]) if o.strip().lower() == ans.strip().lower()), None)
        if oi is None:
            missing.append(g["q"] or f"(unlabelled group {gi})")
        else:
            plan.append((gi, oi, g["opts"][oi], g["q"]))
    if missing:
        return " | ".join(missing)
    for gi, oi, opt, q in plan:
        ev("""(function(){var g=%s[%d]; var r=[...g.querySelectorAll('[role=radio],input[type=radio]')][%d];
          if(!r) return 'none'; ((r.labels&&r.labels[0])||r).click(); return 'clicked';})()""" % (GROUPS_JS, gi, oi))
        print(f"    screener: {q[:70]!r} -> {opt}")
        time.sleep(0.4)
    left = ev("""(function(){var gs=%s; return gs.filter(function(g){
        return ![...g.querySelectorAll('[role=radio],input[type=radio]')].some(function(r){
          return r.checked||r.getAttribute('aria-checked')==='true'})}).length})()""" % GROUPS_JS)
    return "" if left == 0 else f"({left} radio group(s) did not commit)"


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
        # Smart Apply renders client-side; on a slow load the first read is just the header
        # (just the account initial + first name), which used to fall through to a STUCK verdict (2026-10-15: 7/33 rows).
        # Poll until the review form (or a terminal page) has actually rendered.
        for _ in range(8):
            if any(s in str(body_after_apply) for s in ("Send application", "Additional questions",
                                                        "Application summary", "Did all go well",
                                                        "Application sent")):
                break
            time.sleep(2)
            body_after_apply = ev("document.body.innerText") or ""
        qtext = _screening_questions_text()
        if qtext:
            unanswered = " | ".join(x for x in (_answer_text_questions(),
                                                _answer_screeners_from_bank()) if x)
            if unanswered:
                return (f"[{job_id}] BLOCKED — screening question(s) with no truthful bank "
                        f"answer, never blind-answered: {unanswered[:250]}")
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
    for _ in range(10):
        time.sleep(2.5)
        final = ev("document.body.innerText") or ""
        href = ev("location.href") or ""
        if "Application sent" in str(final):
            break
        # confirmation/PENDING ("This should only take a few seconds") and a still-blank
        # confirmation/success both flip to "Application sent!" a few seconds later (JKR
        # 108142055, 2026-10-15 was misreported STUCK) — keep polling through them.
        if ("Sending your application" not in str(final)
                and "Preparing your application" not in str(final)
                and "only take a few seconds" not in str(final)
                and "confirmation/" not in str(href)):
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
        ext = _external_url()
        return (f"[{job_id}] UNVERIFIED — confirmation-shaped page reached but no "
                f"'Application sent!' banner; cross-check the job listing ('Already "
                f"applied'?) and account Applications list before logging Applied "
                f"(url={href}) EXTERNAL={ext}")
    return f"[{job_id}] STUCK (href={href} body={str(final)[:150]})"


if __name__ == "__main__":
    args = sys.argv[1:]
    dry = "--dry" in args
    if "--answers" in args:
        import json as _json
        i = args.index("--answers")
        ANSWERS.update(_json.load(open(args[i + 1], encoding="utf-8")))
        del args[i:i + 2]
    urls = [a for a in args if a != "--dry"]
    for u in urls:
        print(apply(u.strip(), dry=dry))
        time.sleep(3)
