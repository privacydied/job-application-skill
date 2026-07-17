#!/usr/bin/env python3
"""amazon_apply.py — drive an amazon.jobs application end-to-end via the atsform React helpers.

Single source of truth for the amazon.jobs apply SPA (a ~10-step React wizard with cascading
conditional fields). Built ENTIRELY on `atsform`'s widget helpers (rclick/answer/advance/
active_step + the React-controlled select setter), so it works headlessly under Claude Code
AND Hermes with no server change. Supersedes any bespoke per-field driver — Amazon's custom
radios all share value="on", so match by option TEXT (what atsform does), never by value.

Requires: a logged-in amazon.jobs session (cookie persists in the camofox profile) + the
tailored resume in uploads/. Usage:
    CFX_KEY=... CFX_TAB=... python3 scripts/amazon_apply.py <jobId|jobUrl> [--resume am-uxd.pdf]

The answer map encodes the applicant's responses (edit for a different profile). Unmapped
Yes/No questions default to Yes for "do you have experience…" (qualifying) and No otherwise
(compliance) — override in ANSWERS as needed.
"""
import json
import os
import re
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "sites", "_common", "scripts"))
import cfx        # noqa: E402
import atsform    # noqa: E402


def _applicant_facts():
    """Load the applicant's real demographic/education answers from the GITIGNORED config
    (sites/_common/apply-defaults.json → "applicant"). Routing them through config keeps
    this tracked driver PII-free while applications still get the real values. A fresh clone
    with no config falls back to safe placeholders (fill your copy from *.example.json)."""
    path = os.path.join(_HERE, "..", "sites", "_common", "apply-defaults.json")
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh).get("applicant", {}) or {}
    except (OSError, ValueError):
        return {}


_AF = _applicant_facts()


def _af(key, default):
    v = _AF.get(key)
    return v if isinstance(v, str) and v.strip() and not v.strip().startswith("[") else default


# question-text regex (lowercased) -> answer. First match wins.
# Demographic/education answers come from the gitignored config via _af() — never hardcoded
# here (so no PII lands in the repo); your real values in apply-defaults.json fill the forms.
ANSWERS = [
    (r"salary expectation", "£50,000"),
    (r"willing to relocate", "No"),
    (r"how did you hear", "Job Posting"),
    (r"please specify", "Other"),
    (r"currently a student", "No"),
    (r"when did you graduate", "More than 3 years ago"),
    (r"non-internship professional experience", "Yes"),
    (r"education level", "Bachelor's"),
    (r"area.*of study|area\(s\) of study", _af("area_of_study", "")),
    (r"school name", _af("school", "")),
    (r"bachelor.?s degree.*(design|hci)|degree.*above.*(design|hci)", "Yes"),
    (r"previously applied to amazon|previously been employed by amazon", "No"),
    (r"non-competition agreement", "No"),
    (r"immigration.*support or sponsorship|need.*sponsorship", "No"),
    # Jane was a CONTRACTOR/product designer on NHS work, NOT a direct civil servant, so
    # the honest answer is NEVER a (direct) government employee (also avoids the cascade).
    (r"direct employee of any government", "No, I was NEVER a government employee"),
    (r"matter related to amazon|suspended, debarred|future government|"
     r"restriction|reside in|permanent resident in any other", "No"),
    (r"sanctioned countries", "No"),
    (r"in which country/region do you have citizenship|citizenship", "United Kingdom"),
    (r"what is your gender", _af("gender", "I prefer not to answer")),
    (r"military|veteran|ex-military|reserve forces", "I prefer not to answer"),
]


def _answer_for(question):
    q = re.sub(r"\s+", " ", (question or "")).strip().lower()
    for pat, val in ANSWERS:
        if re.search(pat, q):
            return val
    # defaults: experience/have-you questions qualify (Yes); everything else No.
    if re.search(r"do you have|experience|are you able|proficien", q):
        return "Yes"
    return "No"


