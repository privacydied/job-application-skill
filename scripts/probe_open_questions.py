#!/usr/bin/env python3
"""probe_open_questions.py — batch-collect the REQUIRED questions a run still cannot answer.

WHY (2026-08-15). After the screener bank, EEO and location fixes, the postings that still
refuse to submit are the ones asking genuine per-role FREE TEXT ("What interaction design
project are you most proud of?", "Why do you want to work here?"). Those are answerable
truthfully from references/applicant-profile.md — but only by the model, one posting at a
time, and discovering them costs a full nav+fill per posting.

Doing that discovery inline means one model turn per posting just to LEARN the question. This
script does the whole discovery pass in ONE subprocess: for each queue row it fills everything
automatable (config + defaults + EEO + screener bank) WITHOUT submitting, then reports only
the required fields still empty. The model then writes every answer in a single turn and a
second pass fills + submits. Same batching lever as tailor.py / pipeline.py.

It NEVER submits: it is the read half of the loop.

USAGE:
  python3 scripts/probe_open_questions.py <urls.txt> [--out worklist.json]
    urls.txt: one `ats|company|role|url` per line (ats = greenhouse|lever|ashby)
"""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DRIVERS = {
    "greenhouse": os.path.join(ROOT, "sites", "greenhouse", "scripts", "gh_apply.py"),
    "lever": os.path.join(ROOT, "sites", "lever", "scripts", "lever.py"),
    "ashby": os.path.join(ROOT, "sites", "ashbyhq", "scripts", "ashby.py"),
}
RUNCFG = os.path.join(ROOT, "runcfg")


def _slug(*p):
    s = "-".join(str(x or "") for x in p).lower()
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s)).strip("-")[:80] or "posting"


def probe(ats, company, role, url):
    os.makedirs(RUNCFG, exist_ok=True)
    cfg = {"cv": "base-resume.pdf", "company": company, "role": role, "url": url,
           "source": {"lever": "Lever", "ashby": "Ashby"}.get(ats, "Greenhouse"),
           "defaults": True, "fill": {}, "no_submit": True}
    path = os.path.join(RUNCFG, f"{_slug(company, role)}.{ats}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    if ats == "lever":
        cmd = [sys.executable, DRIVERS[ats], "apply", path]        # no --submit
    elif ats == "ashby":
        cmd = [sys.executable, DRIVERS[ats], "apply", path]
    else:
        cmd = [sys.executable, DRIVERS[ats], path]                 # no_submit in the config
    try:
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=420)
    except subprocess.TimeoutExpired:
        return {"config": path, "open": [], "note": "timeout"}
    out = (r.stdout or "") + (r.stderr or "")
    open_qs = []
    for m in re.finditer(r"REQUIRED STILL EMPTY: \[(.*?)\]", out):
        open_qs += [x.strip(" '\"") for x in m.group(1).split("', '")]
    # Ashby/Greenhouse phrase it as a content-review list instead.
    for m in re.finditer(r"^\s+- (?:text|unanswered radio): (.+)$", out, re.M):
        open_qs.append(m.group(1).strip())
    for m in re.finditer(r"UNANSWERED_REQUIRED: (.+?)\s*\[", out):
        open_qs.append(m.group(1).strip())
    # ⛔ ASK THE DOM, NOT THE LOG (2026-08-15). Parsing driver stdout is per-driver and
    # therefore wrong: "REQUIRED STILL EMPTY" is lever.py's wording, gh_apply never prints it,
    # and with `no_submit` set nothing bounces so no validation text appears either. The first
    # version of this probe consequently reported "NONE (ready to submit)" for eight postings
    # that were in fact blocked — a false all-clear, which is the worst possible answer here.
    # Read the live form instead: every unmet REQUIRED control, grouped, with its question.
    # A CLOSED posting has no form at all, so `open` comes back empty — which reads as
    # "ready to submit", the same false all-clear the DOM check was added to kill. Detect it
    # explicitly (Lever: "we couldn't find anything here… might have closed").
    if re.search(r"couldn.t find anything here|posting .{0,20}might have closed|"
                 r"no longer accepting|position (has been )?closed", out, re.I):
        return {"config": path, "open": ["__POSTING_CLOSED__"], "submitted_ok": False}
    open_qs += _dom_unmet()
    seen, uniq = set(), []
    for q in open_qs:
        q = re.sub(r"^\*?(?:text|textarea|select-one|email|choice|file):\s*", "", q).strip()
        if q and q.lower() not in seen:
            seen.add(q.lower())
            uniq.append(q)
    return {"config": path, "open": uniq,
            "submitted_ok": "SUCCESS" in out or "APPLIED_OK" in out}


