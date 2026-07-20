#!/usr/bin/env python3
"""
apply_ea.py — drive ONE LinkedIn Easy Apply application end-to-end.

`easyapply.py` ships only PRIMITIVES (open/state/fill/radio/select/next/submit/
upload); there was no end-to-end driver, so a run meant orchestrating those by
hand turn-by-turn. This wraps them into a single call with the hard-won fixes:

  - tab self-heal on death (404 / connection error): reopen a fresh job-apply tab
    and update CFX_TAB for the child easyapply.py calls, then retry.
  - navigate retry loop (the engine blips mid-nav).
  - screener auto-answer from a KNOWN map, dispatched by widget kind
    (radio vs <select> vs text) — fixes the sponsorship-radio / location-select
    mis-fills.
  - NEEDS_HUMAN bail (exit 7) on an unknown required screener or a
    BLOCKED_UNANSWERED_REQUIRED from `next` — no infinite loops.
  - resume re-upload on the Resume step EVERY posting (LinkedIn persists the
    previous posting's PDF — see references/easyapply-resume-persistence.md).
  - robust submit confirmation: trust `submit`'s own "SUCCESS: application sent"
    first, then fall back to polling state header / the job page's "Applied"
    button. (The ad-hoc predecessor ignored submit's stdout and raced, exiting
    without logging a real submission.)
  - proof + log: on success, screenshot the confirmation AND always write a
    confirmation.txt with the detected evidence, then log via log-application.py
    --proof (satisfies the Applied proof-gate even if the screenshot endpoint
    flakes).

Usage:
    apply_ea.py <job_id|job_url> <Company> <Role> [--resume <container_path>]
                [--source "<src>"] [--notes "<extra>"] [--max-attempts N]
                [--dry-run]

  <job_id|job_url>  bare LinkedIn numeric id, or a full /jobs/view/<id> URL.
  --resume          path the BROWSER CONTAINER sees (default /uploads/base-resume.pdf;
                    per-role tailored PDFs also live under /uploads/). NOT a host path.
  --dry-run         walk to the Review step and STOP — never clicks Submit and never
                    logs. Use to smoke-test the whole flow on a real posting safely.

Exit codes: 0 submitted+logged · 3 all attempts failed (no confirmation) ·
            7 NEEDS_HUMAN (unknown/blocked required screener) · 9 no tab available ·
            5 dry-run reached Review OK (nothing submitted).
"""
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))                 # sites/linkedin/scripts
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))      # skill root
COMMON = os.path.join(ROOT, "sites", "_common", "scripts")
EASYAPPLY = os.path.join(HERE, "easyapply.py")
LOGAPP = os.path.join(COMMON, "log-application.py")
CFXSH = os.path.join(COMMON, "cfx.sh")
sys.path.insert(0, COMMON)
import cfx  # noqa: E402
import screener  # noqa: E402  — shared persistent answer bank (screener-answers.csv)

# Easy-Apply screener answers (label-substring -> value). Source of truth is
# references/applicant-profile.md + sites/_common/apply-defaults.json — keep in
# sync when a fact changes. Ordered longest/most-specific first so e.g.
# "require sponsorship" wins before the bare "sponsorship".
KNOWN = {
    "current location": "London, United Kingdom",
    "willing to relocate": "No",
    "legally authorized": "Yes",
    "authorized to work": "Yes",
    "right to work": "Yes",
    "require sponsorship": "No",
    "visa sponsorship": "No",
    "sponsorship": "No",
    "notice period": "Immediately",
    "available to start": "Immediately",
    "years of experience": "5",
    "email alerts": "No",
    "location": "London",
    "city": "London",
}
RADIO_KEYS = {"willing to relocate", "legally authorized", "authorized to work",
              "right to work", "require sponsorship", "visa sponsorship", "sponsorship",
              "notice period", "available to start", "email alerts"}
SELECT_KEYS = {"current location", "location", "city"}


def ea(*args):
    """Run an easyapply.py primitive, return its stdout (stripped)."""
    r = subprocess.run([sys.executable, EASYAPPLY, *args],
                       capture_output=True, text=True, cwd=ROOT)
    return (r.stdout or "").strip()


def state():
    try:
        return json.loads(ea("state"))
    except (ValueError, TypeError):
        return {}