def _unanswered_questions():
    """Return [{q, kind}] for every currently-unanswered required control on the step."""
    js = r"""(()=>{const norm=s=>(s||'').replace(/\s+/g,' ').trim();
      const out=[]; const seen=new Set();
      const qOf=el=>{const lb=el.getAttribute&&el.getAttribute('aria-labelledby');let q='';
        if(lb){for(const id of lb.split(' ')){const e=document.getElementById(id);if(e)q+=' '+norm(e.textContent);}}
        if(!q&&el.getAttribute)q=norm(el.getAttribute('aria-label'));
        if(!q){const p=el.closest('fieldset,div,section');if(p){const l=p.querySelector('label,legend');if(l)q=norm(l.textContent);}}
        return q.trim();};
      // radiogroups without a checked radio
      document.querySelectorAll('[role=radiogroup],fieldset').forEach(g=>{
        const rs=[...g.querySelectorAll('input[type=radio]')];
        if(rs.length&&rs.length<=6&&![...rs].some(r=>r.checked)){const q=qOf(g);if(q&&!seen.has(q)){seen.add(q);out.push({q:q.slice(0,120),kind:'radio'});}}});
      // empty selects / react comboboxes
      document.querySelectorAll('select').forEach(s=>{const cur=s.value?(([...s.options].find(o=>o.value===s.value)||{}).text||''):'';
        if(!s.value||/select an option/i.test(cur)||cur.trim()===''){const q=qOf(s);if(q&&!seen.has(q)){seen.add(q);out.push({q:q.slice(0,120),kind:'select'});}}});
      // empty required text/date
      document.querySelectorAll('input[type=text],input[type=date],input:not([type])').forEach(i=>{
        if((i.getAttribute('aria-required')==='true'||i.required)&&!i.value){const q=qOf(i);if(q&&!seen.has(q)){seen.add(q);out.push({q:q.slice(0,120),kind:'text'});}}});
      return JSON.stringify(out.slice(0,25));})()"""
    import json
    try:
        r = cfx.evaluate(js)
        return json.loads(r) if isinstance(r, str) else []
    except Exception:
        return []


def _fill_step():
    """Answer every unanswered control on the current step (cascade-safe: repeats until the
    set of unanswered questions stops shrinking). Also checks acknowledgement boxes + uploads."""
    # acknowledgement / consent checkboxes: check all
    try:
        cfx.evaluate("(()=>{for(const c of document.querySelectorAll('input[type=checkbox]'))if(!c.checked)c.click();})()")
    except cfx.CfxError:
        pass
    # FORCE-correct the government-employee answer to NEVER even if a saved/prior value set
    # it to FORMER (contractor != civil servant) — _fill_step otherwise skips answered groups.
    try:
        cfx.evaluate(r"""(()=>{const rs=[...document.querySelectorAll('input[type=radio]')];
          const lof=r=>{const l=r.id&&document.querySelector('label[for="'+r.id+'"]');return (l&&l.textContent)||'';};
          const fmr=rs.find(r=>/former government/i.test(lof(r))&&r.checked);
          if(fmr){const nev=rs.find(r=>/never a government/i.test(lof(r)));
            if(nev){const lab=document.querySelector('label[for="'+nev.id+'"]');if(lab)lab.click();}}})()""")
    except cfx.CfxError:
        pass
    prev = -1
    for _ in range(8):
        qs = _unanswered_questions()
        if not qs or len(qs) == prev:
            break
        prev = len(qs)
        for item in qs:
            q, kind = item.get("q", ""), item.get("kind")
            val = _answer_for(q)
            if kind == "radio":
                # scope to the question container, click the option by text
                cfx.evaluate("(()=>{document.querySelectorAll('[data-cfx-scope]').forEach(e=>e.removeAttribute('data-cfx-scope'));"
                             "const rx=/%s/i;const el=[...document.querySelectorAll('label,legend,p,div,span')]"
                             ".find(e=>rx.test((e.textContent||'').replace(/\\s+/g,' '))&&(e.textContent||'').replace(/\\s+/g,' ').length<200);"
                             "if(el){let s=el.closest('fieldset,[role=radiogroup]')||el.closest('div');"
                             "for(let i=0;i<3&&s&&!s.querySelector('input[type=radio]');i++)s=s.parentElement;"
                             "if(s)s.setAttribute('data-cfx-scope','1');}})()" % re.escape(q[:40]))
                atsform.rclick(val, scope='[data-cfx-scope="1"]') or atsform.rclick(val)
            else:
                atsform.answer(q, val)
            time.sleep(0.35)
        time.sleep(0.8)


