#!/usr/bin/env python3
"""
tal_sec2.py — fill + submit a Civil Service Jobs TAL Section-2 "supporting
evidence" eform (cshr.tal.net/vx/.../candidate/eform/<ID>/page/N).

Key mechanics (learned 2026-07-14):
  * Only clicking the page's "Continue" (a real <input type=submit>) PERSISTS
    that page's data to the server. Typing + blur alone does NOT survive a
    navigation. So we fill a page, then click Continue, for every page.
  * The final (declaration) page has NO Continue — a "Submit" button renders
    only AFTER the declaration checkbox is checked AND the "Full Application
    Form Submitted?" select = "Yes". We detect the final page by spec pages
    list and, on it, fill then click Submit.

Spec shape (spec_ofgem_s2.json / spec_ukef_s2.json):
  {"pages":[1,2,3,...],
   "fields":{ "<name>": {"kind":"textarea|checkbox|select|text", "value": "..."}, ... }}
  Token substitution in string values:
    __CV_EMP__, __CV_SKILLS__, __PS__ -> applications/cabinet-office-user-researcher/*.txt

Usage:
  python3 tal_sec2.py <eform_base_no_slash> <spec.json>
"""
import sys
import os
import json
import time
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "_common", "scripts"))
import cfx  # noqa: E402

_EOFORM = None
APP = os.path.join(HERE, "..", "..", "..", "applications")


def ev(expr, tries=10):
    for _ in range(tries):
        try:
            r = cfx.evaluate(expr)
            if r not in (None, ""):
                return r
        except Exception:
            time.sleep(1)
    return None


def _tok(v):
    if not isinstance(v, str):
        return v
    repl = {
        "__CV_EMP__": os.path.join(APP, "cabinet-office-user-researcher", "cv-employment.txt"),
        "__CV_SKILLS__": os.path.join(APP, "cabinet-office-user-researcher", "cv-skills.txt"),
        "__PS__": os.path.join(APP, "cabinet-office-user-researcher", "personal-statement.txt"),
    }
    for k, path in repl.items():
        if k in v:
            try:
                with open(path) as f:
                    v = v.replace(k, f.read().strip())
            except FileNotFoundError:
                v = v.replace(k, "")
    return v


def set_textarea(name, val):
    return cfx.evaluate(
        "(function(n,v){const e=document.querySelector('textarea[name=\\'"+name+"\\']');"
        "if(!e)return 'NO_FIELD';"
        "const s=Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype,'value').set;"
        "s.call(e,v);e.dispatchEvent(new Event('input',{bubbles:true}));"
        "e.dispatchEvent(new Event('change',{bubbles:true}));"
        "e.dispatchEvent(new Event('blur',{bubbles:true}));return 'OK:'+e.value.length;})"
        "(" + json.dumps(name) + "," + json.dumps(val) + ")")


def set_text(name, val):
    return cfx.evaluate(
        "(function(n,v){const e=document.querySelector('input[name=\\'"+name+"\\']');"
        "if(!e)return 'NO_FIELD';"
        "const s=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;"
        "s.call(e,v);e.dispatchEvent(new Event('input',{bubbles:true}));"
        "e.dispatchEvent(new Event('change',{bubbles:true}));"
        "e.dispatchEvent(new Event('blur',{bubbles:true}));return 'OK:'+e.value.length;})"
        "(" + json.dumps(name) + "," + json.dumps(val) + ")")


def set_checkbox(name, want=True):
    # IDEMPOTENT: click only when the current state differs from `want`. The old code always
    # clicked (toggling), then for a mismatch re-set .checked AND dispatched a synthetic 'click'
    # that toggled AGAIN — so a PRE-checked box (Section 2 persists server-side across re-runs)
    # ended up UNCHECKED, the declaration-gated Submit button never rendered, and the submit
    # silently failed. `.click()` alone toggles + fires native events; 'change' updates Knockout.
    return cfx.evaluate(
        "(function(n,w){const c=document.querySelector('input[name=\\'"+name+"\\']');"
        "if(!c)return 'NO_FIELD';"
        "if(c.checked!==w){c.click();}"
        "c.dispatchEvent(new Event('change',{bubbles:true}));return 'OK:'+c.checked;})"
        "(" + json.dumps(name) + "," + json.dumps(want) + ")")


