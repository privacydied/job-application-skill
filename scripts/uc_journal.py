#!/usr/bin/env python3
"""uc_journal.py — post job-application evidence to the Universal Credit journal.

Routine (run whenever new applications have been logged):
    python3 scripts/uc_journal.py run            # login (OTP prompt) -> dedup -> post
    python3 scripts/uc_journal.py run --dry-run  # build + fill the first entry, do NOT submit
    python3 scripts/uc_journal.py plan           # offline: show what would be posted

One-time setup (masked prompt; writes the gitignored ats-credentials.csv row):
    python3 scripts/uc_journal.py set-login

Flow per entry: Journal -> "Job applications" radio -> Continue -> Add a job ->
Job title/Employer = "multiple" -> status "Applied" -> When did you apply? = batch date ->
Notes = up to NOTES_MAX chars of application lines -> submit.

Source of applications: application-tracker.csv rows with Status == "Applied" (proven
submissions only; Applied?/Blocked/Skipped are never reported) dated >= --since.
Each journal entry has ONE apply date, so batches never mix dates.

Dedup (no duplicates in the journal): a row is skipped if its URL already appears
  (a) in the gitignored ledger uc-journal-posted.csv (written after every confirmed post), or
  (b) anywhere in the journal's existing entries (scraped live before posting).
The ledger is the fast path; the journal scrape is ground truth and seeds the ledger.

Secrets: username/password read at runtime from ats-credentials.csv (site
universal-credit.service.gov.uk). The OTP is typed by the user at a getpass prompt,
or written to the gitignored file .uc_otp (polled, then deleted). Nothing is hardcoded.
"""
import argparse
import csv
import datetime as dt
import getpass
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "sites" / "_common" / "scripts"))

TRACKER = ROOT / "application-tracker.csv"
CREDS = ROOT / "ats-credentials.csv"
LEDGER = ROOT / "uc-journal-posted.csv"
OTP_FILE = ROOT / ".uc_otp"
SITE = "universal-credit.service.gov.uk"
BASE = "https://www.universal-credit.service.gov.uk"
NOTES_MAX = 2990          # field allows 3000 (live counter verified: chars counted 1:1)
PLACEHOLDER = "multiple"  # Job title + Employer or agency (user's spec)
URL_RE = re.compile(r"https?://[^\s|()<>\"']+")


# ---------------------------------------------------------------- data side (no browser)
def norm_url(u):
    return (u or "").strip().rstrip("/.,)").lower()