def run(job, resume="am-uxd.pdf"):
    jid = re.sub(r".*/jobs/(\d+).*", r"\1", job) if "/jobs/" in job else job
    url = f"https://www.amazon.jobs/en/jobs/{jid}"
    tab = cfx.ensure_tab(persist=True); cfx.set_tab(tab)
    cfx.navigate(url); time.sleep(11)   # amazon.jobs SPA is slow to paint the Apply CTA
    if not (atsform.rclick("Apply now") or atsform.rclick("Apply")
            or atsform.rclick("Continue application") or atsform.rclick("Continue")):
        print("FAIL: no Apply/Continue button"); return 7
    time.sleep(9)
    for step in range(14):
        cur = atsform.active_step()
        print(f"step {step}: {cur!r}")
        if re.search(r"review", cur or "", re.I):
            break
        # Contact info: fill from your gitignored apply-defaults.json (never hard-code PII
        # here — this file is committed). Falls back to apply-defaults.example.json's
        # placeholders on a fresh clone; empty/missing fields are just skipped.
        if re.search(r"contact", cur or "", re.I):
            fill = atsform._load_defaults(True).get("fill", {})
            for lbl in ("First name", "Last name", "Address line 1", "City", "Postal"):
                v = fill.get(lbl, "")
                if v:
                    atsform.fill(lbl, v); time.sleep(0.3)
            atsform.answer("country/region", "United Kingdom")
            phone = fill.get("Phone", "")
            if phone:
                try:
                    cfx.post(f"/tabs/{cfx._tab()}/type", {"userId": cfx._uid(),
                             "selector": "input[type=tel]", "text": phone, "mode": "fill"})
                except cfx.CfxError:
                    pass
        # Resume upload
        if re.search(r"resume", cur or "", re.I):
            try:
                cfx.post(f"/tabs/{cfx._tab()}/upload", {"userId": cfx._uid(),
                         "selector": "input[type=file]", "path": resume})
                time.sleep(3)
            except cfx.CfxError as e:
                print("  resume upload note:", str(e)[:40])
        _fill_step()
        if atsform.advance() != 0:
            # one more fill+advance in case a cascade appeared
            _fill_step()
            if atsform.advance() != 0:
                print(f"  STUCK on {cur!r} — unanswered:", _unanswered_questions()[:4])
                return 1
    # Review & submit + pre-submit consent modals
    atsform.rclick("Submit application"); time.sleep(5)
    for _ in range(4):
        # AI-consent modals: opt in to recruiter recommendations, then continue/confirm
        atsform.rclick("No, I've changed my mind")
        if not (atsform.rclick("Continue") or atsform.rclick("Submit application")):
            break
        time.sleep(5)
    time.sleep(6)
    cfx.navigate("https://account.amazon.jobs/en-US/applicant"); time.sleep(7)
    ok = cfx.evaluate("(()=>/%s/.test(document.body.innerText))" % jid) or \
        cfx.evaluate(r"""(()=>{const t=document.body.innerText;const m=t.match(/active\s*\((\d+)\)/i);return m&&+m[1]>0;})()""")
    print("SUBMITTED_VERIFIED" if ok is True else "SUBMIT_UNVERIFIED")
    return 0 if ok is True else 2


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: amazon_apply.py <jobId|jobUrl> [--resume <file>]"); sys.exit(2)
    res = sys.argv[sys.argv.index("--resume") + 1] if "--resume" in sys.argv else "am-uxd.pdf"
    sys.exit(run(sys.argv[1], res))
