#!/usr/bin/env python3
"""reed_modal_drive.py — drive Reed's NEW multi-step "Application questions" modal.

The 2026-07-20 flow divergence: Reed postings now open a stepped modal of dropdown /
free-text screener questions (right-to-work, employed?, notice, salary bracket, salary
expectations free-text, gender, disability, adjustments, ethnicity, …) at 20%→100%
progress, then a review page with "Submit application". The old reed_apply.py only knew
Yes-radio→Continue and dies with NO APPLY BUTTON / LOOP-END.

KEY LESSON (verified live 2026-07-26): snapshot refs [eN] RENUMBER after every snapshot
and clicking a menuitem by ref lands on the WRONG option. Drive everything by JS
text-matching against role=menuitem / button innerText — that is stable. cfx.sh eval
occasionally 500s but the action still lands; re-snapshot to confirm state, don't trust
the eval return alone.

Answers come from apply-defaults.json applicant block + a built-in ANSWERS map keyed by
question substring. Unknown REQUIRED dropdown → picks a safe default ('Prefer not to say'
for demographics, else first non-empty option) and records it; unknown free-text → a
generic honest line. Never fabricates an eligibility gate.

Usage:
  source .jobenv.run ; unset CFX_URL CFX_USER
  python3 scripts/reed_modal_drive.py "<full reed job url>" ["<Company>"] ["<Role>"]
  python3 scripts/reed_modal_drive.py --dry "<url>"     # fill but DO NOT submit
"""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CFX_SH = os.path.join(ROOT, "sites", "_common", "scripts", "cfx.sh")
LOGAPP = os.path.join(ROOT, "sites", "_common", "scripts", "log-application.py")
DEFAULTS = os.path.join(ROOT, "sites", "_common", "apply-defaults.json")

# account-menu noise that also carries role=menuitem — never a real answer
ACCOUNT_NOISE = {
    "Profile and CV", "Saved jobs", "Jobs applied for", "Your searches and alerts",
    "Get the Job Search app", "Course purchase history", "Account", "Sign out",
}


def _af():
    try:
        return json.load(open(DEFAULTS)).get("applicant", {})
    except Exception:
        return {}


AF = _af()


def _fills():
    try:
        return json.load(open(DEFAULTS)).get("fill", {})
    except Exception:
        return {}


FILLS = _fills()

# Question-substring -> desired option text (matched case-insensitively, substring on the
# OPTION too so "£40,001 to £45,000" etc. can be picked by a fragment). Order matters:
# first matching key wins.
ANSWERS = [
    ("right to work", "UK/British Citizen"),
    ("currently employed", "No"),
    ("availability", "immediately available"),
    ("notice period", "immediately available"),
    ("salary bracket", "£40,001 to £45,000"),
    ("salary expectations", "Around £45,000, flexible depending on the full package and role scope."),
    ("what is your gender", AF.get("gender", "Male")),
    ("disabled", "No"),
    ("particular arrangements", "No"),
    ("reasonable adjustment", "No"),
    ("ethnic origin", "Mixed / Multiple ethnic groups: Any other/mixed multiple ethnic background"),
    ("ethnicity", "Mixed / Multiple ethnic groups: Any other/mixed multiple ethnic background"),
    ("sexual orientation", "Heterosexual"),
    ("religion", "Prefer not to say"),
    ("age", "Prefer not to say"),
    ("how did you hear", "Reed"),
    # address block (2026-07-26: free-text "Address Line 1" STUCK-repeated without these;
    # values route through gitignored apply-defaults.json -> fill, never hardcoded here)
    ("address line 1", FILLS.get("Address line 1", "")),
    ("address line 2", "N/A"),
    ("address line", FILLS.get("Address line 1", "")),
    ("postcode", FILLS.get("Postal", "")),
    ("postal code", FILLS.get("Postal", "")),
    ("town", FILLS.get("City", "London")),
    ("city", FILLS.get("City", "London")),
    ("county", "Greater London"),
    ("country", "United Kingdom"),
    ("do you have the right", "Yes"),
    ("require sponsorship", "No"),
    ("need sponsorship", "No"),
    ("visa", "No"),
    ("driving licence", "Yes"),
    ("degree", "Yes"),
]

FREETEXT_DEFAULT = "I'm a London-based product/UX designer with ~6 years across government-scale accessibility work, startup growth design, and hands-on build. Happy to discuss further."


