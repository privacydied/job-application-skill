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
ONE shared engine `atsform.combobox_pick` (interaction ladder: mousedown -> ArrowDown ->
trusted-click -> type-to-filter; menu read from aria-controls / .select__menu / global options;
exact-then-word-boundary match so 'Man' != 'Isle of Man', 'No' != 'Monaco'). This file adds
NO combobox logic of its own — a fix in combobox_pick fixes Greenhouse too.

Hard rules enforced here (not left to the caller):
  * Upload CV via container path /uploads/base-resume.pdf (host path 400s).
  * EEO answers come from apply-defaults.json -> applicant (gender/ethnicity/etc.) per the
    user's 2026-07-19 disclose instruction; age -> prefer not to say; religion untouched.
  * Greenhouse gates submit behind an emailed 8-char "Security code" (anti-bot). The
    applicant's mailbox (address read from config by email_ingest) is IMAP-readable, so we
    poll for the freshest code for THIS company and type it in (char-by-char — React OTP boxes
    reject a bulk paste). Logs via log-application.py with --proof ONLY on a captured confirmation.

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
sys.path.insert(0, os.path.join(_ROOT, "scripts"))  # email_ingest lives at skill root

import cfx        # noqa: E402
import atsform    # noqa: E402
import precheck   # noqa: E402  — already_applied() apply-time dedup guard
import fetch_verification_code as vcode  # noqa: E402  — the ONE shared email-code primitive
import recaptcha  # noqa: E402  — sanctioned reCAPTCHA v2 solver (user pre-authorized)

UPLOADS = os.path.join(_ROOT, "uploads")
APPS = os.path.join(_ROOT, "applications")


def _slug(company, role):
    s = re.sub(r"[^a-z0-9]+", "-", f"{company}-{role}".lower()).strip("-")
    return s[:80]



# The emailed-code fetch lives in the ONE shared primitive scripts/fetch_verification_code.py
# (used by Greenhouse AND applicationtrack/MI5) — imported above as `vcode`. gh_apply just
# calls vcode.get_code(...) and types the result; no per-driver mailbox logic here, and no
# hardcoded address (creds come from the ats-credentials.csv `imap` row via email_ingest).


def _type_code(label, code):
    """Commit a Greenhouse OTP security code to the (controlled) React input.

    The field is a single input whose id is `security-input-0`. A plain value-set or a
    /type value-set only keeps the first char because the component is controlled and
    resets on each render — so we commit the way React expects: set the value via the
    element's native setter (bypassing the React-overridden `.value`), then dispatch
    `input` + `change` events so React's onChange picks it up. If the field is actually
    an N-box OTP (siblings security-input-1..N), the same approach per-box works because
    each box is independently controlled.

    Returns nothing; prints the committed length for verification."""
    info = cfx.evaluate(
        "(function(){"
        "  function ownLabel(e){"
        "    if(e.id){var l=document.querySelector('label[for=\"'+e.id+'\"]');if(l)return l.innerText;}"
        "    var p=e.closest('label');if(p)return p.innerText;"
        "    return (e.getAttribute('aria-label')||e.getAttribute('placeholder')||e.getAttribute('name')||'');"
        "  }"
        "  var ins=[].slice.call(document.querySelectorAll('input'));"
        "  for(var j=0;j<ins.length;j++){"
        "    var e=ins[j];"
        "    var t=ownLabel(e);"
        "    if(/security code|verification code|enter the code|one.?time code/i.test(t)) return '#'+e.id;"
        "  }"
        "  for(var j=0;j<ins.length;j++){"
        "    var e=ins[j];"
        "    var sig=(e.id+' '+(e.getAttribute('name')||'')+' '+(e.getAttribute('autocomplete')||'')+' '+(e.getAttribute('inputmode')||'')).toLowerCase();"
        "    if(/code|otp|verif|one-time/.test(sig)) return '#'+e.id;"
        "  }"
        "  return null;"
        "})()")
    if not info:
        raise RuntimeError("no security-code field found on the form")
    print(f"  CODE_FIELD {info}")
    code = str(code)
    # Detect sibling boxes: security-input-0..N (multi-box OTP).
    boxes = cfx.evaluate(
        "(function(){var base=" + json.dumps(info) + ".replace(/^#/,'').replace(/-0$/,'');"
        "var out=[];for(var i=0;i<12;i++){var el=document.getElementById(base+'-'+i);if(el)out.push('#'+el.id);else break;}"
        "if(out.length)return out;"
        "var single=document.querySelector(" + json.dumps(info) + ");return single?['#'+single.id]:[];})()")
    if len(boxes) > 1:
        print(f"  CODE_BOXES {len(boxes)} (multi-box OTP)")
        for i, ch in enumerate(code):
            if i >= len(boxes):
                break
            _react_set(boxes[i], ch)
            time.sleep(0.12)
    else:
        _react_set(boxes[0] if boxes else info, code)
    time.sleep(0.5)
    # Verify by CONCATENATING all boxes (a multi-box OTP holds one char each) — reading only
    # box 0 falsely reported len=1 even when all 8 were filled and the submit succeeded.
    final = cfx.evaluate(
        "(function(){var s='';for(var i=0;i<12;i++){var e=document.getElementById('security-input-'+i);"
        "if(!e)break;s+=(e.value||'');}"
        "if(!s){var one=document.querySelector(" + json.dumps(info) + ");s=one?one.value:'';}return s;})()")
    print(f"  CODE_TYPED len={len(str(final))} val={final!r}")