def heal_tab():
    """Ensure a live tab; reopen + propagate CFX_TAB to child calls if dead."""
    try:
        cfx.current_url()
        return True
    except Exception:
        pass
    for _ in range(4):
        try:
            cfx.set_tab(cfx.ensure_tab(persist=False))
            return True
        except Exception as e:
            print("heal failed:", e)
            time.sleep(4)
    return False


def set_field(label, val, kind):
    """Set a screener field by trying every primitive until one sticks.

    LinkedIn renders the same yes/no question as EITHER a radio group OR a native
    <select> dropdown (varies per posting), and text/number questions as inputs.
    The bank stores the *intended* kind, but we must not trust it — try the
    kind-appropriate primitive first, then fall back across all three, because a
    'radio' answer that's actually a <select> returns NOT_FOUND and a naive
    fill() only sees text/number inputs (so it NO_FIELDs on selects/radios),
    leaving the required question empty and the whole application BLOCKED."""
    cands = []
    if kind == "radio":
        cands = [("radio", label), ("select", label), ("fill", label)]
    elif kind in ("select", "boolean"):
        cands = [("select", label), ("radio", label), ("fill", label)]
    else:  # text / number
        cands = [("fill", label), ("select", label), ("radio", label)]
    for prim, key in cands:
        r = ea(prim, key, val)
        if isinstance(r, str) and r.startswith("OK"):
            return r
    # last resort: try the bare value/label text on fill (catches mislabeled kinds)
    r = ea("fill", label, val)
    return r


def answer_screeners(labels):
    """Answer every known screener label on the current step. Return True if all
    labels were matched to a KNOWN answer, False if any is unknown (=> human)."""
    all_known = True
    for lab in labels:
        low = lab.lower()
        hit = next((k for k in KNOWN if k in low), None)
        if hit:
            val, kind = KNOWN[hit], ("radio" if hit in RADIO_KEYS
                                     else "select" if hit in SELECT_KEYS else "text")
            key = hit
        else:
            # Fall through to the SHARED, persistent answer bank (screener.py) before
            # deciding a question is unknown — a phrasing this LinkedIn map never had
            # may already be answered there (and every ATS shares those answers).
            bank = screener.lookup(lab)
            if bank:
                val, kind, key = bank["answer"], bank["kind"], bank["pattern"]
            else:
                # A section header ("Additional Questions") isn't a question; only bail
                # on labels that look like real prompts.
                if re.search(r"\?|experience|sponsor|authori|reloc|notice|salary|start|location|comfortable|commut|education|degree|proficien", low):
                    all_known = False
                continue
        r = set_field(key if key in KNOWN else lab, val, kind)
        print(f"  screener [{key}] = {val} -> {r[:40]}")
    return all_known


def capture_proof_and_log(company, role, url, source, notes, submit_out, post):
    slug = re.sub(r"[^a-z0-9]+", "-", f"{company}-{role}".lower()).strip("-") or "linkedin-easyapply"
    base, n = slug, 2
    while os.path.exists(os.path.join(ROOT, "applications", slug)):
        slug = f"{base}-{n}"
        n += 1
    appdir = os.path.join(ROOT, "applications", slug)
    os.makedirs(appdir, exist_ok=True)

    # Always write a text proof from the real confirmation evidence — this alone
    # satisfies the Applied proof-gate even if the screenshot endpoint flakes.
    txt = os.path.join(appdir, "confirmation.txt")
    with open(txt, "w", encoding="utf-8") as f:
        f.write(f"LinkedIn Easy Apply confirmation for {company} — {role}\n{url}\n\n"
                f"submit stdout: {submit_out}\n"
                f"post-submit state: {json.dumps(post)}\n")
    # Best-effort screenshot (preferred visual proof).
    png = os.path.join(appdir, "confirmation.png")
    try:
        subprocess.run(["bash", CFXSH, "shot", png], capture_output=True, text=True, cwd=ROOT)
    except Exception:
        pass
    proof = png if (os.path.isfile(png) and os.path.getsize(png) > 0) else txt

    log = subprocess.run(
        [sys.executable, LOGAPP, company, role, source, url, "Applied",
         "--proof", proof, "--notes", notes],
        capture_output=True, text=True, cwd=ROOT)
    print("LOG:", (log.stdout or log.stderr).strip())
    return slug, log.returncode