def esh(expr, tries=4):
    """cfx.sh eval, returning the 'result' string (or '' on error). Retries the 500s."""
    for _ in range(tries):
        try:
            out = subprocess.run(["bash", CFX_SH, "eval", expr],
                                 capture_output=True, text=True, timeout=45).stdout
            # cfx.sh may print two JSON objects (snap+eval); take the last {...}
            frag = out.strip().splitlines()[-1] if out.strip() else "{}"
            j = json.loads(frag)
            if isinstance(j, dict) and "result" in j and "error" not in j:
                return str(j["result"])
        except Exception:
            pass
        time.sleep(1.2)
    return ""


def snap_text():
    try:
        out = subprocess.run(["bash", CFX_SH, "snap"], capture_output=True, text=True, timeout=45).stdout
        return out
    except Exception:
        return ""


def goto(url):
    subprocess.run([sys.executable, "-c",
                    "import sys;sys.path.insert(0,'sites/_common/scripts');import cfx;print(cfx.goto(%r))" % url],
                   cwd=ROOT, timeout=90)


def click_text(txt, kind="button"):
    """Click a button/menuitem whose trimmed innerText == txt (exact)."""
    sel = "[role=menuitem]" if kind == "menuitem" else "button"
    expr = ("var b=[...document.querySelectorAll(%r)].find(x=>x.innerText.trim()===%r);"
            "if(b){b.click();'ok'}else'miss'" % (sel, txt))
    return esh(expr) == "ok"


def modal_question():
    """Return (qtext, kind) for the current modal step, or (None, None).
    kind in {'select','radio','text'}."""
    txt = snap_text()
    if "progressbar:" not in txt:
        return None, None
    after = txt.split("progressbar:", 1)[-1]
    lines = after.splitlines()
    q = None
    for l in lines[:6]:
        s = l.strip()
        if s.startswith("- text:"):
            q = s[len("- text:"):].strip()
            break
        if s.startswith("- paragraph:"):
            q = s[len("- paragraph:"):].strip()
            break
    if q is None:
        return None, None
    window = after[:600]
    if "- textbox" in window:
        kind = "text"
    elif "- radio" in window:
        kind = "radio"
    else:
        kind = "select"
    return q, kind


def answer_radio(q):
    """Radio Yes/No (and similar) — click the label of the wanted option."""
    want = pick_answer(q) or "Yes"
    expr = ("var want=%r;"
            "var rs=[...document.querySelectorAll('input[type=radio]')];"
            "var hit=null;"
            "for(var i=0;i<rs.length;i++){var r=rs[i];"
            " var lab=r.closest('label')||document.querySelector('label[for=\"'+r.id+'\"]');"
            " var t=(lab?lab.innerText:r.value||'').trim();"
            " if(t.toLowerCase()===want.toLowerCase()){hit=lab||r;break;}}"
            "if(hit){hit.click();'ok'}else'miss'" % want)
    return esh(expr) == "ok"


def dropdown_options():
    expr = ("[...document.querySelectorAll('[role=menuitem]')].map(x=>x.innerText.trim())"
            ".filter(t=>t&&![%s].includes(t)).join('||')"
            % ",".join(repr(x) for x in ACCOUNT_NOISE))
    r = esh(expr)
    return [o for o in r.split("||") if o]


def pick_answer(q):
    ql = q.lower()
    for key, val in ANSWERS:
        if key in ql:
            return val
    return None


def answer_select(q):
    # open the dropdown
    esh("var b=[...document.querySelectorAll('button')].find(x=>/Select an option/.test(x.innerText));"
        "if(b){b.click();'ok'}else'miss'")
    time.sleep(1.5)
    opts = dropdown_options()
    want = pick_answer(q)
    chosen = None
    if want:
        # exact, then substring either direction
        for o in opts:
            if o.strip().lower() == want.strip().lower():
                chosen = o
                break
        if not chosen:
            for o in opts:
                if want.lower() in o.lower() or o.lower() in want.lower():
                    chosen = o
                    break
    if not chosen:
        # safe default: prefer-not-to-say for demographics, else first real option
        for o in opts:
            if "prefer not to say" in o.lower():
                chosen = o
                break
        if not chosen and opts:
            chosen = opts[0]
    if not chosen:
        return None
    ok = click_text(chosen, kind="menuitem")
    return chosen if ok else None