def applied_rows(since):
    with open(TRACKER, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out, seen = [], set()
    for r in rows:
        if r["Status"] != "Applied" or r["Date"] < since:
            continue
        k = norm_url(r["URL"]) or f"{r['Company']}|{r['Role']}|{r['Date']}".lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


def ledger_urls():
    if not LEDGER.exists():
        return set()
    with open(LEDGER, newline="", encoding="utf-8") as f:
        return {norm_url(r["url"]) for r in csv.DictReader(f)}


def ledger_add(rows, entry_date, source):
    new = not LEDGER.exists()
    with open(LEDGER, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["posted_at", "entry_date", "url", "company", "role", "source"])
        now = dt.datetime.now().isoformat(timespec="seconds")
        for r in rows:
            w.writerow([now, entry_date, r["URL"], r["Company"], r["Role"], source])


def line(n, r):
    clean = lambda s: (s or "").replace("|", "/").replace("\n", " ").strip()
    return f"| {n} | {r['Date']} | {clean(r['Company'])} | {clean(r['Role'])} | {clean(r['Source'])} | ({r['URL'].strip()}) |"


def batches(rows, start_n):
    """Group pending rows by apply date, then pack each date into <=NOTES_MAX notes."""
    by_date = {}
    for r in rows:
        by_date.setdefault(r["Date"], []).append(r)
    n, out = start_n, []
    for d in sorted(by_date):
        cur, cur_lines = [], []
        for r in by_date[d]:
            ln = line(n + 1, r)
            if cur and len("\n".join(cur_lines + [ln])) > NOTES_MAX:
                out.append((d, cur, "\n".join(cur_lines)))
                cur, cur_lines = [], []
                ln = line(n + 1, r)
            cur.append(r)
            cur_lines.append(ln)
            n += 1
        if cur:
            out.append((d, cur, "\n".join(cur_lines)))
    return out


def pending(since, posted):
    return [r for r in applied_rows(since) if norm_url(r["URL"]) not in posted]


# ---------------------------------------------------------------- browser side
_CFX_READY = False


def cfx():
    """Import cfx and self-bootstrap the camofox env (key + live tab) on first use, so a
    plain `python3 scripts/uc_journal.py run` works from any shell without sourcing anything."""
    global _CFX_READY
    import cfx as _c
    if not _CFX_READY:
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = _c._init_hermes_env()
        if rc != 0 or not os.environ.get("CFX_TAB"):
            sys.exit("camofox bootstrap failed:\n" + buf.getvalue()[-1500:])
        _CFX_READY = True
    return _c


def ev(js):
    last = None
    for attempt in range(4):
        try:
            return cfx().evaluate(js, timeout=45)
        except Exception as e:  # camofox phantom HTTP 500s on evaluate — transient, retry
            last = e
            time.sleep(2 + attempt * 2)
    raise last


def text():
    return ev("document.body ? document.body.innerText : ''") or ""


def wait_load(t=1.5):
    time.sleep(t)
    cfx().poll("document.readyState", lambda s: s == "complete", timeout=20)


def set_field_by_label(label, value, scope_legend=None):
    """Fill input/textarea whose <label> (or fieldset legend + sub-label) matches."""
    js = """(() => {
      const want=%s.toLowerCase(), legend=%s, val=%s;
      let root=document;
      if (legend) { const fs=[...document.querySelectorAll('fieldset')].find(f=>{const l=f.querySelector('legend');return l&&l.innerText.toLowerCase().includes(legend.toLowerCase())}); if(!fs) return 'NOLEGEND'; root=fs; }
      const lab=[...root.querySelectorAll('label')].find(l=>l.innerText.trim().toLowerCase().startsWith(want));
      if(!lab) return 'NOLABEL';
      const el=lab.htmlFor?document.getElementById(lab.htmlFor):lab.querySelector('input,textarea');
      if(!el) return 'NOEL';
      const proto=el.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(proto,'value').set.call(el,val);
      el.dispatchEvent(new Event('input',{bubbles:true})); el.dispatchEvent(new Event('change',{bubbles:true}));
      return 'OK:'+el.value.length;
    })()""" % (json.dumps(label), json.dumps(scope_legend), json.dumps(value))
    r = ev(js)
    if not str(r).startswith("OK"):
        raise RuntimeError(f"field '{label}' ({scope_legend}): {r}")
    return r


def click_radio(label):
    r = ev("""(() => {const want=%s.toLowerCase();
      const lab=[...document.querySelectorAll('label')].find(l=>l.innerText.trim().toLowerCase()===want)
             || [...document.querySelectorAll('label')].find(l=>l.innerText.trim().toLowerCase().startsWith(want));
      if(!lab) return 'NOLABEL'; const el=lab.htmlFor?document.getElementById(lab.htmlFor):lab.querySelector('input');
      if(!el) return 'NOEL'; el.click(); return el.checked?'OK':'UNCHECKED';})()""" % json.dumps(label))
    if r != "OK":
        raise RuntimeError(f"radio '{label}': {r}")


def click_text(txt, exact=False):
    """Click a button / link / submit whose visible text matches."""
    r = ev("""(() => {const want=%s.toLowerCase(), exact=%s;
      const els=[...document.querySelectorAll('button,a,input[type=submit]')].filter(e=>e.offsetParent!==null||e.type==='submit');
      const t=e=>((e.innerText||e.value||'').trim().toLowerCase());
      const el=els.find(e=>t(e)===want)||(!exact&&els.find(e=>t(e).includes(want)));
      if(!el) return 'NOTFOUND'; el.click(); return 'OK';})()""" % (json.dumps(txt), json.dumps(exact)))
    if r != "OK":
        raise RuntimeError(f"click '{txt}': {r}")
    wait_load()


def error_summary():
    return ev("(()=>{const e=document.querySelector('.govuk-error-summary');return e?e.innerText:''})()") or ""


def get_creds():
    if CREDS.exists():
        found = None
        with open(CREDS, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if (r.get("site") or "").strip() == SITE:
                    found = (r["email"].strip(), r["password"])
        if found:
            return found
    if sys.stdin.isatty():
        print("No saved UC login — saving it now (one-time).")
        cmd_set_login(None)
        return get_creds()
    sys.exit(f"no '{SITE}' row in ats-credentials.csv — run: python3 scripts/uc_journal.py set-login")


def read_otp(timeout_s):
    if sys.stdin.isatty():
        return getpass.getpass("UC one-time code (hidden): ").strip()
    print(f"OTP_REQUIRED — write the code to {OTP_FILE.name} (e.g. read -rs c && printf %s \"$c\" > {OTP_FILE.name}); "
          f"waiting {timeout_s}s", flush=True)
    end = time.time() + timeout_s
    while time.time() < end:
        if OTP_FILE.exists():
            code = OTP_FILE.read_text().strip()
            OTP_FILE.unlink()
            if code:
                return code
        time.sleep(2)
    sys.exit("OTP timeout")


def signed_in():
    t = text().lower()
    return "sign out" in t and "sign in to your universal credit account" not in t


def login(otp_timeout):
    c = cfx()
    c.goto(BASE + "/sign-in")
    wait_load()
    if signed_in():
        print("already signed in")
        return
    user, pw = get_creds()
    c.dismiss_cookie_banner()
    # /sign-in can bounce to the /start landing page; follow its "Sign in" link to the form.
    if not ev("!!document.querySelector('input[type=password]')"):
        ev("(()=>{const a=[...document.querySelectorAll('a')].find(a=>/sign in to your universal credit account|^sign in$/i.test(a.innerText.trim()));a&&a.click()})()")
        wait_load(3)
        c.dismiss_cookie_banner()
    set_field_by_label("Username", user)
    set_field_by_label("Password", pw)
    ev("document.getElementById('id-submit-button').click()")
    wait_load(3)
    if signed_in():
        print("LOGIN_OK (no OTP)")
        return
    err = error_summary()
    if err:
        sys.exit(f"login rejected: {err}")
    # OTP page: the only visible text/number/tel input
    inp = ev("""(()=>{const i=[...document.querySelectorAll('input')].filter(e=>['text','tel','number'].includes(e.type)&&e.offsetParent!==null);
                return i.length?(i[0].id||i[0].name):''})()""")
    if not inp:
        sys.exit("unexpected page after password:\n" + text()[:1500])
    code = read_otp(otp_timeout)
    ev("""(()=>{const i=[...document.querySelectorAll('input')].filter(e=>['text','tel','number'].includes(e.type)&&e.offsetParent!==null)[0];
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(i,%s);
      i.dispatchEvent(new Event('input',{bubbles:true}));
      const b=i.form&&i.form.querySelector('button[type=submit],input[type=submit],button:not([type])'); if(b) b.click(); else i.form.submit();})()"""
       % json.dumps(code))
    wait_load(3)
    if not signed_in():
        sys.exit("OTP step failed:\n" + (error_summary() or text()[:1500]))
    print("LOGIN_OK")


WORK_SEARCH = BASE + "/work-search"


def open_job_applications():
    """User flow: Journal -> Add a journal entry -> 'Job applications' -> Continue -> /work-search."""
    c = cfx()
    c.goto(BASE + "/journal/add-journal-entry-flow-started")
    wait_load()
    ev("document.getElementById('clickable-WORK_SEARCH_JOB_APPLICATIONS').click()")
    ev("document.getElementById('id-submit-button').click()")
    wait_load(2)
    if "/work-search" not in (c.current_url() or ""):
        c.goto(WORK_SEARCH)
        wait_load()


def entry_key(date, company, role):
    k = lambda s: re.sub(r"\s+", " ", (s or "").strip().lower())
    return f"{k(date)}|{k(company)}|{k(role)}"


def journal_existing(max_pages=50):
    """Ground truth: everything already logged under Job applications (all /work-search pages).
    Returns (urls, keys, max_line_number). keys = date|company|role for note lines without URLs."""
    urls, keys, maxn = set(), set(), 0
    for page in range(1, max_pages + 1):
        cfx().goto(f"{WORK_SEARCH}?page={page}")
        wait_load(0.5)
        t = ev("[...document.querySelectorAll('li[id^=job-container-]').values()].map(e=>e.textContent).join('\\n')") or ""
        if not t.strip():
            break
        urls |= {norm_url(u) for u in URL_RE.findall(t)}
        for ln in t.splitlines():
            cells = [c.strip() for c in ln.strip().strip("|").split("|")]
            if cells and cells[0].isdigit():
                maxn = max(maxn, int(cells[0]))
                cells = cells[1:]
            if len(cells) >= 3 and re.match(r"\d{4}-\d{2}-\d{2}$", cells[0]):
                keys.add(entry_key(cells[0], cells[1], cells[2]))
    urls.discard("")
    return urls, keys, maxn


def set_value(el_id, value):
    r = ev("""(()=>{const el=document.getElementById(%s); if(!el) return 'NOEL';
      const proto=el.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(proto,'value').set.call(el,%s);
      el.dispatchEvent(new Event('input',{bubbles:true})); el.dispatchEvent(new Event('change',{bubbles:true}));
      return 'OK:'+el.value.length;})()""" % (json.dumps(el_id), json.dumps(value)))
    if not str(r).startswith("OK"):
        raise RuntimeError(f"field #{el_id}: {r}")


def post_entry(date, notes, dry_run, first_url):
    open_job_applications()
    ev("document.getElementById('add-job').click()")
    wait_load(2)
    if not (cfx().current_url() or "").rstrip("/").endswith("/work-search/job"):
        cfx().goto(WORK_SEARCH + "/job")
        wait_load()
    set_value("id-jobTitle", PLACEHOLDER)
    set_value("id-employer", PLACEHOLDER)
    if ev("(()=>{const r=document.getElementById('clickable-APPLIED'); r.click(); return r.checked})()") is not True:
        raise RuntimeError("Applied radio did not check")
    time.sleep(0.5)
    y, m, d = date.split("-")
    set_value("id-applicationDate.day", str(int(d)))
    set_value("id-applicationDate.month", str(int(m)))
    set_value("id-applicationDate.year", y)
    set_value("id-notes", notes)
    remaining = ev("(()=>{const p=[...document.querySelectorAll('main p,main div')].find(e=>/^You have [\\d,]+ characters? (remaining|too many)$/i.test(e.innerText.trim()));return p?p.innerText:''})()")
    print(f"  form filled: date {d}/{m}/{y}, notes {len(notes)} chars ({remaining.strip()})", flush=True)
    if "too many" in (remaining or "").lower():
        raise RuntimeError("notes over the 3,000 limit: " + remaining)
    if dry_run:
        print("DRY_RUN: form filled, NOT saved")
        return False
    ev("document.getElementById('id-submit-button').click()")
    wait_load(3)
    err = error_summary()
    if err:
        raise RuntimeError("save rejected: " + err)
    # verify: the new entry is on page 1 of /work-search
    cfx().goto(WORK_SEARCH)
    wait_load()
    if norm_url(first_url) not in {norm_url(u) for u in URL_RE.findall(text())}:
        raise RuntimeError("saved but entry not visible on /work-search — check manually before re-running")
    return True


# ---------------------------------------------------------------- commands
def cmd_set_login(_):
    user = input("UC username: ").strip()
    pw = getpass.getpass("UC password (hidden): ")
    # APPEND-ONLY. Never rewrite ats-credentials.csv: rows carry extra columns, and a
    # DictWriter rewrite raised mid-write and truncated the file once. get_creds() reads
    # the LAST matching row, so re-running set-login simply supersedes the old one.
    with open(CREDS, "rb") as f:
        data = f.read()
    needs_nl = bool(data) and not data.endswith(b"\n")
    with open(CREDS, "a", newline="", encoding="utf-8") as f:
        if needs_nl:
            f.write("\n")
        csv.writer(f).writerow([SITE, user, pw, dt.date.today().isoformat()])
    print("saved", SITE)


def cmd_plan(a):
    rows = pending(a.since, ledger_urls())
    b = batches(rows, a.start_n)
    print(f"{len(rows)} pending applications -> {len(b)} journal entries")
    for d, rs, notes in b:
        print(f"  {d}: {len(rs)} apps, {len(notes)} chars")
    if a.show and b:
        print("\n--- first entry notes ---\n" + b[0][2])


def cmd_login(a):
    login(a.otp_timeout)


def cmd_probe(a):
    login(a.otp_timeout)
    urls, keys, maxn = journal_existing()
    print(f"journal: {len(urls)} URLs, {len(keys)} date|company|role lines, last # = {maxn}")
    # human-checkable proof: page 1 of Job applications as text + screenshot
    c = cfx()
    c.goto(WORK_SEARCH)
    wait_load(3)
    proof = ROOT / "applications" / "_uc_proof"
    proof.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d_%H%M")
    (proof / f"work-search-{stamp}.txt").write_text(text())
    c.shot(str(proof / f"work-search-{stamp}.png"))
    print(text()[:2500])
    print(f"\nPROOF saved: {proof}/work-search-{stamp}.png (+ .txt)")


def cmd_run(a):
    login(a.otp_timeout)
    open_job_applications()
    urls, keys, maxn = journal_existing()
    print(f"journal already has {len(urls)} URLs + {len(keys)} URL-less lines; last # = {maxn}", flush=True)
    known = ledger_urls()
    seed = [r for r in applied_rows(a.since) if norm_url(r["URL"]) not in known
            and (norm_url(r["URL"]) in urls or entry_key(r["Date"], r["Company"], r["Role"]) in keys)]
    if seed:  # already on UC (posted by hand / earlier) — record so `plan` stays truthful offline
        ledger_add(seed, "", "journal-scrape")
    rows = [r for r in pending(a.since, ledger_urls())
            if norm_url(r["URL"]) not in urls and entry_key(r["Date"], r["Company"], r["Role"]) not in keys]
    plan = batches(rows, a.start_n or maxn)
    if a.limit:
        plan = plan[: a.limit]
    print(f"{len(rows)} new applications -> {len(plan)} entries to post", flush=True)
    for i, (d, rs, notes) in enumerate(plan, 1):
        print(f"[{i}/{len(plan)}] {d}: {len(rs)} apps", flush=True)
        ok = post_entry(d, notes, a.dry_run, rs[0]["URL"])
        if a.dry_run:
            print(notes)
            return
        if ok:
            ledger_add(rs, d, "posted")
            print("  saved + verified", flush=True)
    print("DONE")


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("set-login", "plan", "login", "probe", "run"):
        s = sub.add_parser(name)
        s.add_argument("--since", default="2026-09-04")
        s.add_argument("--otp-timeout", type=int, default=600)
        s.add_argument("--start-n", type=int, default=0, help="numbering offset for note lines")
        s.add_argument("--dry-run", action="store_true")
        s.add_argument("--limit", type=int, default=0, help="max entries this run")
        s.add_argument("--show", action="store_true")
    a = p.parse_args()
    {"set-login": cmd_set_login, "plan": cmd_plan, "login": cmd_login,
     "probe": cmd_probe, "run": cmd_run}[a.cmd](a)


if __name__ == "__main__":
    main()
