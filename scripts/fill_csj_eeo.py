#!/usr/bin/env python3
"""fill_csj_eeo.py — drive the required "Civil Service UK Diversity Questions"
react-selects on a CSJ Greenhouse apply form.

WHY (2026-07-21): `gh_apply.py`'s shared `combobox_pick` / `_fill_eeo` FAILS on these
CSJ EEO selects — they are async (menu mounts ~1s after open, and closes between
two separate evaluate calls), only mount when scrolled into view, and their
"I don't wish to answer" option uses a curly apostrophe (U+2019) that breaks an
exact straight-quote match. Verified fix in `references/greenhouse-csj-eeo-react-select.md`.

USAGE (needs live CFX_TAB on the opened Greenhouse form):
  python3 scripts/fill_csj_eeo.py            # fill the standard "I don't wish to answer" set
  python3 scripts/fill_csj_eeo.py --show     # just dump all EEO select ids + current value + options
  python3 scripts/fill_csj_eeo.py --set <id>:<value> [--set <id>:<value> ...]

The default set autodetects every select inside the "Civil Service UK Diversity
Questions" section and sets each to "I don't wish to answer" (the truthful choice
when the applicant's real answer is unknown — never fabricate a specific demographic).
A value containing a curly quote is matched after normalizing both sides.

Requires: sites/_common/scripts/cfx.py on PYTHONPATH (run from the skill root).
"""
import argparse
import json
import subprocess
import sys
import time

_ROOT = "/var/services/homes/pry/.hermes/skills/productivity/job-application"
sys.path.insert(0, f"{_ROOT}/sites/_common/scripts")
import cfx  # noqa: E402

WISH = "I don't wish to answer"  # note: literal straight quote here; normalized on compare


def _eval(js):
    # Route through the shell wrapper — python cfx.evaluate 500s on heavy Greenhouse pages.
    out = subprocess.run(
        ["bash", f"{_root}/sites/_common/scripts/cfx.sh", "eval", js],
        capture_output=True, text=True, cwd=_ROOT,
    )
    raw = out.stdout.strip()
    try:
        return json.loads(raw).get("result")
    except Exception:
        return raw


def discover():
    """Return list of {id, label, value, options} for the CSJ diversity selects."""
    js = r"""(async function(){
      var secs=[].slice.call(document.querySelectorAll('h1,h2,h3,h4,legend,fieldset'));
      var sec=null;
      for(var s of secs){ if(/Civil Service UK Diversity Questions/i.test(s.textContent)){sec=s;break;} }
      if(!sec) return 'NO_SECTION';
      var root=sec; while(root && root.parentElement && root.querySelectorAll('select,input').length<3) root=root.parentElement;
      var ins=[].slice.call(root.querySelectorAll('input[type=text]'));
      var out=[];
      for(var e of ins){
        var ctrl=e.closest('.select__control'); if(!ctrl) continue;
        var lab=document.querySelector('label[for="'+e.id+'"]');
        var ph=e.getAttribute('placeholder')||'';
        out.push({id:e.id, label:lab?lab.textContent.replace(/\s+/g,' ').trim().slice(0,70):ph, value:''});
      }
      return JSON.stringify(out);
    })()"""
    r = _eval(js)
    if r == "NO_SECTION" or isinstance(r, str) and r.startswith("NO_"):
        return []
    try:
        return json.loads(r)
    except Exception:
        return []


def set_select(id_, value):
    """Open + bind one EEO select via the verified async recipe. Returns the bound text."""
    js = r"""(async function(){
      var id=%r, target=%r;
      var e=document.getElementById(id); if(!e) return id+':NOEL';
      e.closest('.select__control').scrollIntoView({block:'center'});
      var ctrl=e.closest('.select__control');
      ['mousedown','mouseup','click'].forEach(function(t){ctrl.dispatchEvent(new MouseEvent(t,{bubbles:true,view:window}));});
      var tries=0, menu=null;
      while(tries<40){ menu=document.querySelector('.select__menu'); if(menu && menu.querySelectorAll('.select__option').length) break; await new Promise(r=>setTimeout(r,50)); tries++; }
      if(!menu) return id+':NOMENU';
      var opts=[].slice.call(menu.querySelectorAll('.select__option'));
      var t=opts.find(function(o){var s=o.textContent.replace(/[  2018  2019]/g,"'").trim().toLowerCase(); return s.indexOf(target.replace(/[  2018  2019]/g,"'").toLowerCase())>=0;});
      if(!t) return id+':NOTARGET';
      t.scrollIntoView({block:'center'});
      ['mousedown','mouseup','click'].forEach(function(ev){t.dispatchEvent(new MouseEvent(ev,{bubbles:true,view:window}));});
      await new Promise(r=>setTimeout(r,250));
      var v=e.closest('.select__control').querySelector('.select__single-value');
      return id+'=BOUND:'+(v?v.textContent.trim():'(empty)');
    })()""" % (id_, value)
    return _eval(js)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true", help="dump EEO select ids+options, don't set")
    ap.add_argument("--set", action="append", default=[], help="<id>:<value> overrides")
    a = ap.parse_args()

    fields = discover()
    if not fields:
        print("NO_SECTION (not on a CSJ Greenhouse diversity form, or section not found)")
        return 1
    if a.show:
        for f in fields:
            print(f"{f['id']} | {f['label']}")
        return 0
    sets = {}
    for ov in a.set:
        i, v = ov.split(":", 1)
        sets[i] = v
    for f in fields:
        val = sets.get(f["id"], WISH)
        res = set_select(f["id"], val)
        print(res)
        time.sleep(0.4)
    return 0


if __name__ == "__main__":
    sys.exit(main())
