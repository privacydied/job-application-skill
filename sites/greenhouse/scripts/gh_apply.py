#!/usr/bin/env python3
"""gh_apply.py — drive ONE Greenhouse application end-to-end (guest, account-less).

Single source of truth for Greenhouse submits in this skill. Reads a config JSON:
  {"url": "...", "company": "Monzo", "role": "Machine Learning Platform Engineer",
   "fill": {"<label>": "<value>"},            # JD-specific text answers
   "select": {"<label>": "<option>"},         # native <select> / react-select
   "radios": {"<question>": "<option>"},      # radio groups
   "checkboxes": {"<label>": "on|off"},
   "combo": {"<label>": "<option>"},          # required non-EEO react-select screeners
   "eeo": true|false,                          # fill EEO/diversity inputs (default true)
   "cover": "<base>.txt",                      # optional cover-letter file in uploads/
   "no_submit": true}                          # fill+review only, don't submit

Every dropdown/combobox — native <select> AND every react-select variant — is driven by the
ONE shared engine `atsform.combobox_pick` (interaction ladder: mousedown → ArrowDown →
trusted-click → type-to-filter; menu read from aria-controls / .select__menu / global options;
exact-then-word-boundary match so 'Man' != 'Isle of Man', 'No' != 'Monaco'). This file adds
NO combobox logic of its own — a fix in combobox_pick fixes Greenhouse too.

Hard rules enforced here (not left to the caller):
  * Anti-AI attestation clause on the page => REFUSE (prints REFUSE_ATTESTATION, exit 3).
    We must NOT submit a "use only my own words" form on the applicant's behalf.
  * Upload CV via container path /uploads/base-resume.pdf (host path 400s).
  * EEO answers come from apply-defaults.json -> applicant (gender/ethnicity/etc.) per the
    user's 2026-07-19 disclose instruction; age -> prefer not to say; religion untouched.
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

import cfx        # noqa: E402
import atsform    # noqa: E402

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
        "                e.textContent.replace(/\\s+/g,' ').trim().length < 80);"
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


def _fill_eeo():
    """Fill OPTIONAL EEO/diversity comboboxes via the ONE engine (atsform.combobox_pick),
    which drives every react-select variant through the interaction ladder. Values come from
    apply-defaults.json -> applicant (the user's 2026-07-19 disclose instruction). A field
    that's absent returns NOTFOUND and is skipped — EEO is optional. Tries several label
    phrasings per field because Greenhouse EEO wording varies by company. The gender /
    orientation / ethnicity fields are usually "mark all that apply" multi-selects → driven
    with multi=True + clear_first (replace any stale chip). Returns [(field, value, result)].

    Label care: the gender phrasings are SPECIFIC ("how would you describe your gender" /
    "which gender do you identify") so they do NOT collide with a "is your gender identity the
    same as sex assigned at birth?" Yes/No question — matching that would put "Man" on the
    wrong field. The transgender question uses the word "transgender" for the same reason."""
    defaults = json.load(open(os.path.join(_ROOT, "sites", "_common", "apply-defaults.json")))
    a = defaults.get("applicant", {})
    if str(a.get("disclose_demographics", "")).strip().lower().startswith("no"):
        return [("(disclose_demographics=No)", "", "SKIP")]
    # (label alternates, value, multi/mark-all-that-apply)
    plan = [
        (["how would you describe your gender", "which gender do you identify"],
         a.get("gender_identity"), True),
        (["sexual orientation"], a.get("sexual_orientation"), True),
        (["racial", "race/ethnicity", "ethnic background"], a.get("ethnicity"), True),
        (["transgender"], a.get("transgender"), False),
        (["disability", "chronic condition", "consider yourself disabled"], a.get("disability"), False),
        (["veteran"], a.get("veteran"), False),
    ]
    done = []
    for labels, val, multi in plan:
        if not val:
            continue
        rc = "NO_FIELD"
        for lab in labels:
            r = atsform.combobox_pick(lab, val, multi=multi, clear_first=multi, quiet_notfound=True)
            if r == atsform.NOTFOUND:
                continue           # this phrasing isn't on the form — try the next alternate
            rc = "OK" if r == 0 else "FAIL"   # a FAIL surfaces a real gap (e.g. a US race list
            break                              # with no "Mixed" option — handle via config)
        done.append((labels[0], val, rc))
    try:
        atsform.combobox_pick("pronoun", defaults.get("select", {}).get("Pronouns", "He/him"),
                              quiet_notfound=True)
    except Exception:  # noqa: BLE001
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
    except Exception as e:  # noqa: BLE001
        print(f"RESUME_UPLOAD_FAIL {e}")
        return 4

    cover = cfg.get("cover")
    if cover:
        try:
            atsform.upload("#cover_letter", f"/uploads/{cover}")
        except Exception as e:  # noqa: BLE001
            print(f"COVER_UPLOAD_WARN {e}")

    apply_cfg = {"defaults": True, "fill": cfg.get("fill", {}),
                 "select": cfg.get("select", {}), "radios": cfg.get("radios", {}),
                 "checkboxes": cfg.get("checkboxes", {})}
    tmp = os.path.join(appdir, "apply.json")
    json.dump(apply_cfg, open(tmp, "w"))
    try:
        atsform.apply(tmp, do_submit=False)
    except Exception as e:  # noqa: BLE001
        print(f"FILL_WARN {e}")

    for frag in ("UK Right to Work", "right to work"):
        try:
            if atsform.set_radio(frag, "Yes") == 0:
                break
        except Exception:  # noqa: BLE001
            pass

    if cfg.get("eeo", True):
        for lab, val, rc in _fill_eeo():
            print(f"  eeo {lab!r}={val!r} -> {rc}")

    # Required non-EEO react-select screeners (per-company, from config "combo") — driven by
    # the ONE engine, native <select> or react-select alike.
    for label_sub, val in cfg.get("combo", {}).items():
        rc = atsform.combobox_pick(label_sub, val)
        print(f"  combo {label_sub!r}={val!r} -> {rc}")

    if cfg.get("no_submit"):
        print(f"FILLED_ONLY {company} {role}")
        return 0

    try:
        cfx.shot(os.path.join(appdir, "review.png"))
    except Exception as e:  # noqa: BLE001
        print(f"SHOT_WARN {e}")

    try:
        atsform.submit("Submit application",
                       "thank you for applying|application (received|sent)|we.?re rooting|successfully submitted")
    except Exception as e:  # noqa: BLE001
        print(f"SUBMIT_ERR {e}")
    txt = ""
    try:
        txt = cfx.evaluate("document.body?document.body.innerText:''") or ""
    except Exception:  # noqa: BLE001
        pass
    if re.search(r"thank you for applying|application received|successfully submitted", txt, re.I):
        proof_png = os.path.join(appdir, "confirmation.png")
        proof_txt = os.path.join(appdir, "confirmation.txt")
        try:
            cfx.shot(proof_png)
        except Exception:  # noqa: BLE001
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