def _react_set(sel, value):
    """Set a controlled React input's value via the native setter + dispatch input/change.
    Mirrors atsform's React-commit trick; usable for OTP boxes where /type truncates."""
    cfx.evaluate(
        "(function(){"
        "  var el=document.querySelector(" + json.dumps(sel) + ");"
        "  if(!el) return;"
        "  var proto = el.tagName==='TEXTAREA' ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;"
        "  var setter = Object.getOwnPropertyDescriptor(proto,'value').set;"
        "  setter.call(el, " + json.dumps(value) + ");"
        "  el.focus();"
        "  el.dispatchEvent(new Event('input',{bubbles:true}));"
        "  el.dispatchEvent(new Event('change',{bubbles:true}));"
        "})()")


def _is_enterprise_invisible():
    """Greenhouse now serves reCAPTCHA ENTERPRISE with size=invisible (not the v2
    checkbox the user pre-authorized auto-solve covers). There is no clickable anchor
    (#recaptcha-anchor is absent inside the enterprise iframe) — the token is scored by
    the real Submit action itself. So: do NOT try to click; just proceed to submit and
    then poll for the response token. Returns True if an enterprise-invisible widget is
    detected, else False."""
    try:
        src = cfx.evaluate(
            "(function(){var f=document.querySelector('iframe[src*=recaptcha],iframe[src*=captcha]');"
            "return f?f.src:'';})()")
        if not src:
            return False
        return ("enterprise" in src) and ("size=invisible" in src or "invisible" in src)
    except Exception:  # noqa: BLE001
        return False


