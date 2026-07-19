#!/usr/bin/env python3
"""gh_apply.py — drive ONE Greenhouse application end-to-end (guest, account-less).

Single source of truth for Greenhouse submits in this skill. Reads a config JSON:
  {"url": "...", "company": "Monzo", "role": "Machine Learning Platform Engineer",
   "fill": {"<label>": "<value>"},            # JD-specific text answers
   "select": {"<label>": "<option>"},         # native <select> / react-select
   "radios": {"<question>": "<option>"},      # radio groups
   "checkboxes": {"<label>": "on|off"},
   "eeo": true|false,                          # fill EEO/diversity inputs (default true)
   "cover": "<base>.txt",                      # optional cover-letter file in uploads/
   "no_submit": true}                          # fill+review only, don't submit

Hard rules enforced here (not left to the caller):
  * Anti-AI attestation clause on the page => REFUSE (prints REFUSE_ATTESTATION, exit 3).
    We must NOT submit a "use only my own words" form on the applicant's behalf.
  * Upload CV via container path /uploads/base-resume.pdf (host path 400s).
  * EEO answers come from apply-defaults.json -> applicant (gender/ethnicity/etc.) per the
    user's 2026-07-19 instruction; age -> prefer not to say; religion untouched.
  * Logs via log-application.py with --proof ONLY on a captured confirmation.

Proof artifact: applications/<slug>/confirmation.png + .txt, captured after submit.
"""
import json
import os
import re
import subprocess
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(_ROOT, "sites", "_common", "scripts"))

import cfx
import atsform

UPLOADS = os.path.join(_ROOT, "uploads")
APPS = os.path.join(_ROOT, "applications")


def _slug(company, role):
    s = re.sub(r"[^a-z0-9]+", "-", f"{company}-{role}".lower()).strip("-")
    return s[:80]


def _antiai_present():
    return bool(cfx.evaluate(
        r"""(function(){
            var t = document.body ? document.body.innerText : '';
            return /own words|use of AI|AI[- ]generated content|generated content/i.test(t);
        })()"""))


def _upload_and_verify(target, filename):
    """Upload a file to a Greenhouse file input and verify by the filename CHIP
    (Greenhouse moves the file into a chip, so input.files[0] reads NONE — that is
    NORMAL, not a failure). Raises on a genuine upload error."""
    sel = cfx.evaluate(
        "(() => {"
        "  const t = " + json.dumps(target) + ";"
        "  let el = document.getElementById(t.replace(/^#/,''));"
        "  if (el && el.type === 'file') return 'input[id=\"'+el.id+'\"]';"
        "  const tl = t.toLowerCase();"
        "  const files = [...document.querySelectorAll('input[type=file]')];"
        "  const labs = [...document.querySelectorAll('label,span,div,p')]"
        "    .filter(e => e.childElementCount<=2 && e.textContent &&"
        "                e.textContent.toLowerCase().includes(tl) &&"
        "                e.textContent.replace(/\s+/g,' ').trim().length < 80);"
        "  for (const lab of labs) {"
        "    const f = files.find(fi => lab.compareDocumentPosition(fi) & Node.DOCUMENT_POSITION_FOLLOWING);"
        "    if (f && f.id) return 'input[id=\"'+f.id+'\"]';"
        "  }"
        "  return '';"
        "})()")
    if not sel:
        raise RuntimeError(f"no file input for {target!r}")
    cfx.post(f"/tabs/{cfx._tab()}/upload",
             {"userId": cfx._uid(), "selector": sel, "path": filename})
    want = os.path.basename(filename)
    regex = want.replace(".", r"\.")
    chip = cfx.poll(
        "(()=>{const t=document.body.innerText||'';return /" + regex + "/.test(t);})()",
        predicate=lambda r: r is True, timeout=3.0, interval=0.25)
    if not chip:
        raise RuntimeError(f"CV chip '{want}' not visible after upload")
    print(f"OK upload {target!r}: chip={want}")