def run(job, company, role, resume, source, notes, max_attempts, dry_run):
    jid = job.rstrip("/").split("/")[-1] if "/" in job else job
    url = f"https://www.linkedin.com/jobs/view/{jid}/"

    for attempt in range(1, max_attempts + 1):
        print(f"=== attempt {attempt}/{max_attempts}: {company} — {role} ({jid}) ===")
        if not heal_tab():
            print("NO_TAB_AVAILABLE")
            return 9
        # Navigate with retry.
        for nav_try in range(4):
            try:
                cfx.navigate(url)
                break
            except Exception as e:
                print(f"  nav error (try {nav_try}): {e}")
                heal_tab()
                time.sleep(3)
        else:
            print("  NAV_FAILED after retries")
            continue
        time.sleep(11)  # let the card + Easy Apply button render
        open_res = ea("open")
        print("  open:", open_res)
        # NO_BUTTON => not a real Easy Apply posting (the queue tag was a
        # false positive, or it's "apply on company site"). Retrying 3x wastes
        # ~6 min on a dead end. Bail immediately so the driver skips to the next
        # queue row. (Bucket-A code fix: fast-fail NO_BUTTON instead of grinding.)
        if "NO_BUTTON" in str(open_res):
            print("  NO_BUTTON: not a real Easy Apply posting — skipping (rc=7)")
            return 7
        ea("dismiss-save")

        # Walk the modal steps.
        reached_review = False
        already_sent = False
        for _ in range(12):
            st = state()
            step = st.get("step", "") or st.get("header", "")
            labels = st.get("labels", [])
            low = step.lower()
            # LinkedIn sometimes auto-advances straight to "Your application was
            # sent" with no Review step. Treat that as an immediate success.
            # WORD-BOUNDARY "sent" ("application sent" / "was sent") — a bare `"sent" in low`
            # also matched "conSENT" / "preSENT" step titles, setting already_sent=True and
            # logging a FALSE "Applied" WITHOUT ever clicking Submit (false success is the
            # worst outcome here). "application submitted" kept as an explicit phrase.
            if re.search(r"\bsent\b", low) or "application submitted" in low:
                already_sent = True
                break
            if "review" in low:
                reached_review = True
                break
            if "resume" in low and resume:
                print("  upload:", ea("upload", resume))
                ea("next")
                time.sleep(2)
                continue
            if "additional" in low or any("?" in lbl for lbl in labels):
                # Answer every label we CAN (known or bank). A label we can't answer
                # yet isn't a hard stop — `next` will tell us exactly which required
                # fields are still empty (BLOCKED_UNANSWERED_REQUIRED carries the full
                # question text), and we re-answer those specifically. This survives
                # LinkedIn's inconsistent markup where some questions aren't surfaced
                # in state()'s labels list but ARE reported by the blocker.
                answer_screeners(labels)
                for attempt in range(3):
                    r = ea("next")
                    print("  next:", r[:60])
                    if "BLOCKED_UNANSWERED_REQUIRED" not in r:
                        break
                    # Parse the still-unanswered question strings from the blocker and
                    # answer each (re-matching against KNOWN + the shared bank).
                    blocked = []
                    seg = r.split("BLOCKED_UNANSWERED_REQUIRED:", 1)[-1]
                    for chunk in seg.split(" | "):
                        q = chunk.strip().strip("'\"[]")
                        if q and "?" in q:
                            blocked.append(q)
                    if not blocked:
                        break
                    answered_any = False
                    for q in blocked:
                        lowq = q.lower()
                        hit = next((k for k in KNOWN if k in lowq), None)
                        if hit:
                            val, kind = KNOWN[hit], ("radio" if hit in RADIO_KEYS
                                                   else "select" if hit in SELECT_KEYS else "text")
                            set_field(hit, val, kind)
                            answered_any = True
                        else:
                            bank = screener.lookup(q)
                            if bank:
                                set_field(bank["pattern"], bank["answer"], bank["kind"])
                                answered_any = True
                            else:
                                print("  UNKNOWN_SCREENER:", q,
                                      "\n  -> persist: python3 sites/_common/scripts/screener.py learn '<pattern>' '<answer>' <kind>")
                    if not answered_any:
                        break
                    time.sleep(1)
                if "BLOCKED_UNANSWERED_REQUIRED" in r:
                    print("NEEDS_HUMAN (unanswered required screeners remain)")
                    return 7
                time.sleep(2)
                continue
            # Plain step (contact info etc.) — advance. If a required field is
            # unanswered (e.g. an unhandled Location combobox), bail to human.
            r = ea("next")
            print(f"  step[{step}] next:", r[:40])
            if "BLOCKED_UNANSWERED_REQUIRED" in r:
                st2 = state()
                print("BLOCKED_REQUIRED:", st2.get("errors") or st2.get("labels"), "\nNEEDS_HUMAN")
                return 7
            time.sleep(2)

        if already_sent:
            # Auto-advanced to the "sent" confirmation without a Review step.
            submit_out = "SUCCESS: application sent (auto-advanced)"
            confirmed = True
            post = {}
            for _ in range(8):
                try:
                    post = state()
                except Exception:
                    heal_tab()
                    continue
                blob = (post.get("step", "") + post.get("header", "")).lower()
                if "sent" in blob:
                    break
                try:
                    applied = cfx.evaluate(
                        "(()=>[...document.querySelectorAll('button')]"
                        ".map(x=>x.innerText.trim()).filter(t=>/^applied/i.test(t)))()")
                    if applied:
                        break
                except Exception:
                    pass
            if confirmed:
                slug, rc = capture_proof_and_log(company, role, url, source, notes, submit_out, post)
                if rc == 0:
                    print("SUBMITTED_OK", slug)
                    return 0
                print("SUBMITTED but LOG FAILED (rc", rc, ") — proof/log issue, not a re-submit")
                return 0

        if not reached_review:
            print(f"  attempt {attempt}: never reached Review")
            ea("dismiss-save")
            continue

        if dry_run:
            print("DRY_RUN: reached Review, not submitting.")
            return 5

        submit_out = ea("submit")
        print("  submit:", submit_out[:80])

        # Confirm: trust submit's own SUCCESS line first, then poll.
        confirmed = "SUCCESS" in submit_out.upper() or "application sent" in submit_out.lower()
        post = {}
        for _ in range(8):
            if confirmed:
                break
            time.sleep(3)
            try:
                post = state()
            except Exception:
                heal_tab()
                continue
            blob = (post.get("step", "") + post.get("header", "")).lower()
            if "sent" in blob:
                confirmed = True
                break
            try:
                applied = cfx.evaluate(
                    "(()=>[...document.querySelectorAll('button')]"
                    ".map(x=>x.innerText.trim()).filter(t=>/^applied/i.test(t)))()")
                if applied:
                    confirmed = True
                    break
            except Exception:
                pass

        if confirmed:
            slug, rc = capture_proof_and_log(company, role, url, source, notes, submit_out, post)
            if rc == 0:
                print("SUBMITTED_OK", slug)
                return 0
            print("SUBMITTED but LOG FAILED (rc", rc, ") — proof/log issue, not a re-submit")
            return 0
        print(f"  attempt {attempt}: submit not confirmed, retrying")
        ea("dismiss-save")

    print("ALL_ATTEMPTS_FAILED")
    return 3