def _solve_captcha(company):
    """Solve a Greenhouse reCAPTCHA gate before submit.

    - v2 checkbox present+unsolved -> click it (user pre-authorized v2 auto-solve);
      a grid challenge (rc==2) or fingerprint NO-CHANGE (rc==3) are hard stops -> False.
    - v2 already solved / invisible badge -> True (submit + wait-token handles it).
    - ENTERPRISE invisible (no checkbox; scored on the Submit action) -> True: just
      proceed to submit; the token populates as a side-effect of the real action.
    """
    try:
        if _is_enterprise_invisible():
            print("  CAPTCHA enterprise-invisible — proceeding to Submit (scored on action)")
            return True
        if recaptcha._anchor_present():
            if recaptcha._anchor_checked() is True:
                print("  CAPTCHA already solved")
                return True
            r = recaptcha.click(company)
            if r == 2:
                print("  CAPTCHA_GRID_HALT: image-grid challenge requires the user; stopping this form")
                return False
            if r == 3:
                print("  CAPTCHA_NOCHANGE_HALT: fingerprint distrust; hand to user")
                return False
            print(f"  CAPTCHA click rc={r}")
            return True
        if recaptcha._badge_present():
            print("  CAPTCHA invisible badge — will wait for token after Submit")
            return True
    except Exception as e:  # noqa: BLE001
        print(f"  CAPTCHA_SOLVE_WARN {e}")
        return True
    return True


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
    orientation / ethnicity fields are usually "mark all that apply" multi-selects -> driven
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
        # NOTE: several Greenhouse forms render a "race/ethnicity" combobox whose
        # option list is actually a COUNTRY dialing-code list (broken employer form) —
        # pushing "Mixed or Multiple ethnic groups" into it is wrong. Skip ethnicity auto-fill
        # defensively; the applicant can disclose it on forms that expose a real EEO race list.
        # (["racial", "race/ethnicity", "ethnic background"], a.get("ethnicity"), True),
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

    # DEDUP GUARD: a config driven directly bypasses the sourcing precheck, so re-check the
    # live tracker (canonical URL id first, then Company+Role) before burning a real submit /
    # CAPTCHA on a role already Applied — this is what stops re-applying to already-applied
    # roles (only "Applied" statuses skip; Blocked/Saved stay re-drivable). Override with
    # "force": true in the config to intentionally re-drive.
    if not cfg.get("force"):
        hit = precheck.already_applied(url=url, company=company, role=role)
        if hit and precheck.is_applied(hit[0]):
            print(f"SKIP_ALREADY_APPLIED {company} | {role} — tracker={hit[0]} (matched {hit[1]})")
            return 0

    slug = _slug(company, role)
    appdir = os.path.join(APPS, slug)
    os.makedirs(appdir, exist_ok=True)

    r = cfx.goto(url)
    if not r.get("ok"):
        print(f"NAV_FAIL {url} {r}")
        return 2
    time.sleep(1.0)

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

    # TOP-UP: atsform.apply batch-fill occasionally leaves a field empty (React commit
    # timing). Re-fill each text field individually via atsform.fill — the proven path —
    # so required fields that the batch missed actually bind. Combinations of label
    # substring + value; failures are reported, not fatal.
    for lab, val in cfg.get("fill", {}).items():
        try:
            rc = atsform.fill(lab, val)
            if rc != 0:
                print(f"  FILL_TOPUP {lab!r} -> {rc}")
        except Exception as e:  # noqa: BLE001
            print(f"  FILL_TOPUP_WARN {lab!r}: {e}")

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
    # the ONE engine, native <select> or react-select alike. A mid-run camofox tab death
    # (HTTP 404 Tab not found) is an INFRA failure, not a form failure — catch it and log a
    # clean Blocked instead of crashing with a traceback (the run can be retried on a fresh tab).
    for label_sub, val in cfg.get("combo", {}).items():
        try:
            rc = atsform.combobox_pick(label_sub, val)
        except cfx.CfxError as e:
            print(f"  combo {label_sub!r} ENGINE_ERR {e}")
            _log(company, role, "Greenhouse", url, "Blocked",
                 note=f"camofox tab/engine died mid-fill ({str(e)[:60]}) — retry on a fresh tab",
                 proof=None)
            return 6
        print(f"  combo {label_sub!r}={val!r} -> {rc}")

    # Truthful checkbox auto-fill (replaces a blanket tick-all): post-fill steps can render NEW
    # checkboxes, so tick ONLY those whose statement is affirmatively true for the applicant
    # (accuracy / consent-to-apply + eligibility facts from apply-defaults.json checkbox_truths);
    # leave unknown / false / marketing / anti-AI boxes UNCHECKED and report them for the human.
    try:
        rep = atsform.checkboxes_from_profile()
        if rep.get("ticked"):
            print(f"OK  truthful-checkboxes ticked {len(rep['ticked'])}: {rep['ticked']}")
        for k in ("left_unknown", "left_antiai", "left_false", "left_marketing"):
            if rep.get(k):
                print(f"  checkbox left for you ({k[5:]}): {rep[k]}")
    except cfx.CfxError:
        pass

    if cfg.get("no_submit"):
        print(f"FILLED_ONLY {company} {role}")
        return 0

    try:
        cfx.shot(os.path.join(appdir, "review.png"))
    except Exception as e:  # noqa: BLE001
        print(f"SHOT_WARN {e}")

    # ── submit (Greenhouse MAY gate submit behind an emailed "Security code") ──
    _CONF = r"thank you for applying|application received|successfully submitted"

    # ── reCAPTCHA v2 (user pre-authorized auto-solve) — solve BEFORE first submit ──
    if not _solve_captcha(company):
        _log(company, role, "Greenhouse", url, "Blocked",
             note="reCAPTCHA image-grid / fingerprint-distrust — needs the user", proof=None)
        return 7

    def _confirm_text():
        # Confirmed if the page is on the /confirmation route OR the body shows the success
        # text. Greenhouse redirects to .../confirmation on a successful (code-gated) submit,
        # and that redirect can LAG the submit by several seconds — so treat the URL as proof.
        try:
            url = cfx.current_url()
        except Exception:  # noqa: BLE001
            url = ""
        try:
            t = cfx.evaluate("document.body?document.body.innerText:''") or ""
        except Exception:  # noqa: BLE001
            t = ""
        if "/confirmation" in url or re.search(_CONF, t, re.I):
            return t or url
        return ""

    def _confirm_poll(seconds=45):
        # Poll for confirmation — the emailed-code submit + redirect lags well past atsform's
        # own submit wait; a single read here is what caused false 'Blocked' on Monzo.
        deadline = time.time() + seconds
        while True:
            t = _confirm_text()
            if t or time.time() >= deadline:
                return t
            time.sleep(2)

    try:
        atsform.submit("Submit application",
                       "thank you for applying|application (received|sent)|we.?re rooting|successfully submitted")
    except Exception as e:  # noqa: BLE001
        print(f"SUBMIT1_ERR {e}")

    txt = _confirm_text()
    if not txt:
        # Not confirmed → likely the emailed "Security code" gate: the first Submit fired the
        # email, so poll the mailbox for it, type it char-by-char, and Submit again. (Forms
        # WITHOUT the gate confirmed on the first Submit above and skip this whole block — no
        # wasted 90s poll for a code that will never arrive.)
        code = vcode.get_code(sender="greenhouse", company=company, digits=8, wait_s=90)
        if code:
            try:
                _type_code("Security code", code)
                print(f"  CODE_FILL ok ({len(code)} chars)")
            except Exception as e:  # noqa: BLE001
                print(f"  CODE_FILL_WARN {e}")
            # re-verify the reCAPTCHA is still solved (token may have expired while fetching email)
            try:
                recaptcha.recheck(company)
            except Exception as e:  # noqa: BLE001
                print(f"  CAPTCHA_RECHECK_WARN {e}")
            # DIAGNOSTIC: what is the field value + which submit buttons exist now?
            try:
                diag = cfx.evaluate(
                    "(function(){"
                    "  var f=document.getElementById('security-input-0');"
                    "  var btns=[].slice.call(document.querySelectorAll('button')).map(function(b){return b.innerText.trim();});"
                    "  return {fieldVal:(f?f.value:'(no field)'), btns:btns.filter(Boolean).slice(0,12)};"
                    "})()")
                open("/tmp/gh_pre2.txt","w").write(str(diag))
                print("  PRE2_DIAG", diag)
            except Exception as e:
                print("  PRE2_DIAG_ERR", e)
            try:
                atsform.submit("Submit application",
                               "thank you for applying|application (received|sent)|we.?re rooting|successfully submitted")
            except Exception as e:  # noqa: BLE001
                print(f"SUBMIT2_ERR {e}")
            txt = _confirm_poll(45)   # the code-gated redirect lags — poll, don't single-read
        else:
            print("  CODE_MISSING — no verification code fetched")

    if txt:
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
    print(f"SUBMIT_NO_CONFIRM {company} {role} — logging Blocked")
    try:
        dbg = cfx.evaluate("document.body?document.body.innerText:''") or ""
        open("/tmp/gh_debug.txt", "w").write(dbg[:3000])
        print(f"  DEBUG_TEXT_SAVED /tmp/gh_debug.txt ({len(dbg)} chars)")
    except Exception as e:  # noqa: BLE001
        print(f"  DEBUG_ERR {e}")
    _log(company, role, "Greenhouse", url, "Blocked",
         note="submit returned no confirmation (verification code gap or required field)", proof=None)
    return 5


if __name__ == "__main__":
    sys.exit(main())
