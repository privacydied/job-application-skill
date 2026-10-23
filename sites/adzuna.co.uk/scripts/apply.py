#!/usr/bin/env python3
"""apply.py — Adzuna ApplyIQ native apply form driver (sites/adzuna.co.uk).

Flow (verified 2026-10-23): /details/<id> -> link `.../details/<id>/apply?aztt=...` ("Apply for this
job") -> native form (First/Last/Email + saved-CV <select name=cvId> + employer screening questions
`screeningQuestionAnswers["<id>"]`) -> reCAPTCHA v2 -> "Submit Application" -> heading
"Application submitted: <Role>". Requires the email/password Adzuna login in the browser profile
(NOT Google SSO — see NOTES.md). Postings with no `/apply?aztt` link are external redirects: reported
`EXTERNAL`, not driven.

Usage:
  python3 apply.py <details_id|url> [--cv family-design.pdf] [--answers answers.json]
                   [--company "<Co>" --role "<Role>"] [--portfolio dz-portfolio.pdf] [--submit]
  Without --submit it fills + prints every field/answer for review and STOPS.
  answers.json = {"<question substring>": "<answer>"} (truthful, applicant's own). Unmatched
  required-looking questions are answered from screener.py's bank; anything still unknown is listed
  as UNRESOLVED and the driver refuses to submit (never blind-answers).
"""
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
COMMON = os.path.join(HERE, "..", "..", "_common", "scripts")
sys.path.insert(0, COMMON)
import cfx  # noqa: E402
import precheck  # noqa: E402
import screener  # noqa: E402

ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
LOGAPP = os.path.join(COMMON, "log-application.py")
DEFAULTS = json.load(open(os.path.join(COMMON, "..", "apply-defaults.json")))
FILL = DEFAULTS.get("fill", {})


def ev(expr, tries=4):
    for i in range(tries):
        try:
            return cfx.evaluate(expr)
        except Exception as e:  # noqa: BLE001
            err = str(e)
            time.sleep(2)
    raise RuntimeError(err)


FIELDS_JS = r"""(()=>{
const out=[];const seen=new Set();
document.querySelectorAll('form [name]').forEach(e=>{
  const n=e.name; if(!n||e.tagName==='IFRAME'||e.type==='hidden'||n==='g-recaptcha-response'||n==='q'||n==='w'||n==='cvFile') return;
  if((e.type==='radio'||e.type==='checkbox')&&seen.has(n)) return; seen.add(n);
  const opts=[];
  if(e.tagName==='SELECT') [...e.options].forEach(o=>opts.push(o.text.trim()));
  if(e.type==='radio'||e.type==='checkbox') document.querySelectorAll('[name="'+n.replace(/"/g,'\\"')+'"]').forEach(o=>{opts.push((o.labels&&o.labels[0]?o.labels[0].innerText:o.parentElement.innerText).trim())});
  let a=e,label='';
  for(let i=0;i<8&&a;i++){a=a.parentElement; if(!a)break;
    const t=(a.innerText||'').split('\n').map(s=>s.trim()).filter(s=>s&&!opts.includes(s));
    if(t.length&&t[0].length>2){label=t[0];break;}}
  const lb=(e.labels&&e.labels[0])?e.labels[0].innerText.trim():'';
  out.push({name:n,type:e.type||e.tagName.toLowerCase(),tag:e.tagName,label:(lb&&e.type!=='radio'&&e.type!=='checkbox'?lb:label).slice(0,260),opts:opts,val:(e.type==='radio'||e.type==='checkbox')?'':(e.value||'').slice(0,40),req:!!e.required||e.getAttribute('aria-required')==='true'});
});
return JSON.stringify(out);})()"""