_DOM_UNMET = r"""
(() => {
  const clean = s => (s||'').replace(/\s+/g,' ').trim();
  // Climb PAST the control's own rendering. A react-select shows "Select...", a chosen radio
  // shows its own option text — stopping at the first non-empty ancestor returns THAT, not the
  // question, which made the first DOM probe report open items called "Select..." and "Yes".
  // Keep going until the ancestor says something the control itself doesn't.
  const q = e => {
    const own = clean(e.innerText || e.value || '');
    let t = clean(e.labels && e.labels[0] ? e.labels[0].innerText : '');
    if (t && t !== own) return t;
    let b = e;
    for (let k=0;k<6&&b;k++){
      b = b.parentElement; if (!b) break;
      const x = clean(b.innerText);
      if (!x || x.length >= 300) continue;
      if (own && (x === own || x.replace(own,'').trim().length < 3)) continue;
      return x;
    }
    return t || e.name || e.id || '?';
  };
  const groups = {};
  for (const e of document.querySelectorAll('input,select,textarea')) {
    const ty = (e.type||'').toLowerCase();
    if (ty === 'submit' || ty === 'button' || ty === 'reset' || ty === 'image') continue;
    if (!e.required) continue;
    const key = e.name || e.id || Math.random();
    const ok = (ty === 'checkbox' || ty === 'radio') ? e.checked
             : (ty === 'file' ? !!(e.files && e.files[0]) : !!clean(e.value));
    if (!(key in groups)) groups[key] = {ok: false, q: q(e)};
    groups[key].ok = groups[key].ok || ok;
  }
  const out = [];
  for (const g of Object.values(groups)) if (!g.ok) out.push(g.q.slice(0, 200));
  // react-select renders no <select>, so a required combobox shows up only as an empty control
  for (const c of document.querySelectorAll('[class*="select__control"]')) {
    if (c.querySelector('[class*="singleValue"],[class*="multi-value"]')) continue;
    const own = clean(c.innerText || '');
    let b = c, t = '';
    for (let k=0;k<6&&b;k++){ b=b.parentElement; if(!b) break;
      const x = clean(b.innerText);
      if (!x || x.length >= 300) continue;
      if (own && (x === own || x.replace(own,'').trim().length < 3)) continue;
      t = x; break; }
    if (t && /\*|✱|required/i.test(t)) out.push(t.slice(0, 200));
  }
  return JSON.stringify([...new Set(out)]);
})()
"""


def _dom_unmet():
    """Every REQUIRED control on the live form that is still unanswered, by question text."""
    sys.path.insert(0, os.path.join(ROOT, "sites", "_common", "scripts"))
    try:
        import cfx  # noqa: PLC0415
        return json.loads(cfx.evaluate(_DOM_UNMET))
    except Exception:  # noqa: BLE001 — a probe that can't read the DOM reports nothing extra
        return []


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    out_path = None
    if "--out" in sys.argv:
        out_path = sys.argv[sys.argv.index("--out") + 1]
    work = []
    for line in open(sys.argv[1], encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        ats, company, role, url = [p.strip() for p in line.split("|", 3)]
        print(f">>> probe [{ats}] {company} :: {role}", file=sys.stderr)
        res = probe(ats, company, role, url)
        res.update(ats=ats, company=company, role=role, url=url)
        work.append(res)
        print(f"    open: {res['open'] or 'NONE (ready to submit)'}", file=sys.stderr)
    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(work, f, indent=1, ensure_ascii=False)
    print(json.dumps(work, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
