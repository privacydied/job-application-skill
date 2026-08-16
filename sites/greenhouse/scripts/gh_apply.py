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
    want = os.path.basename(filename)
    regex = want.replace(".", r"\.")
    probe = ("(()=>{const t=document.body.innerText||'';return /" + regex + "/.test(t);})()")
    # ⛔ 3 SECONDS WAS TOO TIGHT, AND ONE ATTEMPT TOO FEW (2026-08-16). Greenhouse moves the
    # file into a chip asynchronously; on a heavy form that render can take longer than the
    # old 3s poll, and _upload_and_verify raising aborts the WHOLE application with rc=4
    # (RESUME_UPLOAD_FAIL) before a single question is answered. Lost the Dotmatics UX
    # Designer drive that way — a Tier-A, Remote-UK posting that was otherwise one truthful
    # answer from complete, failed on a timer rather than on anything about the form.
    # Give the render room, and retry the upload once before giving up: an upload that did
    # not register is far likelier than a form that cannot accept one.
    for attempt in (1, 2):
        cfx.post(f"/tabs/{cfx._tab()}/upload",
                 {"userId": cfx._uid(), "selector": sel, "path": filename})
        if cfx.poll(probe, predicate=lambda r: r is True, timeout=12.0, interval=0.4):
            print(f"OK upload {target!r}: chip={want}"
                  + (" (2nd attempt)" if attempt == 2 else ""))
            return
        print(f"  upload {target!r}: no chip after 12s — retrying" if attempt == 1 else "")
    raise RuntimeError(f"CV chip '{want}' not visible after upload (2 attempts)")


def _fill_eeo():
    """Delegate to the ONE shared EEO filler (atsform.fill_eeo) — this logic was promoted there
    2026-07-24 so Ashby (which had no EEO capability, and grew a bespoke one that inverted the
    applicant's disclose instruction) uses the SAME implementation. Do NOT re-add a local copy:
    values come from apply-defaults.json -> applicant, label alternates and the
    combobox-then-radio fallback all live in the shared engine now."""
    return atsform.fill_eeo()