SET_JS = r"""((name,val,mode)=>{
const els=[...document.querySelectorAll('[name]')].filter(e=>e.name===name);
if(!els.length) return 'NOFIELD';
const e=els[0];
if(e.tagName==='SELECT'){
  const o=[...e.options].find(o=>o.text.trim().toLowerCase()===val.toLowerCase())||[...e.options].find(o=>o.text.trim().toLowerCase().includes(val.toLowerCase()));
  if(!o) return 'NOOPTION:'+[...e.options].map(o=>o.text.trim()).join('|').slice(0,200);
  e.value=o.value;e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));return 'OK '+o.text.trim();
}
if(e.type==='radio'||e.type==='checkbox'){
  const vals=val.split('||').map(s=>s.trim().toLowerCase());
  let n=0;
  els.forEach(o=>{const t=((o.labels&&o.labels[0])?o.labels[0].innerText:o.parentElement.innerText).trim().toLowerCase();
    if(vals.includes(t)||vals.some(v=>t.includes(v))){ if(!o.checked) o.click(); n++; }});
  return n?'OK '+n:'NOOPTION:'+els.map(o=>((o.labels&&o.labels[0])?o.labels[0].innerText:o.parentElement.innerText).trim()).join('|').slice(0,200);
}
const proto=e.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;
Object.getOwnPropertyDescriptor(proto,'value').set.call(e,val);
e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));e.blur&&e.blur();
return 'OK '+e.value.length;})"""


def setf(name, val, mode=""):
    return ev("(%s)(%s,%s,%s)" % (SET_JS, json.dumps(name), json.dumps(val), json.dumps(mode)))


def open_form(job):
    m = re.search(r"(\d{8,})", job)
    jid = m.group(1)
    cfx.goto("https://www.adzuna.co.uk/details/%s" % jid)
    time.sleep(3)
    meta = json.loads(ev("""JSON.stringify({h1:(document.querySelector('h1')||{}).innerText||'',
      co:(document.querySelector('[class*=company],[class*=Company],.ui-company')||{}).innerText||'',
      t:document.title})"""))
    href = ev("""(()=>{const a=[...document.querySelectorAll('a')].find(a=>/\\/apply\\?aztt/.test(a.href)&&/Apply for this job/i.test(a.innerText));return a?a.href:'none'})()""")
    if href == "none":
        return jid, meta, False
    cfx.goto(href)
    time.sleep(7)
    return jid, meta, True


def answer_for(f, answers):
    q = f["label"].lower()
    n = f["name"]
    low = lambda s: re.sub(r"\s+", " ", s.lower())
    for k, v in answers.items():
        if low(k) in low(q):
            return v
    simple = {"firstname": None, "lastname": None, "email": None}
    if n in simple:
        return None  # prefilled from the Adzuna account
    key = re.sub(r'^screeningQuestionAnswers\["|"\]$', "", n)
    if key == "phone":
        return FILL.get("Phone")
    if key == "address":
        return FILL.get("City") or "London"
    if "pronoun" in q:
        return ""
    if "portfolio" in q and "link" in q or ("portfolio" in q and "online" in q):
        return FILL.get("Portfolio")
    if "linkedin" in q:
        return FILL.get("LinkedIn")
    if "notice" in q and "period" in q:
        return "Immediately"
    if "privacy" in q or "read and understood" in q:
        return "yes" if f["type"] == "select-one" else "I have read and understood"
    if "how did you hear" in q or "where you first heard" in q or "where did you hear" in q:
        return "Adzuna"
    if n == "optIn":
        return "No thanks"
    hit = screener.lookup(f["label"])
    if hit:
        a = hit.get("answer") if isinstance(hit, dict) else (hit[2] if isinstance(hit, (list, tuple)) else None)
        return a
    return None


