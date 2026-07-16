#!/usr/bin/env python3
"""reed_apply.py — drive a Reed.co.uk on-site application for one posting id.

Flow (observed): job page -> click "Apply now" -> modal appears.
Two modal shapes:
  A) Screening question(s): Yes/No radios + "Continue"  -> then About-you modal
  B) About-you summary (prefilled) + "Submit application"  (sometimes a screening
     question precedes it)
We answer any "Yes/No" screening with Yes, click Continue if present, then click
"Submit application". Finally verify on /account/jobs/applications.

Usage: python3 reed_apply.py <job_id> [--dry]
"""
import sys, os, time, json, subprocess
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "sites", "_common", "scripts"))
import cfx

ROOT = HERE  # this file lives at the skill root; derive the path, don't hard-code it
REED_TAB_FILE = os.path.join(ROOT, ".reed_tab")

def ev(expr, tries=8):
    for _ in range(tries):
        try:
            r = cfx.evaluate(expr)
            if r is not None:
                return r
        except Exception:
            time.sleep(1.5)
    return None

def snap_buttons():
    # minimal: list buttons by text via DOM (avoid complex evaluate wedge)
    return ev("""JSON.stringify([...document.querySelectorAll('button,input[type=submit],a')]
        .map(b=>(b.innerText||b.value||b.textContent||'').trim())
        .filter(t=>t.length>0 && t.length<60))""")

def click_by_text(txt, timeout=8):
    end=time.time()+timeout
    while time.time()<end:
        r=ev("""(function(){
          var els=[...document.querySelectorAll('button,input[type=submit],a')];
          for(var i=0;i<els.length;i++){var t=(els[i].innerText||els[i].value||'').trim();
            if(t==='%s'){els[i].click();return 'clicked:'+t;}}
          return 'none';})()""" % txt)
        if r and 'clicked' in str(r):
            return True
        time.sleep(1.5)
    return False

def answer_screening():
    # click any radio whose label says Yes, then Continue
    ev("""(function(){
      var radios=[...document.querySelectorAll('input[type=radio]')];
      for(var i=0;i<radios.length;i++){
        var lab='';
        if(radios[i].nextSibling) lab+=radios[i].nextSibling.textContent||'';
        if(radios[i].parentElement) lab+=radios[i].parentElement.textContent||'';
        if(/\\byes\\b/i.test(lab)){radios[i].click();return 'yes-clicked';}
      }
      // also try label[for]
      var ls=[...document.querySelectorAll('label')];
      for(var j=0;j<ls.length;j++){if(/\\byes\\b/i.test(ls[j].innerText||'')){var f=ls[j].getAttribute('for');if(f){var el=document.getElementById(f);if(el){el.click();return 'label-yes';}}}}
      return 'no-radio';
    })()""")
    time.sleep(1.5)
    # click Continue if present
    click_by_text("Continue", timeout=4)

def click_apply_now():
    # robust DOM click on the btn-primary 'Apply now' (ref-clicks 500 intermittently)
    return ev("""(function(){
      var b=[...document.querySelectorAll('button.btn-primary')].find(x=>x.innerText.trim()==='Apply now');
      if(b){b.click();return 'clicked';}
      var a=[...document.querySelectorAll('a')].find(x=>x.innerText.trim()==='Apply now');
      if(a){a.click();return 'clicked-a';}
      return 'none';
    })()""")

def answer_yes_and_advance():
    # click Yes radio if present, then click Submit if present else Continue
    res=ev("""(function(){
      var ls=[...document.querySelectorAll('label')];
      for(var i=0;i<ls.length;i++){if(ls[i].innerText.trim()==='Yes'){var f=ls[i].getAttribute('for');if(f){var el=document.getElementById(f);if(el){el.click();break;}}}}
      var r=[...document.querySelectorAll('input[type=radio]')];
      for(var j=0;j<r.length;j++){var lab=(r[j].parentElement?r[j].parentElement.innerText:'');if(/\\bYes\\b/i.test(lab)){r[j].click();break;}}
      var b=[...document.querySelectorAll('button,input[type=submit]')].map(x=>(x.innerText||x.value||'').trim());
      if(b.indexOf('Submit application')>=0){var s=[...document.querySelectorAll('button,input[type=submit]')].find(x=>(x.innerText||x.value||'').trim()==='Submit application');s.click();return 'SUBMIT';}
      var c=[...document.querySelectorAll('button,input[type=submit]')].find(x=>(x.innerText||x.value||'').trim()==='Continue');
      if(c){c.click();return 'CONTINUE';}
      return 'NONE:'+b.join('|');
    })()""")
    return res

def apply(job_id, dry=False):
    url=f"https://www.reed.co.uk/jobs/ux-designer/{job_id}"
    print(f"[{job_id}] nav {url}")
    if dry:
        return "dry"
    cfx.navigate(url); time.sleep(5)
    r=click_apply_now()
    if not r or 'clicked' not in str(r):
        time.sleep(3); r=click_apply_now()
    if not r or 'clicked' not in str(r):
        return f"[{job_id}] NO APPLY BUTTON ({r})"
    time.sleep(6)
    for step in range(8):
        res=answer_yes_and_advance()
        res=str(res)
        if 'SUBMIT' in res:
            time.sleep(5)
            return f"[{job_id}] SUBMITTED (url={ev('location.href')})"
        if 'CONTINUE' in res:
            time.sleep(5); continue
        if 'NONE' in res:
            # maybe About-you with Submit not detected; try direct submit
            if click_by_text("Submit application", timeout=4):
                time.sleep(5); return f"[{job_id}] SUBMITTED2 (url={ev('location.href')})"
            return f"[{job_id}] STUCK ({res})"
        time.sleep(4)
    return f"[{job_id}] LOOP-END"

if __name__ == "__main__":
    ids=sys.argv[1:]
    for jid in ids:
        print(apply(jid.strip()))
        time.sleep(3)