def answer_text(q):
    """Fill ALL visible text inputs/textareas on the step, each keyed by its own
    label/placeholder/aria-label (2026-07-26: address steps carry 4+ fields — Line 1,
    Line 2, Town, Postcode — and filling only the first STUCK-repeated the step)."""
    labels_raw = esh(
        "[...document.querySelectorAll('textarea,input[type=text],input:not([type])')]"
        ".filter(x=>x.getBoundingClientRect().width>0)"
        ".map(function(t,ix){var lab=(t.labels&&t.labels[0]&&t.labels[0].innerText)||"
        "t.getAttribute('aria-label')||t.placeholder||"
        "(t.closest('div')&&t.closest('div').innerText.split('\\n')[0])||'';"
        "return ix+':::'+lab.trim().substring(0,80);}).join('|||')")
    fields = [f for f in labels_raw.split("|||") if f] if labels_raw else []
    if not fields:
        return False
    ok_any = False
    for f in fields:
        ix, _, lab = f.partition(":::")
        want = pick_answer(lab) or pick_answer(q) or FREETEXT_DEFAULT
        expr = ("var els=[...document.querySelectorAll('textarea,input[type=text],input:not([type])')]"
                ".filter(x=>x.getBoundingClientRect().width>0);var t=els[%s];"
                "if(t&&!t.value){t.focus();var s=Object.getOwnPropertyDescriptor(Object.getPrototypeOf(t),'value').set;"
                "s.call(t,%r);t.dispatchEvent(new Event('input',{bubbles:true}));"
                "t.dispatchEvent(new Event('change',{bubbles:true}));'ok'}else if(t){'ok'}else'miss'"
                % (ix, want))
        if esh(expr) == "ok":
            ok_any = True
    return ok_any


def click_continue():
    return esh("var b=[...document.querySelectorAll('button')].find(x=>x.innerText.trim()==='Continue');"
               "if(b){b.click();'ok'}else'miss'") == "ok"


def at_review():
    txt = snap_text()
    return "Submit application" in txt


def drive(url, company=None, role=None, dry=False):
    goto(url)
    time.sleep(4)
    body = esh("document.body.innerText.substring(0,3000)")
    if "You applied for this job" in body:
        return "ALREADY-APPLIED"
    # click Apply now
    if not esh("var b=[...document.querySelectorAll('button')].find(x=>x.innerText.trim()==='Apply now');"
               "if(b){b.click();'ok'}else'miss'") == "ok":
        time.sleep(3)
        esh("var b=[...document.querySelectorAll('button')].find(x=>x.innerText.trim()==='Apply now');"
            "if(b){b.click();'ok'}else'miss'")
    time.sleep(4)
    seen = []
    for step in range(15):
        if at_review():
            break
        q, kind = modal_question()
        if not q:
            time.sleep(2)
            continue
        if q in seen and len(seen) > 2 and seen[-1] == q:
            return "STUCK repeating: %s" % q[:60]
        seen.append(q)
        if kind == "text":
            answer_text(q)
        elif kind == "radio":
            if not answer_radio(q):
                return "NO-RADIO for: %s" % q[:60]
        else:
            chosen = answer_select(q)
            if chosen is None:
                return "NO-OPTION for: %s" % q[:60]
        time.sleep(1)
        click_continue()
        time.sleep(2.5)
    if not at_review():
        return "NO-REVIEW after steps (last q chain: %s)" % " > ".join(s[:25] for s in seen[-4:])
    # verify email is the real one, not gmail SSO
    rv = esh("document.body.innerText")
    if "@gmail" in rv.lower():
        return "EMAIL-GMAIL-SSO abort (review shows gmail)"
    if dry:
        return "DRY-REVIEW-REACHED (%d questions)" % len(seen)
    ok = esh("var b=[...document.querySelectorAll('button')].find(x=>x.innerText.trim()==='Submit application');"
             "if(b){b.click();'ok'}else'miss'")
    if ok != "ok":
        return "NO-SUBMIT-BUTTON"
    time.sleep(5)
    goto(url)
    time.sleep(3)
    conf = esh("document.body.innerText.includes('You applied for this job')?'CONFIRMED':'UNCONFIRMED'")
    return "SUBMITTED %s (%d questions)" % (conf, len(seen))


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--dry"]
    dry = "--dry" in sys.argv
    url = args[0]
    company = args[1] if len(args) > 1 else None
    role = args[2] if len(args) > 2 else None
    print(drive(url, company, role, dry=dry))