def run(job, cv, answers, company, role, submit, portfolio=None):
    jid, meta, ok = open_form(job)
    title = role or meta.get("h1") or meta.get("t")
    print("[%s] %s | %s" % (jid, title, meta.get("co") or company))
    if not ok:
        print("EXTERNAL — no native ApplyIQ form (redirect to employer/agency site); not driven")
        return 3
    body = ev("document.body.innerText")
    if not re.search(r"Application for ", body):
        print("NOFORM — page is not the ApplyIQ form:", body[:150].replace("\n", " / "))
        return 4
    co = company or (re.search(r"-\s*([^\n]+)\n", body[body.find("Application for "):]) or [None, ""])[1]
    co = company or re.sub(r"^.* - ", "", (re.search(r"Application for [^\n]*\n([^\n]+)", body) or [None, ""])[1]).strip()
    if precheck.guard(url="https://www.adzuna.co.uk/jobs/details/%s" % jid, company=co, role=title, label="adzuna"):
        return 5
    # CV: pick saved CV by filename, newest
    sel = ev("""JSON.stringify([...document.querySelectorAll('select[name=cvId]')].map(s=>[...s.options].map(o=>o.value+'|'+o.text)))""")
    opts = json.loads(sel)[0] if json.loads(sel) else []
    pick = next((o for o in opts if cv in o), None)
    if pick:
        ev("""(()=>{const s=document.querySelector('select[name=cvId]');s.value=%s;s.dispatchEvent(new Event('change',{bubbles:true}));})()""" % json.dumps(pick.split("|")[0]))
        print("CV:", pick.split("|", 1)[1])
    else:
        print("CV: NOT FOUND in saved CVs ->", cv, "(upload path not implemented)")
        return 6
    fields = json.loads(ev(FIELDS_JS))
    if portfolio:
        n = ev("""(()=>{let n=0;document.querySelectorAll('input[type=file]').forEach(f=>{if(f.name==='cvFile')return;f.setAttribute('data-adz-up',String(n++));});return n;})()""")
        for i in range(int(n or 0)):
            try:
                cfx.post("/tabs/%s/upload" % cfx._tab(), {"userId": cfx._uid(), "selector": 'input[data-adz-up="%d"]' % i, "path": portfolio})
                print("PORTFOLIO FILE attached to extra file input", i, portfolio)
            except cfx.CfxError as e:
                print("portfolio upload FAIL:", e)
                return 9
    unresolved = []
    for f in fields:
        if f["name"] in ("cvId",):
            continue
        a = answer_for(f, answers)
        if a == "" and f["name"] not in ("firstName", "lastName", "email"):
            continue  # explicit skip (optional field left blank on purpose)
        if a is None:
            if f["name"] in ("firstName", "lastName", "email") or "pronoun" in f["label"].lower() or f["name"].endswith('"CA_2b1d"]'):
                continue
            if f["type"] in ("file",):
                continue
            unresolved.append(f)
            continue
        r = setf(f["name"], a)
        print("  %-9s %-60s <- %s  [%s]" % (f["type"][:9], f["label"][:60], str(a)[:50], r[:40]))
        if r.startswith(("NOFIELD", "NOOPTION")):
            unresolved.append(dict(f, why=r))
    if unresolved:
        print("UNRESOLVED (refusing to submit):")
        for f in unresolved:
            print("   -", f["name"], "|", f["type"], "|", f["label"][:120], "|", f["opts"][:8], f.get("why", ""))
        return 7
    print("FORM READY")
    if not submit:
        return 0
    rc = subprocess.run([sys.executable, os.path.join(COMMON, "recaptcha.py"), "click"], capture_output=True, text=True, timeout=120)
    print("recaptcha:", (rc.stdout or rc.stderr).strip()[-200:])
    ev("""[...document.querySelectorAll('button')].filter(b=>/Submit Application/i.test(b.innerText)).forEach(b=>b.setAttribute('data-sub','1'))""")
    cfx.click_selector('button[data-sub="1"]')
    for _ in range(12):
        time.sleep(3)
        body = ev("document.body.innerText")
        if re.search(r"Application submitted", body):
            break
    ok = bool(re.search(r"Application submitted", body))
    print("SUBMITTED" if ok else "NOT CONFIRMED: " + body[:200].replace("\n", " / "))
    if ok:
        slug = re.sub(r"[^a-z0-9]+", "-", ("%s-%s" % (co, title)).lower()).strip("-")[:60]
        d = os.path.join(ROOT, "applications", slug)
        os.makedirs(d, exist_ok=True)
        pf = os.path.join(d, "confirmation.txt")
        open(pf, "w").write(body[:800])
        subprocess.run([sys.executable, LOGAPP, co, title, "Adzuna", "https://www.adzuna.co.uk/jobs/details/%s" % jid,
                        "Applied", "--proof", pf, "--notes", "Adzuna ApplyIQ native form; confirmation heading captured"])
        return 0
    return 8


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a:
        print(__doc__)
        sys.exit(2)

    def opt(k, d=None):
        return a[a.index(k) + 1] if k in a else d

    answers = json.load(open(opt("--answers"))) if opt("--answers") else {}
    sys.exit(run(a[0], opt("--cv", "family-design.pdf"), answers, opt("--company"), opt("--role"), "--submit" in a, opt("--portfolio")))
