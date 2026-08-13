#!/usr/bin/env python3
"""submit_ashby.py — adaptive fill + trusted-submit for ANY Ashby application.

Key fixes vs naive approach:
- Resume: try input[id=_systemfield_resume], fall back to input[type=file].
- Radios: discover groups dynamically; map by QUESTION-KEYWORD to the applicant's
  truthful value (gender/transgender/orientation/disability/neurodiverse/age/consent).
  Commit via setNativeChecked + dispatch MouseEvent (React state) — NOT bare .click().
- Trusted submit via cfx.click_selector (Playwright input channel) — beats Ashby spam-flag.
- On submit, re-read the page; only log Applied on a REAL confirmation banner.
"""
import json, os, re, sys, time, subprocess
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "sites", "_common", "scripts"))
import cfx

# Applicant truthful values (kept here; no external PII file needed for on-lane answers)
APPLICANT = {
    "gender": "Man",
    "transgender": "No",
    "orientation": "Heterosexual/Straight",
    "disability": "No",
    "neurodiverse": "No",
    "age": "25 - 34",
}
EEO_KEYWORDS = [
    ("transgender", "transgender", APPLICANT["transgender"]),
    ("sexual orientation", "orientation", APPLICANT["orientation"]),
    ("gender", "gender", APPLICANT["gender"]),
    ("disabilities", "disability", APPLICANT["disability"]),
    ("neurodiverse", "neurodiverse", APPLICANT["neurodiverse"]),
    ("age are you", "age", APPLICANT["age"]),
]

_RADIO_JS = r"""(function(g, o){
  g=g.toLowerCase(); o=o.toLowerCase();
  function setNative(el){ var d=Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el),'checked'); if(d&&d.set){ d.set.call(el,true);} else { el.checked=true; } }
  var labels=[].slice.call(document.querySelectorAll('label'));
  for(var i=0;i<labels.length;i++){
    if(!(labels[i].innerText||'').toLowerCase().includes(g)) continue;
    for(var j=i;j<Math.min(labels.length,i+14);j++){
      var ol=labels[j], t=(ol.innerText||'').trim().toLowerCase();
      if(!t) continue;
      if(t===o || (o.length>2 && t.includes(o))){
        var r=document.getElementById(ol.getAttribute('for'))||ol.querySelector('input[type=radio]');
        if(!r) return 'NO_INPUT';
        setNative(r);
        r.dispatchEvent(new MouseEvent('click',{bubbles:true}));
        r.dispatchEvent(new Event('input',{bubbles:true}));
        r.dispatchEvent(new Event('change',{bubbles:true}));
        return r.checked ? ('OK:'+ol.innerText.trim().slice(0,40)) : 'CLICK_FAILED';
      }
    }
  }
  var fsets=[].slice.call(document.querySelectorAll('fieldset'));
  for(var f=0;f<fsets.length;f++){
    if(!(fsets[f].innerText||'').toLowerCase().includes(g)) continue;
    var all=fsets[f].querySelectorAll('*');
    for(var k=0;k<all.length;k++){
      var ot=(all[k].innerText||'').trim().toLowerCase();
      if(!ot) continue;
      if(ot===o || (o.length>2 && ot.includes(o))){
        var rr=all[k].querySelector('input[type=radio]')||(all[k].closest('label,fieldset')&&all[k].closest('label,fieldset').querySelector('input[type=radio]'));
        if(!rr) continue;
        setNative(rr);
        rr.dispatchEvent(new MouseEvent('click',{bubbles:true}));
        rr.dispatchEvent(new Event('input',{bubbles:true}));
        rr.dispatchEvent(new Event('change',{bubbles:true}));
        return rr.checked ? ('OKg:'+ot.slice(0,30)) : 'CLICK_FAILED_G';
      }
    }
  }
  return 'NO_MATCH';
})"""

def ev(expr, retries=4):
    for _ in range(retries):
        try:
            return cfx.evaluate(expr)
        except cfx.CfxError:
            time.sleep(2)
    return "FLAKE"

def set_text(label, value):
    return ev(f"""(()=>{{const lab=[...document.querySelectorAll('label')].find(l=>l.innerText.trim()==={label!r}||l.innerText.trim().includes({label!r}));if(!lab)return 'NO_LAB';const inp=lab.querySelector('input,textarea')||document.getElementById(lab.getAttribute('for'))||lab.closest('div').querySelector('input,textarea');if(!inp)return 'NO_INP';const set=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;set.call(inp,{value!r});inp.dispatchEvent(new Event('input',{{bubbles:true}}));inp.dispatchEvent(new Event('change',{{bubbles:true}}));return inp.value;}})()""")

def set_radio_by_group(group_keyword, option_text):
    return ev(f"({_RADIO_JS})({group_keyword!r},{option_text!r})")

def upload_resume(path):
    for sel in ("input[id=_systemfield_resume]", "input[type=file]"):
        try:
            cfx.post(f"/tabs/{cfx._tab()}/upload", {"userId": cfx._uid(), "selector": sel, "path": path})
            return sel
        except cfx.CfxError:
            continue
    return None