def set_select(name, want):
    # EXACT match first across ALL options, THEN fall back to substring — the old single-pass
    # `find(exact(x) || substring(x))` was first-either-wins, so a substring hit on an EARLIER
    # option (options=['Greater London','London'], want 'London') beat the exact match and wrote
    # the WRONG value to the submitted Section-2 form. (Same fix pick.py already carries.)
    return cfx.evaluate(
        "(function(n,w){const s=document.querySelector('select[name=\\'"+name+"\\']');"
        "if(!s)return 'NO_FIELD';"
        "const o=[...s.options].find(x=>(x.text||'').trim().toLowerCase()===w.toLowerCase())"
        "||[...s.options].find(x=>(x.text||'').toLowerCase().includes(w.toLowerCase()));"
        "if(!o)return 'NO_OPT:'+[...s.options].map(x=>x.text.trim()).join(',');"
        "s.value=o.value;s.dispatchEvent(new Event('change',{bubbles:true}));"
        "s.dispatchEvent(new Event('input',{bubbles:true}));return 'OK:'+o.text.trim();})"
        "(" + json.dumps(name) + "," + json.dumps(want) + ")")


def set_field(name, kind, val):
    if kind == "textarea":
        return set_textarea(name, _tok(val))
    if kind == "text":
        return set_text(name, _tok(val))
    if kind == "checkbox":
        return set_checkbox(name, val)
    if kind == "select":
        return set_select(name, val)
    return "BAD_KIND:" + kind


def click_button_by_label(label):
    return ev("""(() => {
      const bs=[...document.querySelectorAll('button,input[type=submit],a')];
      const b=bs.find(e=>(e.innerText||e.value||'').trim().toLowerCase()===%s);
      if(!b) return 'NO_BTN';
      b.click();
      return 'clicked';
    })()""" % json.dumps(label))


def click_continue_or_submit(final=False):
    """On non-final pages click 'Continue'; on the final page click 'Submit'
    (only present after declaration fields are filled)."""
    label = "submit" if final else "continue"
    for _ in range(4):
        r = click_button_by_label(label)
        if r == "clicked":
            time.sleep(3)
            return label
        time.sleep(1.5)
    return "NO_BTN"


def problem_text():
    b = cfx.evaluate("document.body.innerText")
    if not b:
        return "(no body)"
    b = b.replace("\n", " ")
    i = b.find("There is a problem")
    return b[i:i + 400] if i >= 0 else b[-300:]


def fill_page(pg, spec):
    out = []
    time.sleep(4.5)
    for nm, specfield in spec.get("fields", {}).items():
        kind = specfield.get("kind")
        val = specfield.get("value")
        out.append((f"{kind} {nm}", set_field(nm, kind, val)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("eform_base")
    ap.add_argument("spec")
    a = ap.parse_args()
    global _EOFORM
    _EOFORM = a.eform_base.rstrip("/")
    spec = json.load(open(a.spec))
    pages = spec.get("pages", [1, 2, 3])
    last = max(pages)

    for pg in pages:
        cfx.navigate(f"{_EOFORM}/page/{pg}")
        cfx.poll("document.readyState", predicate=lambda r: r == "complete", timeout=25)
        print(f"=== page {pg} ===", flush=True)
        for label, r in fill_page(pg, spec):
            print(f"  {label}: {r}", flush=True)
        final = (pg == last)
        btn = click_continue_or_submit(final=final)
        time.sleep(3)
        url = ev("location.href")
        print(f"  advance -> {btn} | url {url}", flush=True)
        if not final:
            print(f"  savepage: {problem_text()}", flush=True)

    url = ev("location.href")
    print(f"FINAL url: {url}", flush=True)
    print(f"FINAL: {problem_text()}", flush=True)


if __name__ == "__main__":
    main()