def _fill_remix_combo(label_sub, value):
    """Fill a Greenhouse Remix combobox (select__input) by clicking the input (resolved via
    its visible label OR enclosing fieldset/legend) and picking the best-matching
    [role=option] from the live listbox. Matching prefers an EXACT (case-insensitive)
    option, then a word-boundary substring, so 'Man' does NOT match 'Isle of Man'.
    Presses Escape first to dismiss any STALE listbox left open by a prior field
    (greenhouse-ats-quirks.md §4: a stray Country listbox masks the real options).
    Returns 'OK' / 'NO_FIELD' / 'NO_OPTION' / 'ERR ...'."""
    def _js_escape(s):
        return json.dumps(s)
    # Close any open listbox so we read THIS field's own options, not a stale one.
    try:
        cfx.press("Escape")
        time.sleep(0.4)
    except Exception:
        pass
    sel = cfx.evaluate(
        "(function(){"
        "  var lab=" + _js_escape(label_sub.lower()) + ";"
        # 1) a <label> (incl. select__label) whose own text contains lab
        "  var labs=[].slice.call(document.querySelectorAll('label'));"
        "  for(var i=0;i<labs.length;i++){"
        "    var lt=labs[i].innerText.trim().toLowerCase();"
        "    if(lt.indexOf(lab)<0) continue;"
        "    if(labs[i].id && /-label$/.test(labs[i].id)){"
        "      var byId=document.getElementById(labs[i].id.replace(/-label$/,''));"
        "      if(byId&&byId.id) return 'input[id=\"'+byId.id+'\"]';"
        "    }"
        "    var inp=labs[i].querySelector('input,select');"
        "    if(inp&&inp.id) return 'input[id=\"'+inp.id+'\"]';"
        "    var cont=labs[i].closest('.select__container,fieldset,div');"
        "    if(cont){ var c2=cont.querySelector('input.select__input,input[type=text],select'); if(c2&&c2.id) return 'input[id=\"'+c2.id+'\"]'; }"
        "  }"
        # 2) fallback: any select__label by text (class-based)
        "  var sl=[].slice.call(document.querySelectorAll('.select__label'));"
        "  for(var k=0;k<sl.length;k++){"
        "    if(sl[k].innerText.trim().toLowerCase().indexOf(lab)>=0){"
        "      var c=sl[k].closest('.select__container');"
        "      if(c){var ci=c.querySelector('input.select__input,input[type=text],select'); if(ci&&ci.id) return 'input[id=\"'+ci.id+'\"]';}"
        "    }"
        "  }"
        # 3) fallback: aria-label / placeholder substring
        "  var els=[].slice.call(document.querySelectorAll('input,select'));"
        "  for(var j=0;j<els.length;j++){"
        "    var al=(els[j].getAttribute('aria-label')||els[j].getAttribute('placeholder')||'').toLowerCase();"
        "    if(al.indexOf(lab)>=0 && els[j].id) return 'input[id=\"'+els[j].id+'\"]';"
        "  }"
        "  return '';"
        "})()")
    if not sel:
        return "NO_FIELD"
    # Use a JS click (evaluate) rather than the paced REST click — the REST /click
    # endpoint hangs (30s timeout) on Remix combobox inputs. A trusted .click() opens
    # the listbox reliably.
    try:
        # The listbox opens on the .select__control WRAPPER, not the inner input.
        cfx.evaluate(f"(()=>{{var e=document.querySelector({json.dumps(sel)});if(!e)return 'NOEL';"
                     f"var ctrl=e.closest('.select__control')||e.parentElement||e;ctrl.click();return 'CLICKED';}})()")
    except Exception as e:
        return f"ERR click {e}"
    # wait for the option listbox to appear (Remix renders it async)
    time.sleep(1.0)
    picked = cfx.evaluate(
        "(function(){"
        "  var opts=[].slice.call(document.querySelectorAll('[role=option], li[role=option]'));"
        "  var want=" + _js_escape(value) + ";"
        "  var wl=want.toLowerCase();"
        "  function norm(s){return (s||'').trim().toLowerCase();}"
        # Remix prepends a COUNTRY list; scan REVERSED so the specific real option (appended
        # last) wins over a country substring (e.g. 'Man' vs 'Isle of Man'). Exact + word
        # boundary only — NO loose substring (would match 'San Marino' on 'no').
        "  for(var i=opts.length-1;i>=0;i--){if(norm(opts[i].innerText)===wl){opts[i].click();return 'OK(exact):'+opts[i].innerText.trim().slice(0,30);}}"
        "  var re=new RegExp('(^|[^a-z])'+want.replace(/[-/\\\\^$*+?.()|[\\]{}]/g,'\\\\$&').toLowerCase()+'([^a-z]|$)');"
        "  for(var k=opts.length-1;k>=0;k--){if(re.test(norm(opts[k].innerText))){opts[k].click();return 'OK(wb):'+opts[k].innerText.trim().slice(0,30);}}"
        "  return 'NO_OPTION';"
        "})()")
    # close any open listbox before returning
    try:
        cfx.press("Escape")
        time.sleep(0.3)
    except Exception:
        pass
    return picked if isinstance(picked, str) else "ERR"