def main():
    a = sys.argv[1:]
    if len(a) < 3:
        print(__doc__)
        return 1
    job, company, role = a[0], a[1], a[2]
    opts = a[3:]

    def opt(flag, default=""):
        return opts[opts.index(flag) + 1] if flag in opts and opts.index(flag) + 1 < len(opts) else default

    resume = opt("--resume", "/uploads/base-resume.pdf")
    source = opt("--source", "LinkedIn Easy Apply")
    notes = opt("--notes", "Easy Apply auto-submitted via apply_ea.py; resume=" + os.path.basename(resume))
    max_attempts = int(opt("--max-attempts", "3"))
    dry_run = "--dry-run" in opts
    return run(job, company, role, resume, source, notes, max_attempts, dry_run)


if __name__ == "__main__":
    _rc = main()
    # Feed the per-ATS success stats (Tier-5): a real submit attempt that reached a
    # terminal outcome. rc 0 = submitted; 3/7 = attempted-but-not (failed/needs-human).
    # rc 5 (dry-run), 9 (no tab), 1 (usage) aren't real attempts — don't record.
    try:
        if _rc in (0, 3, 7):
            import apply_stats
            apply_stats.record("linkedin-easyapply", submitted=(_rc == 0))
    except Exception:
        pass
    sys.exit(_rc)
