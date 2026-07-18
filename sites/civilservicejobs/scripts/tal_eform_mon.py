#!/usr/bin/env python3
"""Monitored OFGEM/CPS Section-1 submitter. Navigates each page explicitly,
fills fields, clicks Continue, and after each advance prints URL + any
validation problem so we can see exactly where it sticks. Reuses tal_eform's
field setters (native .click() for radios/checkboxes, setter+events for text)."""
import sys
import os
import json
import time
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "_common", "scripts"))
import cfx  # noqa: E402
sys.path.insert(0, HERE)
import tal_eform as T  # noqa: E402

_EOFORM = None
LOG = []


def ev(expr, tries=10):
    for _ in range(tries):
        try:
            r = cfx.evaluate(expr)
            if r not in (None, ""):
                return r
        except Exception:
            time.sleep(1)
    return None


def problem():
    b = ev("document.body.innerText")
    if not b:
        return "(no body)"
    b = b.replace("\n", " ")
    i = b.find("There is a problem")
    return (b[i:i + 350] if i >= 0 else b[-250:])


def fill_page(pg, spec):
    cfx.navigate(f"{_EOFORM}/page/{pg}")
    cfx.poll("document.readyState", predicate=lambda r: r == "complete", timeout=25)
    time.sleep(4.5)
    out = []
    for nm, val in spec.get("text", {}).items():
        out.append((nm, T._set_field(nm, "text", val)))
    for nm, val in spec.get("textarea", {}).items():
        out.append((nm, T._set_field(nm, "textarea", val)))
    for nm, val in spec.get("select", {}).items():
        out.append((nm, T._set_field(nm, "select", val)))
    for nm, val in spec.get("radio", {}).items():
        out.append((nm, T._set_field(nm, "radio", val)))
    for nm in spec.get("checkbox", {}):
        out.append((nm, T._set_field(nm, "checkbox", True)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("eform_base")
    ap.add_argument("spec")
    a = ap.parse_args()
    global _EOFORM
    _EOFORM = a.eform_base.rstrip("/")
    spec = json.load(open(a.spec))
    pages = spec.get("_pages", [1, 2, 3, 4, 5])
    for pg in pages:
        res = fill_page(pg, spec)
        bad = [f"{n}={r}" for n, r in res if str(r).startswith("NO_FIELD")]
        print(f"=== page {pg} === fill: {len(res)} fields, missing={bad}", flush=True)
        before = ev("location.href")
        # click Continue (or Submit on last page)
        ev("""(() => {
          const bs=[...document.querySelectorAll('button,input[type=submit]')];
          const sub=bs.find(e=>(e.innerText||e.value||'').trim().toLowerCase()==='submit');
          const cont=bs.find(e=>(e.innerText||e.value||'').trim().toLowerCase()==='continue');
          const b=sub||cont; if(b) b.click(); return b? (sub?'submit':'continue'):'NONE';
        })()""")
        time.sleep(4)
        after = ev("location.href")
        print(f"  advance: {before[-10:]} -> {after[-10:]} {'OK' if after!=before else 'STUCK'}", flush=True)
        if after == before:
            print(f"  PROBLEM: {problem()}", flush=True)
            # try once more after a beat
            ev("""(() => {const b=[...document.querySelectorAll('button,input[type=submit]')].find(e=>(e.innerText||e.value||'').trim().toLowerCase()==='continue');if(b)b.click();})()""")
            time.sleep(4)
            after2 = ev("location.href")
            print(f"  retry: {after2[-10:]} {'OK' if after2!=before else 'STUCK'}", flush=True)
            if after2 == before:
                print("  GIVING UP on this page.", flush=True)
                break
    print(f"FINAL url: {ev('location.href')}", flush=True)
    print(f"FINAL: {problem()}", flush=True)


if __name__ == "__main__":
    main()