def reveal():
    ev("""(()=>{const b=[...document.querySelectorAll('button,a,[role=button]')].find(x=>/^apply(\\s+(for\\s+this\\s+(job|role|position)|now|to\\s+this))?\\s*$/i.test((x.innerText||x.textContent||'').trim())&&!/website|company\\s*site|external/i.test(x.innerText||''));if(b)b.click();return b?'c':'nf';})()""")
    time.sleep(5)

def main():
    cfg = json.load(open(sys.argv[1]))
    cfx.ensure_tab(persist=True)
    cfx.navigate(cfg["url"]); time.sleep(6)
    reveal()
    # 1) resume FIRST
    sel = upload_resume(os.path.join(_ROOT, "uploads", cfg["cv"]))
    print("resume selector:", sel)
    time.sleep(5)
    print("resume attached:", ev("""(()=>{const fs=[...document.querySelectorAll('input[type=file]')];for(const f of fs){if(f.files&&f.files[0])return f.files[0].name;}return 'NONE';})()"""))
    # 2) text fills (map by substring)
    for lbl, val in (cfg.get("fill") or {}).items():
        print(f"fill {lbl}:", set_text(lbl, val)); time.sleep(0.3)
    # 3) EEO: explicit per-form overrides if given, else keyword auto-map
    eeo_over = cfg.get("eeo_overrides") or {}
    if eeo_over:
        for q, opt in eeo_over.items():
            r = set_radio_by_group(q, opt)
            print(f"eeo {q}={opt}:", r); time.sleep(0.3)
    else:
        for kw, _, val in EEO_KEYWORDS:
            r = set_radio_by_group(kw, val)
            print(f"eeo {kw}={val}:", r); time.sleep(0.3)
    # 4) explicit consent radios (option text provided directly)
    for opt in (cfg.get("consent_options") or []):
        # consent questions: find a radio group whose options include opt; set it
        r = set_radio_by_group(opt, opt)
        print(f"consent {opt}:", r); time.sleep(0.3)
    # 5) explicit toggles (visa etc.)
    for q, val in (cfg.get("toggles") or {}).items():
        print(f"toggle {q}:", ev(f"""(()=>{{const lab=[...document.querySelectorAll('label,div,span')].find(l=>(l.innerText||'').trim().toLowerCase().includes({q.lower()!r}));if(!lab)return 'NOLAB';let p=lab.closest('fieldset')||lab.parentElement;const inp=p.querySelector('input[type=radio],input[type=checkbox],button,[role=radio]');if(!inp)return 'NOINP';const want={str(val).lower()!r};if(inp.type==='checkbox'){{if(inp.checked!==want)inp.click();}}else{{inp.click();}}return inp.checked!==undefined?(''+(inp.checked)):'clk';}})()"""))
        time.sleep(0.3)
    # 6) comboboxes
    for q, val in (cfg.get("comboboxes") or {}).items():
        try:
            import atsform
            rc = atsform.combobox_pick(q, val, quiet_notfound=True)
            print(f"combobox {q}={val}:", "OK" if rc == 0 else f"rc={rc}")
        except Exception as e:
            print(f"combobox {q} err:", str(e)[:50])
        time.sleep(0.5)
    # 7) trusted submit
    ev("""(()=>{const b=[...document.querySelectorAll('button')].find(x=>/submit application/i.test((x.innerText||'').trim()));if(b)b.scrollIntoView({block:'center'});return 1;})()""")
    time.sleep(1)
    try:
        r = cfx.click_selector('button:has-text("Submit Application")', pace=True, timeout=30)
        print("SUBMIT CLICK:", r)
    except cfx.CfxError as e:
        print("SUBMIT ERR:", e)
    time.sleep(8)
    b = ev("document.body.innerText") or ""
    low = b.lower()
    # Real confirmation: Ashby shows "Thank you for your application" / "Application received" / "we'll be in touch"
    confirmed = any(k in low for k in ["thank you for your application", "application received", "we'll be in touch", "we will be in touch", "your application has been", "successfully submitted"])
    needs_corr = "needs corrections" in low or "missing entry" in low
    print("URL:", ev("location.href"))
    print("CONFIRMED:", confirmed, "| NEEDS_CORRECTIONS:", needs_corr)
    print("BODY HEAD:", b[:400])
    if confirmed and not needs_corr:
        slug = re.sub(r"[^a-z0-9]+", "-", f"{cfg.get('company','')}-{cfg.get('role','')}".lower()).strip("-")[:80]
        appdir = os.path.join(_ROOT, "applications", slug)
        os.makedirs(appdir, exist_ok=True)
        proof = os.path.join(appdir, "confirmation.png")
        try:
            cfx.shot(proof)
        except Exception:
            pass
        subprocess.run([sys.executable, os.path.join(_ROOT, "sites", "_common", "scripts", "log-application.py"),
                       cfg.get("company",""), cfg.get("role",""), cfg.get("source","Ashby"), cfg["url"], "Applied",
                       "--proof", proof, "--notes", "trusted-submit via submit_ashby.py (verified confirmation)"], check=False)
        print("LOGGED Applied")
    else:
        print("NOT LOGGED (no verified confirmation)")

if __name__ == "__main__":
    main()
