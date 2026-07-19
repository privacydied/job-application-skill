#!/usr/bin/env python3
import sys, json, time
sys.path.insert(0, 'sites/_common/scripts')
import cfx

def options_for(label_sub):
    sel = cfx.evaluate(
        "(function(){"
        "  var lab=" + json.dumps(label_sub.lower()) + ";"
        "  var labs=[].slice.call(document.querySelectorAll('label'));"
        "  for(var i=0;i<labs.length;i++){if(labs[i].innerText.trim().toLowerCase().indexOf(lab)>=0){"
        "    if(labs[i].id&&/-label$/.test(labs[i].id)){var b=document.getElementById(labs[i].id.replace(/-label$/,''));if(b&&b.id)return 'input[id=\"'+b.id+'\"]';}"
        "    var c=labs[i].querySelector('input,select');if(c&&c.id)return 'input[id=\"'+c.id+'\"]';"
        "    var w=labs[i].closest('.select__container');if(w){var c2=w.querySelector('input.select__input,input[type=text],select');if(c2&&c2.id)return 'input[id=\"'+c2.id+'\"]';}"
        "  }}"
        "  return '';"
        "})()")
    if not sel:
        return '(no field)'
    try:
        cfx.click_selector(sel, pace=False)
    except Exception as e:
        return f'ERR click {e}'
    time.sleep(1.0)
    opts = cfx.evaluate(
        "(function(){var o=[].slice.call(document.querySelectorAll('[role=option], li[role=option]'));"
        "return o.map(function(x){return x.innerText.trim();});})()")
    try:
        cfx.press("Escape")
    except Exception:
        pass
    time.sleep(0.3)
    return opts

cfx.goto("https://job-boards.greenhouse.io/gocardless/jobs/7996584")
time.sleep(1.5)
for lab in ["sponsor a work visa", "pay range transparency", "willing to commute", "your privacy at gocardless",
            "which gender do you identify as", "race/ethnicity", "sexual orientation",
            "consider yourself disabled", "neurodiverse"]:
    print(lab, "=>", options_for(lab))
