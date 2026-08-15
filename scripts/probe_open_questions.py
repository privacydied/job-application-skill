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
    seen, uniq = set(), []
    for q in open_qs:
        q = re.sub(r"^\*?(?:text|textarea|select-one|email|choice|file):\s*", "", q).strip()
        if q and q.lower() not in seen:
            seen.add(q.lower())
            uniq.append(q)
    return {"config": path, "open": uniq,
            "submitted_ok": "SUCCESS" in out or "APPLIED_OK" in out}


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
