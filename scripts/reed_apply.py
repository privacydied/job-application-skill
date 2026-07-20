#!/usr/bin/env python3
"""reed_apply.py — drive a Reed.co.uk on-site application for one or more posting ids.

Verified working 2026-07-15. Reed is a REAL, sourceable + applyable non-LinkedIn board
with on-profile junior-mid UX/Service/Product Designer inventory (~25 fresh UX jobs per
London pull) and Jane's session already logged in (profile + CV attached), so apply is a
fast on-site modal — NOT an external ATS.

Flow (observed):
  job page -> click "Apply now" (button.btn-primary) -> modal opens.
  Modal shapes (either order, repeatable):
    A) Screening question(s): Yes/No radios + "Continue"   (1-4 steps)
    B) "About you" summary (prefilled from Reed profile: name/email/phone/CV) + "Submit application"
  We answer every screening "Yes" (truthful — Jane has ~6yrs; e.g. "2yrs in a UX role?" /
  "public-sector GDS experience?" both Yes), click Continue until "Submit application"
  appears, then click it. Verify on /account/jobs/applications (badge count + cards).

CRITICAL Reed wedge (cost real time this session):
  * `cfx.sh click <ref>` on the Apply now button 500s INTERMITTENTLY and the modal does
    NOT open. The reliable click is a DOM querySelector on `button.btn-primary` filtered by
    exact text 'Apply now' (see click_apply_now).
  * The "Submit application" button is NOT captured by `cfx.sh snap` (modal bottom is cut
    off / portal) — click it by text via minimal evaluate (answer_yes_and_advance).
  * The post-submit redirect lands on a 404 page, but the application REGISTERS — confirm
    via the Applications list badge, never the redirect URL.

Usage: python3 reed_apply.py <job_id> [<job_id> ...] [--dry]
  (job_id = the trailing digits in the Reed URL, e.g. 57108922)
"""
import sys
import os
import time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "sites", "_common", "scripts"))
import cfx  # noqa: E402


def ev(expr, tries=8):
    """Evaluate JS. camofox's python cfx.evaluate 500s intermittently on Reed's SPA
    even when the page rendered fine (SKILL.md: route through `cfx.sh eval`). Try the
    python module first, then fall back to the shell wrapper on failure."""
    for _ in range(tries):
        try:
            r = cfx.evaluate(expr)
            if r is not None:
                return r
        except Exception:  # noqa: BLE001
            # fall back to the shell wrapper (same REST endpoint, no python 500s)
            try:
                import subprocess
                import json as _json
                out = subprocess.run(
                    ["bash", os.path.join(HERE, "..", "sites", "_common", "scripts", "cfx.sh"),
                     "eval", expr], capture_output=True, text=True, timeout=60).stdout
                j = _json.loads(out)
                if isinstance(j, dict) and "result" in j and "error" not in j:
                    return j["result"]
            except Exception:
                pass
        time.sleep(1.5)
    return None


def click_by_text(txt, timeout=8):
    end = time.time() + timeout
    while time.time() < end:
        r = ev("""(function(){
          var els=[...document.querySelectorAll('button,input[type=submit],a')];
          for(var i=0;i<els.length;i++){var t=(els[i].innerText||els[i].value||'').trim();
            if(t==='%s'){els[i].click();return 'clicked:'+t;}}
          return 'none';})()""" % txt)
        if r and 'clicked' in str(r):
            return True
        time.sleep(1.5)
    return False


def click_apply_now():
    # Robust DOM click — ref-based cfx.sh click 500s and the modal never opens.
    return ev("""(function(){
      var b=[...document.querySelectorAll('button.btn-primary')].find(x=>x.innerText.trim()==='Apply now');
      if(b){b.click();return 'clicked';}
      var a=[...document.querySelectorAll('a')].find(x=>x.innerText.trim()==='Apply now');
      if(a){a.click();return 'clicked-a';}
      return 'none';
    })()""")


