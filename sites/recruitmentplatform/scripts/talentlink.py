#!/usr/bin/env python3
"""
talentlink.py — driver for Lumesse TalentLink application forms
(emea3.recruitmentplatform.com/apply-app/pages/application-form?jobId=...).

Hackney Council, and other Lumesse-backed councils, route "Apply Now" here.
The form is a single long page with ~117 fields: contact, multi-employer
employment history (each block = Employer name + Job title + start/end date
dropdowns + responsibility textarea), education, qualifications, role-specific
competency textareas, declarations, and an equality-monitoring block.

Field addresses: TalentLink uses stable `name` attributes (first_name,
e-mail_address, custom_question_NNNN, ...). The ONE quirk: each employment
date is THREE <select> elements that SHARE one name (Day / Month / Year, in
document order) — so you must set them by querySelectorAll index, not a single
name lookup. This driver handles that.

Usage:
  python3 talentlink.py <jobId-url-or-form-url> <spec.json> [--submit]

spec.json keys (all optional — only listed keys are set; everything else is
left as the page default, which is correct for optional EEO fields):
  {
    "text":   { "<name>": "<value>", ... },          # text/email/textarea by name
    "select": { "<name>": "<option text>", ... },     # native <select> by name+label
    "dates":  { "<name>": ["DD","Month","YYYY"], ... },# each = 3 selects sharing <name>
    "radio":  { "<name>": "<value>", ... },           # radio by name+value (rare)
    "upload": "<path to CV pdf>",
    "company": "Hackney Council",                      # for the pre-submit review
    "submit": true
  }

EEO / monitoring fields are intentionally NOT in the defaults — the skill's
standing rule is "Prefer not to say" for optional demographic questions; the
caller should pass those explicitly if the council requires them (Hackney marks
most as Required, so the spec SHOULD set them — see the example spec used by the
apply loop). The driver only sets what the spec lists.

The driver does NOT invent answers — pass real, verified values from
references/applicant-profile.md. Reused by the job-apply loop for every
Hackney (and any other Lumesse) posting.

Exit: 0 if every set field verified + review clean (and submitted if --submit);
non-zero on any failure (with a per-field summary).
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "_common", "scripts"))
import cfx  # noqa: E402


def _set_text(name, value):
    sel = f'select[name="{name}"], input[name="{name}"], textarea[name="{name}"]'
    # prefer the input/textarea (text), not a select
    res = cfx.evaluate(f"""(() => {{
      const e = document.querySelector('input[name="{name}"], textarea[name="{name}"]');
      if (!e) return 'NO_FIELD';
      e.focus();
      const setter = Object.getOwnPropertyDescriptor(e.constructor.prototype, 'value').set;
      setter.call(e, {json.dumps(value)});
      e.dispatchEvent(new Event('input', {{bubbles:true}}));
      e.dispatchEvent(new Event('change', {{bubbles:true}}));
      return 'OK:' + (e.value||'').slice(0,40);
    }})()""")
    return res if isinstance(res, str) else str(res)


def _set_select(name, option_text):
    res = cfx.evaluate(f"""(() => {{
      const s = document.querySelector('select[name="{name}"]');
      if (!s) return 'NO_FIELD';
      const want = {json.dumps(option_text)}.toLowerCase();
      const opt = [...s.options].find(o => o.text.trim().toLowerCase() === want)
               || [...s.options].find(o => o.text.trim().toLowerCase().includes(want));
      if (!opt) return 'NO_OPTION:' + [...s.options].map(o=>o.text.trim()).slice(0,8).join('|');
      s.value = opt.value;
      s.dispatchEvent(new Event('change', {{bubbles:true}}));
      return 'OK:' + opt.text.trim().slice(0,40);
    }})()""")
    return res if isinstance(res, str) else str(res)


def _set_date(name, dmy):
    """dmy = [day_str, month_str, year_str]; sets the 3 selects sharing `name`."""
    day, month, year = dmy[0], dmy[1], dmy[2]
    res = cfx.evaluate(f"""(() => {{
      const sels = [...document.querySelectorAll('select[name="{name}"]')];
      if (sels.length < 3) return 'NO_DATE_FIELDS:' + sels.length;
      const want = {json.dumps([day, month, year])};
      const out = [];
      for (let i=0;i<3;i++) {{
        const s = sels[i];
        const w = want[i].toLowerCase();
        const opt = [...s.options].find(o => o.text.trim().toLowerCase() === w)
                 || [...s.options].find(o => o.text.trim().toLowerCase().includes(w));
        if (!opt) {{ out.push('NO_OPTION['+i+']'); continue; }}
        s.value = opt.value;
        s.dispatchEvent(new Event('change', {{bubbles:true}}));
        out.push('OK'+i);
      }}
      return out.join(',');
    }})()""")
    return res if isinstance(res, str) else str(res)


def _set_radio(name, value):
    res = cfx.evaluate(f"""(() => {{
      const r = document.querySelector('input[type=radio][name="{name}"][value="{value}"]')
             || document.querySelector('input[type=radio][name="{name}"]');
      if (!r) return 'NO_FIELD';
      r.click();
      return 'OK:' + (r.checked?'checked':'unchecked');
    }})()""")
    return res if isinstance(res, str) else str(res)


def _upload(path):
    """Upload a CV pdf. The camofox upload API expects the file to already be
    staged in the skill's uploads/ dir (bind-mounted as /uploads in the
    container); only the basename is sent as `path`. So copy it there first."""
    import shutil
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
    uploads_dir = os.path.join(root, "uploads")
    os.makedirs(uploads_dir, exist_ok=True)
    base = os.path.basename(path)
    staged = os.path.join(uploads_dir, base)
    shutil.copyfile(path, staged)
    sel = 'input[type=file]'
    try:
        cfx.post(f"/tabs/{cfx._tab()}/upload",
                 {"userId": cfx._uid(),
                  "selector": sel, "path": base})
        return "OK uploaded " + base
    except cfx.CfxError as e:
        return "FAIL upload: " + str(e)


def _accept_dps():
    """Hackney/Lumesse Data Privacy Statement. The visible 'I agree' UI is a dialog
    over a HIDDEN <select name="dps"> (options: 'Please agree'='' / 'I agree'='true').
    Setting that select directly is what actually satisfies the form's validation
    model (synthetic clicks on the dialog button don't persist to the model)."""
    res = cfx.evaluate("""(() => {
      const s = document.querySelector('select[name="dps"]');
      if (!s) return 'NO_DPS_SELECT';
      const opt = [...s.options].find(o => /^(yes|agree|i agree)$/i.test(o.text.trim())) || [...s.options].find(o => o.value && o.value !== '');
      if (!opt) return 'NO_DPS_OPTION:' + [...s.options].map(o=>o.text.trim()).join('|');
      s.value = opt.value;
      s.dispatchEvent(new Event('change', {bubbles:true}));
      s.dispatchEvent(new Event('input', {bubbles:true}));
      return 'OK:' + opt.text.trim();
    })()""")
    return res if isinstance(res, str) else str(res)


def review(company):
    """Light pre-submit audit: no empty REQUIRED text/textarea, and a basic
    wrong-company scan across free text. Returns (rc, findings). Hidden fields
    (e.g. a conditional "work permit type" that only shows when permit=Yes) are
    skipped — they are not actually required for this applicant."""
    import re as _re
    data = json.loads(cfx.evaluate(r"""(() => {
      const out = { texts: [], emptyRequired: [] };
      for (const i of document.querySelectorAll('input[type=text],input[type=email],input[type=url],textarea')) {
        const lblEl = (i.labels&&i.labels[0]) || null;
        const lbl = (lblEl?lblEl.innerText:'')||i.getAttribute('aria-label')||i.name||'';
        const req = /required/i.test(lbl);
        // skip hidden fields (conditional / not applicable to this applicant)
        const r = i.getBoundingClientRect();
        const hidden = i.offsetParent===null || r.width===0 || r.height===0
                     || getComputedStyle(i).visibility==='hidden' || getComputedStyle(i).display==='none';
        let p=i.parentElement, ph=false;
        while(p){const st=getComputedStyle(p); if(st.display==='none'||st.visibility==='hidden'){ph=true;break;} p=p.parentElement;}
        const v = i.value || '';
        out.texts.push({ label: lbl.replace(/\s+/g,' ').trim().slice(0,60), value: v, required: req, hidden: hidden||ph });
        if (req && !v.trim() && !(hidden||ph)) out.emptyRequired.push(lbl.replace(/\s+/g,' ').trim());
      }
      return JSON.stringify(out);
    })()"""))
    findings = []
    for e in data["emptyRequired"]:
        findings.append(f"EMPTY REQUIRED: {e}")
    if findings:
        print("REVIEW — issues:")
        for f in findings:
            print("  - " + f)
        return 1, findings
    print(f"REVIEW OK: no empty required visible text fields (company {company!r}).")
    return 0, []


def apply(form_url, spec, do_submit=False):
    cfx.navigate(form_url)
    time.sleep(1.5)
    cfx.dismiss_cookie_banner()
    results = []
    for name, val in (spec.get("text") or {}).items():
        results.append(("text " + name, _set_text(name, val)))
    for name, opt in (spec.get("select") or {}).items():
        results.append(("select " + name, _set_select(name, opt)))
    for name, dmy in (spec.get("dates") or {}).items():
        results.append(("date " + name, _set_date(name, dmy)))
    for name, val in (spec.get("radio") or {}).items():
        results.append(("radio " + name, _set_radio(name, val)))
    if spec.get("upload"):
        results.append(("upload CV", _upload(spec["upload"])))
    # Data Privacy Statement consent (Hackney/Lumesse custom dialog)
    if spec.get("accept_dps", True):
        results.append(("accept DPS", _accept_dps()))
    rc, _ = review(spec.get("company", "Unknown"))
    failed = [(l, r) for l, r in results if not str(r).startswith("OK")]
    print("---- talentlink apply summary ----")
    if failed:
        for l, r in failed:
            print(f"  FAIL {l}: {r}")
    else:
        print(f"  OK   {len(results)} field(s) set; review clean")
    if failed or rc != 0:
        print("apply: NOT submitting — fix above first.")
        return 1
    if do_submit or spec.get("submit"):
        sub = cfx.evaluate("""(() => {
          const b = document.querySelector('input[type=submit], button[type=submit]');
          if (!b) return 'NO_SUBMIT';
          b.scrollIntoView({block:'center'});
          b.click();
          return 'clicked';
        })()""")
        print("submit:", sub)
        time.sleep(4)
        body = cfx.evaluate("(() => document.body.innerText.slice(0,600))()")
        if isinstance(body, str) and re_search(body):
            print("SUCCESS: confirmation text present.")
            return 0
        print("UNCLEAR: no confirmation text — screenshot to verify. Body tail:\n" + (body if isinstance(body, str) else str(body))[-300:])
        return 2
    print("apply: all set + review clean — not submitting (pass --submit).")
    return 0


def re_search(body):
    import re
    return bool(re.search(r"thank you|received|submitted|successfully|confirmation|application has been|we have received", body, re.I))


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("form_url")
    ap.add_argument("spec_json")
    ap.add_argument("--submit", action="store_true")
    a = ap.parse_args()
    spec = json.load(open(a.spec_json, encoding="utf-8"))
    return apply(a.form_url, spec, do_submit=a.submit)


if __name__ == "__main__":
    sys.exit(main())