def _fill_eeo():
    """Fill OPTIONAL EEO/diversity Remix comboboxes. These are optional on most forms, so a
    NO_FIELD (field absent) is fine. Uses the applicant facts from apply-defaults.json per the
    user's 2026-07-19 instruction. Labels match the REAL visible text (not 'gender identity'
    which collides with the 'is your gender identity the same as...' Yes/No question)."""
    defaults = json.load(open(os.path.join(_ROOT, "sites", "_common", "apply-defaults.json")))
    a = defaults.get("applicant", {})
    mapping = [
        ("which gender do you identify as", a.get("gender_identity")),
        ("sexual orientation", a.get("sexual_orientation")),
        ("race/ethnicity", a.get("ethnicity")),
        ("consider yourself disabled", a.get("disability")),
        ("neurodiverse", "No"),
    ]
    done = []
    for label_sub, val in mapping:
        if not val:
            continue
        rc = _fill_remix_combo(label_sub, val)
        done.append((label_sub, val, rc))
    try:
        atsform.fill("pronouns", defaults.get("select", {}).get("Pronouns", "He/him"))
    except Exception:
        pass
    return done


def _log(company, role, source, url, status, note=None, proof=None):
    cmd = ["python3", os.path.join(_ROOT, "sites", "_common", "scripts", "log-application.py"),
           company, role, source, url, status]
    if proof:
        cmd += ["--proof", proof]
    if note:
        cmd += ["--note", note]
    subprocess.run(cmd, cwd=_ROOT)


def main():
    cfg_path = sys.argv[1]
    cfg = json.load(open(cfg_path))
    url = cfg["url"]
    company = cfg["company"]
    role = cfg["role"]
    slug = _slug(company, role)
    appdir = os.path.join(APPS, slug)
    os.makedirs(appdir, exist_ok=True)

    r = cfx.goto(url)
    if not r.get("ok"):
        print(f"NAV_FAIL {url} {r}")
        return 2
    time.sleep(1.0)

    if _antiai_present():
        print(f"REFUSE_ATTESTATION {company} {role} — anti-AI clause present; skipping per hard stop")
        _log(company, role, "Greenhouse", url, "Skipped",
             note="anti-AI attestation clause — hard stop, not submitted", proof=None)
        return 3

    try:
        _upload_and_verify("#resume", "/uploads/base-resume.pdf")
    except Exception as e:
        print(f"RESUME_UPLOAD_FAIL {e}")
        return 4

    cover = cfg.get("cover")
    if cover:
        try:
            atsform.upload("#cover_letter", f"/uploads/{cover}")
        except Exception as e:
            print(f"COVER_UPLOAD_WARN {e}")

    apply_cfg = {"defaults": True, "fill": cfg.get("fill", {}),
                 "select": cfg.get("select", {}), "radios": cfg.get("radios", {}),
                 "checkboxes": cfg.get("checkboxes", {})}
    tmp = os.path.join(appdir, "apply.json")
    json.dump(apply_cfg, open(tmp, "w"))
    try:
        atsform.apply(tmp, do_submit=False)
    except Exception as e:
        print(f"FILL_WARN {e}")

    for frag in ("UK Right to Work", "right to work"):
        try:
            atsform.radio(frag, "Yes")
            break
        except Exception:
            pass

    if cfg.get("eeo", True):
        eeo = _fill_eeo()
        for lab, val, rc in eeo:
            print(f"  eeo {lab!r}={val!r} -> {rc}")

    # Required non-EEO Remix comboboxes (per-company, from config "combo")
    for label_sub, val in cfg.get("combo", {}).items():
        rc = _fill_remix_combo(label_sub, val)
        print(f"  combo {label_sub!r}={val!r} -> {rc}")

    if cfg.get("no_submit"):
        print(f"FILLED_ONLY {company} {role}")
        return 0

    try:
        cfx.shot(os.path.join(appdir, "review.png"))
    except Exception as e:
        print(f"SHOT_WARN {e}")

    try:
        atsform.submit("Submit application",
                       "thank you for applying|application (received|sent)|we.?re rooting|successfully submitted")
    except Exception as e:
        print(f"SUBMIT_ERR {e}")
    txt = ""
    try:
        txt = cfx.evaluate("document.body?document.body.innerText:''") or ""
    except Exception:
        pass
    if re.search(r"thank you for applying|application received|successfully submitted", txt, re.I):
        proof_png = os.path.join(appdir, "confirmation.png")
        proof_txt = os.path.join(appdir, "confirmation.txt")
        try:
            cfx.shot(proof_png)
        except Exception:
            pass
        with open(proof_txt, "w") as f:
            f.write(txt[:2000])
        _log(company, role, "Greenhouse", url, "Applied", proof=proof_png)
        print(f"APPLIED_OK {company} {role} proof={proof_png}")
        return 0
    else:
        print(f"SUBMIT_NO_CONFIRM {company} {role} — logging Blocked")
        _log(company, role, "Greenhouse", url, "Blocked",
             note="submit returned no confirmation (required EEO/field gap)", proof=None)
        return 5


if __name__ == "__main__":
    sys.exit(main())