def answer_yes_and_advance():
    # click Yes radio if present, then Submit if present else Continue
    res = ev("""(function(){
      var ls=[...document.querySelectorAll('label')];
      for(var i=0;i<ls.length;i++){if(ls[i].innerText.trim()==='Yes'){var f=ls[i].getAttribute('for');if(f){var el=document.getElementById(f);if(el){el.click();break;}}}}
      var r=[...document.querySelectorAll('input[type=radio]')];
      for(var j=0;j<r.length;j++){var lab=(r[j].parentElement?r[j].parentElement.innerText:'');if(/\\byes\\b/i.test(lab)){r[j].click();break;}}
      // "How did you hear about this job?" is a CHECKBOX step (no Yes radio); when nothing in a
      // visible checkbox group is ticked, Continue re-loops to the SAME step (the AJ-Bell symptom).
      // Tick ONE truthful source option so it advances — prefer job-board/Reed/website (how it was
      // actually sourced), else the first visible box.
      var cbs=[...document.querySelectorAll('input[type=checkbox]')].filter(function(c){return c.offsetParent!==null;});
      if(cbs.length && !cbs.some(function(c){return c.checked;})){
        var pref=cbs.find(function(c){var l=((document.querySelector('label[for=\"'+c.id+'\"]')||c.closest('label')||{}).textContent)||'';return /job ?board|reed|company website|website|online/i.test(l);});
        (pref||cbs[0]).click();
      }
      var b=[...document.querySelectorAll('button,input[type=submit]')].map(x=>(x.innerText||x.value||'').trim());
      if(b.indexOf('Submit application')>=0){var s=[...document.querySelectorAll('button,input[type=submit]')].find(x=>(x.innerText||x.value||'').trim()==='Submit application');s.click();return 'SUBMIT';}
      var c=[...document.querySelectorAll('button,input[type=submit]')].find(x=>(x.innerText||x.value||'').trim()==='Continue');
      if(c){c.click();return 'CONTINUE';}
      return 'NONE:'+b.join('|');
    })()""")
    return res


def apply(job_arg, dry=False):
    # job_arg may be a bare id (default ux-designer slug) or a full Reed URL.
    if str(job_arg).startswith("http"):
        url = job_arg
        job_id = job_arg.rstrip("/").split("/")[-1]
    else:
        job_id = job_arg
        url = f"https://www.reed.co.uk/jobs/ux-designer/{job_id}"
    print(f"[{job_id}] nav {url}")
    if dry:
        return "dry"
    cfx.navigate(url)
    # Reed's job page lazy-renders the "Apply now" button via JS; a 5s settle races it
    # and click_apply_now() returns 'none' -> LOOP-END. Give the SPA time to paint.
    time.sleep(9)
    r = click_apply_now()
    if not r or 'clicked' not in str(r):
        time.sleep(4)
        r = click_apply_now()
    if not r or 'clicked' not in str(r):
        # one more settle+retry before giving up (camofox eval can 500 spuriously)
        time.sleep(5)
        r = click_apply_now()
    if not r or 'clicked' not in str(r):
        return f"[{job_id}] NO APPLY BUTTON ({r})"
    time.sleep(6)
    for step in range(8):
        res = str(answer_yes_and_advance())
        if 'SUBMIT' in res:
            time.sleep(5)
            return f"[{job_id}] SUBMITTED (url={ev('location.href')})"
        if 'CONTINUE' in res:
            time.sleep(5)
            continue
        if 'NONE' in res:
            if click_by_text("Submit application", timeout=4):
                time.sleep(5)
                return f"[{job_id}] SUBMITTED2 (url={ev('location.href')})"
            return f"[{job_id}] STUCK ({res})"
        time.sleep(4)
    return f"[{job_id}] LOOP-END"


if __name__ == "__main__":
    args = sys.argv[1:]
    dry = "--dry" in args           # BUGFIX: --dry was skipped, never passed to apply() —
    ids = [a for a in args if a != "--dry"]   # so a "dry run" actually SUBMITTED. Now it's honored.
    for jid in ids:
        print(apply(jid.strip(), dry=dry))
        time.sleep(3)
