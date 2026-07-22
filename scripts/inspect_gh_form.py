#!/usr/bin/env python3
"""inspect_gh_form.py — dump a Greenhouse apply form's required fields + control types.

WHY (2026-07-20): before driving any Greenhouse posting, you must know which required
fields exist and HOW they're rendered, because a meaningful fraction of live postings have
required react-selects that render with NO options (broken employer-side form) and are
undrivable walls. Driving blind burns the 2-attempt budget on a structural wall. This probe
prints every required field + its control type (text / textarea / react-select / native
select / checkbox) so a correct gh_apply config can be built in ONE shot — and so a
"No options" react-select is caught BEFORE you try to submit.

USAGE (needs live CFX_TAB):
  python3 scripts/inspect_gh_form.py <greenhouse-url>

OUTPUT: one line per control:
  [SELECT] <label> req=<bool> opts=[...]
  [RSELECT] <label> req=<bool> ph='<placeholder>'
  [ESSAY] <label> req=<bool> len=<n>
  [TEXT*] <label> ='<current value>'
  [CHECK] <label> checked=<bool>

A react-select with no options (opening it shows []) is a WALL — log Blocked, do not retry.
Requires: sites/_common/scripts/cfx.py on PYTHONPATH (run from the skill root).
"""
import sys
import time
sys.path.insert(0, "sites/_common/scripts")
import cfx  # noqa: E402

url = sys.argv[1]
cfx.goto(url)
time.sleep(2)


def near_label(el):
    p = el.closest("label")
    if p:
        return p.textContent.replace("\\s+", " ").strip()
    c = el
    for _ in range(4):
        c = c.parentElement
        if not c:
            break
        l = c.querySelector("label")
        if l:
            return l.textContent.replace("\\s+", " ").strip()
    return "(unlabeled)"


js = r"""(function(){
  var out = [];
  function lab(el){ return near_label(el); }
  var sels = [].slice.call(document.querySelectorAll('select'));
  for(var s of sels){
    var opts=[].slice.call(s.options).map(function(o){return o.textContent.trim();});
    out.push({t:'select', label:lab(s), req:!!s.required, opts:opts.slice(0,12)});
  }
  var rs=[].slice.call(document.querySelectorAll('.select__container, [class*=remix-css]'));
  for(var r of rs){
    var inp=r.querySelector('input'); if(!inp) continue;
    var l=r.querySelector('label');
    out.push({t:'rselect', label:(l?l.textContent.replace(/\s+/g,' ').trim():lab(inp)), req:/\*/.test((l?l.textContent:'')), ph:(inp.getAttribute('placeholder')||'')});
  }
  var tas=[].slice.call(document.querySelectorAll('textarea'));
  for(var ta of tas){ out.push({t:'essay', label:lab(ta), req:!!ta.required, len:(ta.value||'').length}); }
  var ins=[].slice.call(document.querySelectorAll('input'));
  for(var i of ins){
    if(i.type=='hidden'||i.type=='file'||i.type=='checkbox'||i.type=='radio') continue;
    if(!i.required) continue;
    var l=lab(i); if(l=='(unlabeled)') continue;
    out.push({t:'text', label:l, val:(i.value||'').slice(0,30)});
  }
  var cbs=[].slice.call(document.querySelectorAll('input[type=checkbox]'));
  for(var c of cbs){ var l=lab(c); if(l&&l!='(unlabeled)') out.push({t:'check', label:l.slice(0,60), chk:c.checked}); }
  return out;
})()"""
res = cfx.evaluate(js) or []
for f in res:
    if f["t"] == "select":
        print(f"[SELECT] {f['label'][:50]} req={f['req']} opts={f['opts'][:6]}")
    elif f["t"] == "rselect":
        print(f"[RSELECT] {f['label'][:50]} req={f['req']} ph='{f['ph']}'")
    elif f["t"] == "essay":
        print(f"[ESSAY] {f['label'][:55]} req={f['req']} len={f['len']}")
    elif f["t"] == "text":
        print(f"[TEXT*] {f['label'][:50]} ='{f['val']}'")
    elif f["t"] == "check":
        print(f"[CHECK] {f['label'][:55]} checked={f['chk']}")