def _log(company, role, source, url, status, note=None, proof=None):
    """Write the tracker row — and VERIFY it was written.

    ⛔ WHY THE RETURN CODE MATTERS (2026-08-15, cost a duplicate application).
    This used to be a bare `subprocess.run(...)` that ignored the exit code. log-application.py
    deliberately REFUSES a blind pair-merge when an existing (Company, Role) row carries a
    DIFFERENT url — the dedup-collision case — and tells you to re-run with --append-new. That
    refusal was swallowed, so:
      * Graphcore "Infrastructure and MLOps Engineer" was submitted successfully, the older
        2026-07-24 row for the same title (different job id) triggered the refusal, and NO row
        was written;
      * because no row existed, the next drain's tracker dedup did not see it and applied to
        THE SAME POSTING A SECOND TIME.
    A silent logging failure is therefore not a bookkeeping nit: it re-submits real
    applications to real employers, and under-reports the count at the same time (SKILL.md
    §Count integrity calls this the dangerous UNDER_REPORTED conflict).

    A different job id at the same company+title IS a genuinely new posting, which is exactly
    what --append-new means, so retry with it once and shout if that still fails."""
    base = ["python3", os.path.join(_ROOT, "sites", "_common", "scripts", "log-application.py"),
            company, role, source, url, status]
    if proof:
        base += ["--proof", proof]
    if note:
        base += ["--note", note]
    r = subprocess.run(base, cwd=_ROOT, capture_output=True, text=True)
    out = (r.stdout or "") + (r.stderr or "")
    print(out.strip())
    if r.returncode == 0:
        return True
    if "--append-new" in out:
        r2 = subprocess.run(base + ["--append-new"], cwd=_ROOT, capture_output=True, text=True)
        print(((r2.stdout or "") + (r2.stderr or "")).strip())
        if r2.returncode == 0:
            return True
    print(f"⛔ LOG_FAILED {company} | {role} | {status} — the tracker was NOT updated. "
          f"A submitted application that is not logged WILL be applied to again by the next "
          f"drain. Fix the row by hand before re-running.", file=sys.stderr)
    return False


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
        # ⛔ NOT rc=0 (2026-08-16). Returning the SUCCESS code for a posting we did not
        # apply to made apply_queue tally it under `applied`: drain23 reported
        # "applied: 1" with ZERO real submissions, the count coming entirely from one
        # already-applied Saviynt row. That is the count-integrity failure SKILL.md
        # warns about, arriving through the tally instead of the tracker. rc=6 =
        # "skipped, already applied": not a success, not a failure.
            return 10

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

    # IDENTITY BACKSTOP (2026-08-15). Greenhouse's core identity inputs have STABLE ids
    # (#first_name/#last_name/#email/#phone), but they were repeatedly left empty by the
    # label-driven fill and the submit bounced on "First Name is required." — twice in one
    # run (Cognism, Capco), each costing a full re-drive plus a wasted verification-code
    # round-trip. Two causes seen: (a) label collision — a form with BOTH "First Name*" and
    # "Preferred First Name*" resolves the substring to the wrong control, and (b) Greenhouse
    # re-renders after the résumé autofill and drops a value that fill() already reported OK.
    # Neither is worth diagnosing per-form when the ids are stable: assert the values by id,
    # and only touch a field that is genuinely EMPTY so a correct value is never overwritten.
    try:
        d = atsform._load_defaults(True) or {}
        f = d.get("fill", {}) or {}
        ident = {"first_name": f.get("First name"), "last_name": f.get("Last name"),
                 "email": f.get("Email"), "phone": f.get("Phone")}
        ident = {k: v for k, v in ident.items() if v}
        if ident:
            res = cfx.evaluate(
                "(function(){var m=%s;"
                "var s=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;"
                "var fixed=[];"
                "Object.keys(m).forEach(function(id){var el=document.getElementById(id);"
                "  if(!el||(el.value||'').trim()) return;"
                "  s.call(el,m[id]);"
                "  el.dispatchEvent(new Event('input',{bubbles:true}));"
                "  el.dispatchEvent(new Event('change',{bubbles:true}));"
                "  fixed.push(id);});"
                "return fixed.join(',');})()" % json.dumps(ident))
            if res:
                print(f"  IDENTITY_BACKSTOP re-bound empty field(s): {res}")
    except Exception as e:  # noqa: BLE001
        print(f"  IDENTITY_BACKSTOP_WARN {e}")

    # EDUCATION BACKSTOP (2026-08-15). Some Greenhouse postings render a required Education
    # block (School / Degree / Discipline react-selects + start/end year). It is NOT part of
    # the `questions` API and neither inspect_gh_form nor gen_gh_config can see it, so a
    # config built from either looks complete and the submit still bounces with
    # "School is required." — hit on IMC and YugabyteDB. The controls have STABLE ids
    # (school--0 / degree--0 / discipline--0 / start-year--0 / end-year--0), so bind them
    # directly from the gitignored applicant config rather than teaching every generator
    # about a section it cannot introspect. Skipped silently when the block is absent.
    try:
        if cfx.evaluate("!!document.querySelector('#school--0')"):
            d = atsform._load_defaults(True) or {}
            ap = d.get("applicant", {}) or {}
            school = ap.get("school")
            disc = ap.get("area_of_study")
            degree = ap.get("degree") or "Bachelor's Degree"
            if school:
                for target, val in (("School", school), ("Degree", degree), ("Discipline", disc)):
                    if not val:
                        continue
                    try:
                        rc = atsform.combobox_pick(target, val, quiet_notfound=True)
                        # Greenhouse's Discipline list is a FIXED taxonomy, so a specific real
                        # course title ("Information & Interface Design") is often absent from
                        # it and the field stays empty on a REQUIRED control. Fall back to the
                        # course's own category word — a narrowing to the employer's
                        # vocabulary, not a different claim (same rule as the ethnicity
                        # leading-token fallback in atsform.fill_eeo).
                        if rc not in (0, atsform.NOTFOUND) and target == "Discipline":
                            for word in reversed(str(val).replace("&", " ").split()):
                                if len(word) < 4:
                                    continue
                                rc = atsform.combobox_pick(target, word, quiet_notfound=True)
                                if rc == 0:
                                    print(f"  education Discipline matched via category "
                                          f"{word!r} (taxonomy has no {val!r})")
                                    break
                        print(f"  education {target}={val!r} -> {rc}")
                    except Exception as e:  # noqa: BLE001
                        print(f"  education {target} WARN {e}")
                yrs = ap.get("education_years")  # e.g. "2016-2019"
                if yrs and "-" in str(yrs):
                    s, e = str(yrs).split("-", 1)
                    cfx.evaluate(
                        "(function(){var set=Object.getOwnPropertyDescriptor("
                        "window.HTMLInputElement.prototype,'value').set;"
                        "[['start-year--0',%s],['end-year--0',%s]].forEach(function(p){"
                        "var el=document.getElementById(p[0]);"
                        "if(el&&!el.value){set.call(el,p[1]);"
                        "el.dispatchEvent(new Event('input',{bubbles:true}));"
                        "el.dispatchEvent(new Event('change',{bubbles:true}));}});"
                        "return 1;})()" % (json.dumps(s.strip()), json.dumps(e.strip())))
                # START/END MONTH (2026-08-15). Several postings require month as well as
                # year — IMC bounced with "Start month is required. End month is required."
                # while every other field was correct, so the whole application failed on two
                # dropdowns. These are NOT guessable: the profile records years only, and a
                # month is a real-world fact about the applicant. So read them from the
                # gitignored applicant config and, when absent, say so and let the posting go
                # to the human queue rather than inventing a date (SKILL.md §No fabrication).
                sm, em = ap.get("education_start_month"), ap.get("education_end_month")
                if cfx.evaluate("!!document.querySelector('#start-month--0')"):
                    if sm and em:
                        for tgt, val in (("Start month", sm), ("End month", em)):
                            try:
                                atsform.combobox_pick(tgt, val, quiet_notfound=True)
                            except Exception:  # noqa: BLE001
                                pass
                    else:
                        print("  EDUCATION_MONTHS_REQUIRED but apply-defaults.json has no "
                              "applicant.education_start_month / education_end_month — add "
                              "the real months there (gitignored). NOT guessing a date.")
            else:
                print("  EDUCATION_REQUIRED but apply-defaults.json has no applicant.school "
                      "— add it there (gitignored), do not hardcode it here.")
    except Exception as e:  # noqa: BLE001
        print(f"  EDUCATION_BACKSTOP_WARN {e}")

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
        # ANTI-AI OATH (2026-08-14): the form REQUIRES attesting the answers are the
        # applicant's own words and that AI-generated content disqualifies the application.
        # An autonomous run cannot sign that truthfully. Abandon this posting WITHOUT
        # submitting and route it to the human queue — never fall through to submit, which
        # would either bounce on the required field or, worse, go through having auto-signed
        # a false attestation in the applicant's name.
        if rc == atsform.ANTI_AI:
            print(f"  combo {label_sub!r} -> ANTI_AI attestation; abandoning submit.")
            _log(company, role, "Greenhouse", url, "Skipped",
                 note="requires anti-AI attestation ('own words', AI-generated content "
                      "disqualifies) — the applicant must write and submit this one himself",
                 proof=None)
            return 8
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

    # LAST fill pass — answer anything STILL empty from the shared screener bank.
    # gh_apply has its own flow rather than going through atsform.apply(), so it did not
    # inherit fill_gaps_from_bank when that was wired into atsform.apply and ashby.apply.
    # That gap was costing whole submissions: Twilio bounced on "Location (City)",
    # "How did you hear about Twilio?" and two consent selects that are all ALREADY in
    # screener-answers.csv — the config just didn't happen to name them, and nothing
    # afterwards looked. Runs after config + EEO + combos so an explicit answer always wins,
    # and before the review screenshot so what's captured is what gets submitted.
    try:
        atsform.fill_gaps_from_bank()
    except Exception as e:  # noqa: BLE001 — a bank miss must never block an otherwise-good form
        print(f"  screener-bank note: {str(e)[:80]}")

    if cfg.get("no_submit"):
        print(f"FILLED_ONLY {company} {role}")
        return 0

    try:
        cfx.shot(os.path.join(appdir, "review.png"), full_page=True)
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
            cfx.shot(proof_png, full_page=True)
        except Exception:  # noqa: BLE001
            pass
        with open(proof_txt, "w") as f:
            f.write(txt[:2000])
        _log(company, role, "Greenhouse", url, "Applied", proof=proof_png)
        print(f"APPLIED_OK {company} {role} proof={proof_png}")
        return 0
    print(f"SUBMIT_NO_CONFIRM {company} {role} — logging Blocked")
    try:
        # ⛔ DUMP THE ERRORS, NOT THE FIRST 3000 CHARS OF THE PAGE (2026-08-16). This used to
        # take document.body.innerText[:3000], which on a Greenhouse posting is the JOB
        # DESCRIPTION — the form and its validation messages are far below that cut. Read it
        # twice while diagnosing a blocked submit and learned nothing about the form either
        # time. Collect the error nodes and the label of the field each one belongs to, then
        # fall back to the body text only if the page exposes no error nodes at all.
        errs = cfx.evaluate("""(()=>{
          const clean=s=>(s||'').replace(/\\s+/g,' ').trim();
          const out=[];
          document.querySelectorAll('[class*="error"],[aria-invalid="true"],[role=alert]')
            .forEach(e=>{
              const msg=clean(e.innerText); if(!msg||msg.length>200) return;
              let b=e,lab='';
              for(let k=0;k<5&&b;k++){b=b.parentElement; if(!b)break;
                const t=clean(b.innerText);
                if(t&&t.length<260&&t!==msg){lab=t.split(msg).join(' ').trim(); break;}}
              out.push((lab?lab.slice(0,120)+'  ==> ':'')+msg);});
          return JSON.stringify([...new Set(out)].slice(0,25),null,1);})()""") or ""
        try:
            parsed = json.loads(errs) if errs else []
        except ValueError:
            parsed = []
        dbg = ("VALIDATION ERRORS (field ==> message)\n" + "\n".join(parsed)) if parsed else (
            cfx.evaluate("document.body?document.body.innerText:''") or "")
        # ⛔ ONE FIXED PATH MEANS EVERY FAILURE OVERWRITES THE LAST (2026-08-16). A drain
        # produces many SUBMIT_NO_CONFIRMs, all writing /tmp/gh_debug.txt, so by the time
        # anyone reads it the contents belong to a DIFFERENT posting. It cost a misdiagnosis
        # today: investigating why Dotmatics blocked, the dump held SumUp's form. Write the
        # evidence next to the application it belongs to, and keep a stable path as a
        # convenience copy of the most recent one.
        dbg_path = os.path.join(appdir, "submit-blocked.txt") if appdir else "/tmp/gh_debug.txt"
        with open(dbg_path, "w") as f:
            f.write(dbg[:3000])
        try:
            with open("/tmp/gh_debug.txt", "w") as f:
                f.write(f"# most recent: {company} | {role}\n" + dbg[:3000])
        except OSError:
            pass
        print(f"  DEBUG_TEXT_SAVED {dbg_path} ({len(dbg)} chars)")
    except Exception as e:  # noqa: BLE001
        print(f"  DEBUG_ERR {e}")
    _log(company, role, "Greenhouse", url, "Blocked",
         note="submit returned no confirmation (verification code gap or required field)", proof=None)
    return 5


if __name__ == "__main__":
    sys.exit(main())
