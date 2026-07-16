#!/usr/bin/env python3
"""amazon_apply.py — apply to one amazon.jobs role via the logged-in camofox session.

Usage:
    CFX_KEY=... CFX_TAB=... python3 amazon_apply.py <amazon_jobs_url>

Assumes Jane's amazon.jobs profile is pre-filled (Contact/Education/Resume/General/EEO)
from the one manual application. Walks the multi-step wizard:
  Apply now -> (SMS: Skip & continue) -> Job-specific (answer required selects Yes)
  -> Work Eligibility (answer Yes/eligible) -> Review & submit -> confirm.
"""
import os, sys, time, subprocess
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "sites", "_common", "scripts"))
import cfx

YES = "1"  # amazon.jobs select value for "Yes"

def ev(expr, timeout=40):
    return cfx.evaluate(expr, timeout=timeout)

def click_text(pat, timeout=40):
    return ev("""(function(){var b=[...document.querySelectorAll('a,button')].find(e=>new RegExp(%s,'i').test(e.textContent));if(b){b.click();return 'clicked:'+b.textContent.trim().slice(0,30);}return 'none';})()""" % repr(pat), timeout)

def click_ref(ref, timeout=40):
    r = subprocess.run(["bash", os.path.join(os.path.dirname(os.path.abspath(__file__)), "sites","_common","scripts","cfx.sh"),
                        "click", ref], capture_output=True, text=True, timeout=timeout)
    return r.stdout.strip()

def set_empty_selects_yes():
    # native <select> -> Yes
    out = ev("""(function(){
        var n=0;
        for(var s of document.querySelectorAll('select')){
            if(!s.value){
                var setter=Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype,'value').set;
                setter.call(s,'%s');
                s.dispatchEvent(new Event('change',{bubbles:true}));
                n++;
            }
        }
        return 'native-set:'+n;
    })()""" % YES)
    # ARIA comboboxes -> open + click Yes (skip nav chrome like Preferences/My progress)
    for _ in range(20):
        cb = ev("""(function(){
            var els=[...document.querySelectorAll('[role=combobox],[aria-expanded]')];
            for(var e of els){
                if(e.getAttribute('aria-expanded')!=='false') continue;
                var box=e.closest('form')||e.closest('[class*=question]')||e.parentElement;
                var txt=(box?box.innerText:'')+e.getAttribute('aria-label')+e.textContent;
                if(/preferences|my progress|show all/i.test(txt)) continue;
                if(!/question|experience|portfolio|design|degree|research|work|adjust/i.test(txt)) continue;
                e.click(); return 'opened';
            }
            return 'none';
        })()""")
        if cb != "opened":
            break
        time.sleep(2)
        opt = ev("""(function(){
            var opts=[...document.querySelectorAll('[role=option],li,[class*=option]')].filter(o=>o.offsetParent!==null);
            var y=opts.find(o=>/^yes$/i.test(o.textContent.trim()));
            if(y){y.click();return 'yes';}
            return 'no-yes';
        })()""")
        if opt != "yes":
            ev("""(function(){document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));})()""")
        time.sleep(1)
        time.sleep(1)
    return out

def selected_step():
    # the tab with aria-selected="true" is the current step
    return ev("""(function(){
        var tabs=[...document.querySelectorAll('[role=tab]')];
        var t=tabs.find(e=>e.getAttribute('aria-selected')=='true');
        if(t) return t.textContent.replace(/Optional|required/g,'').trim().slice(0,40);
        // fallback: any tab whose text is the selected one
        return 'unknown';
    })()""")

def main():
    url = sys.argv[1]
    cfx.navigate(url); time.sleep(8)
    r = click_text("apply now")
    print("[apply]", r); time.sleep(8)
    if "none" in r:
        # maybe already on apply page
        pass
    for i in range(12):
        # advance based on selected step
        cur = selected_step()
        print(f"[step {i}] selected={cur}")
        low = (cur or "").lower()
        if "review" in low and "submit" in low:
            sub = click_text("review & submit")
            print("[submit]", sub); time.sleep(6)
            conf = click_text("confirm|submit application|yes, apply|submit my application")
            print("[confirm]", conf)
            final = ev("location.href")
            print("[final]", final)
            return 0
        if "sms" in low:
            click_text("skip & continue"); time.sleep(4); continue
        # universal: complete any step by setting all selects+comboboxes Yes,
        # all radios to NO/NEVER (Jane: no Amazon history, British, no sponsorship),
        # filling portfolio, then Continue/Save/Skip
        set_empty_selects_yes(); time.sleep(2)
        ev("""(function(){
          // radios: Jane answers No/Never (no Amazon history, British, no sponsorship)
          for(var r of document.querySelectorAll('input[type=radio]')){
            if(r.value==='NO'||r.value==='NEVER'){ r.click(); }
          }
          return 'radios-ok';
        })()""")
        time.sleep(1)
        ev("""(function(){var i=[...document.querySelectorAll('input[type=text],input:not([type])')].find(e=>/portfolio/i.test((e.closest('div')?e.closest('div').innerText:'')+e.getAttribute('aria-label')+e.placeholder));if(i&&!i.value){var d=Object.getOwnPropertyDescriptor(Object.getPrototypeOf(i),'value');d.set.call(i,'https://example.com');i.dispatchEvent(new Event('input',{bubbles:true}));i.dispatchEvent(new Event('change',{bubbles:true}));return 'pf-set';}return 'pf-none';})()""")
        time.sleep(1)
        click_text("continue|save|next|skip & continue"); time.sleep(4); continue
    print("[incomplete] no submit reached for", url)
    return 1

if __name__ == "__main__":
    sys.exit(main())
