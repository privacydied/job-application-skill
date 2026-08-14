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


# NOTE (2026-08-14): there used to be a *Python* `near_label(el)` here that the injected JS
# below called as `near_label(el)`. Python functions do not exist in the page's JS context, so
# every call threw `ReferenceError: near_label is not defined`, the whole IIFE threw, and the
# backend turned that into `HTTP 500 Internal server error`. i.e. this probe — the thing
# SKILL.md tells you to run BEFORE driving any Greenhouse posting, precisely so you don't burn
# the 2-attempt budget on a blind form — could never have produced output. Its docstring's
# promised behaviour was fiction. The label lookup is now implemented in JS, inline, below.


js = r"""(function(){
  var out = [];
  function lab(el){
    var p = el.closest('label');
    if (p) return p.textContent.replace(/\s+/g,' ').trim();
    // Greenhouse often puts the <label> as a SIBLING or on an ancestor wrapper rather than
    // wrapping the control, so walk up a few levels looking for one.
    var c = el;
    for (var i=0; i<4; i++){
      c = c.parentElement;
      if (!c) break;
      var l = c.querySelector('label');
      if (l) return l.textContent.replace(/\s+/g,' ').trim();
    }
    // Last resort: aria-label / aria-labelledby / name, so a control is still identifiable.
    var al = el.getAttribute && (el.getAttribute('aria-label') || '');
    if (al) return al.replace(/\s+/g,' ').trim();
    var lb = el.getAttribute && el.getAttribute('aria-labelledby');
    if (lb){
      var t = document.getElementById(lb);
      if (t) return t.textContent.replace(/\s+/g,' ').trim();
    }
    return (el.getAttribute && el.getAttribute('name')) || '(unlabeled)';
  }
  // REQUIRED-DETECTION (2026-08-14). Greenhouse does NOT set the HTML `required` attribute on
  // most of its custom questions — it marks them with a trailing `*` in the label and enforces
  // them in React on submit. Reading only `el.required` therefore UNDER-reports required
  // fields, which is the one thing this probe exists to get right: a required essay reported
  // as `req=False` gets left out of the gh_apply config, the first submit bounces with
  // "This field is required.", and (worse) Greenhouse never sends the emailed security code
  // for a submit it rejected — so the run then reports a bogus `CODE_MISSING` and logs
  // Blocked, blaming the mailbox for a missing-field bug. Cost a real application
  // (Capital on Tap, Product Designer) before being spotted.
  // Truth = the HTML attribute OR a `*` on the label (the same rule the rselect branch below
  // already used).
  function req(el, label){
    if (el && el.required) return true;
    if (el && el.getAttribute && el.getAttribute('aria-required') === 'true') return true;
    return /\*\s*$/.test((label||'').trim()) || /\*/.test(label||'');
  }
  var sels = [].slice.call(document.querySelectorAll('select'));
  for(var s of sels){
    var opts=[].slice.call(s.options).map(function(o){return o.textContent.trim();});
    var sl=lab(s);
    out.push({t:'select', label:sl, req:req(s,sl), opts:opts.slice(0,12)});
  }
  var rs=[].slice.call(document.querySelectorAll('.select__container, [class*=remix-css]'));
  for(var r of rs){
    var inp=r.querySelector('input'); if(!inp) continue;
    var l=r.querySelector('label');
    out.push({t:'rselect', label:(l?l.textContent.replace(/\s+/g,' ').trim():lab(inp)), req:/\*/.test((l?l.textContent:'')), ph:(inp.getAttribute('placeholder')||'')});
  }
  var tas=[].slice.call(document.querySelectorAll('textarea'));
  for(var ta of tas){ var tl=lab(ta); out.push({t:'essay', label:tl, req:req(ta,tl), len:(ta.value||'').length}); }
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


def main():
    if len(sys.argv) < 2:
        print("usage: inspect_gh_form.py <greenhouse-url>", file=sys.stderr)
        return 2
    url = sys.argv[1]
    cfx.goto(url)
    time.sleep(2)
    res = cfx.evaluate(js) or []

    # DEDUPE (2026-08-14): the react-select probe selector
    # `.select__container, [class*=remix-css]` matches several NESTED wrappers around the
    # same control, so every dropdown was printed ~5x — 60+ lines of noise for a 12-field
    # form, which buries the ESSAY/required rows you actually need to build the config.
    # Collapse on (type, label), keeping the first occurrence, which is the outermost
    # wrapper and the one carrying the real `required` marker.
    seen = set()
    deduped = []
    for f in res:
        key = (f.get("t"), f.get("label"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(f)
    dropped = len(res) - len(deduped)

    for f in deduped:
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

    if dropped:
        print(f"\n({dropped} duplicate nested-wrapper rows collapsed)")

    # REQUIRED CHECKLIST — the actionable summary. Every one of these must appear in the
    # gh_apply config's "fill"/"combo" or the submit WILL bounce (and on Greenhouse a bounced
    # submit also means no security-code email, which then looks like a mailbox failure).
    # NOTE: `text` is included deliberately. Leaving it out hid "Preferred First Name is
    # required." on Cognism — the probe printed a clean checklist, the config was built from
    # it, and the submit bounced on a field the checklist had promised was complete. A
    # checklist that is silently partial is worse than no checklist, because it is trusted.
    needed = [f for f in deduped if f.get("req") and f["t"] in ("select", "rselect", "essay", "text")]
    if needed:
        print("\n⛔ REQUIRED — every one of these needs a config entry:")
        for f in needed:
            where = "combo" if f["t"] in ("select", "rselect") else "fill"
            print(f"  [{where:5s}] {f['label'][:88]}")


if __name__ == "__main__":
    sys.exit(main())
