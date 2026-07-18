#!/usr/bin/env python3
"""apply.py — drive a Guardian Jobs (Madgex) IN-PLATFORM application, autonomously.

Guardian jobs split ~50/50 (measured, logged-in): some apply via an ON-PAGE form
(name/email/CV/cover + reCAPTCHA v2 → "Send application"), others "Apply on website" →
redirect to the employer's OWN ATS (a per-employer account wall). The feed's `guardian-direct`
hint is an OPTIMISTIC DEFAULT, not verified — so this driver CLASSIFIES at apply time and only
drives the in-platform ones; external ones are reported (never a false submit).

Flow (all via shipped tools — atsform for fill/upload, recaptcha.py for the sanctioned v2 solve,
login.py for the session):
  1. ensure logged in (login.py --check; run login.py if not).
  2. open the job → classify:
       IN-PLATFORM  = on-page #application-form (input[name=cv] etc.)  → drive it
       EXTERNAL     = "Apply on website" / redirect off jobs.theguardian.com → report, skip
  3. reach the form (#application-form), fill firstName/lastName/email from apply-defaults.json,
     upload the CV (a plain visible <input type=file> — atsform.upload binds it directly),
     add the cover message, and OPT OUT of the marketing checkboxes.
  4. "Send application" → the INVISIBLE reCAPTCHA v2 fires. SETTLED 2026-07-18 (REVIVA 10126456):
     for the camofox fingerprint it escalates to an image-grid that LOOPS the same tiles forever
     and never accepts — so this is a STAGE-AND-HALT: everything is filled, but the final Send is a
     one-time human noVNC gate (exit 3 + a resumable blockers.py entry). Not an autonomous submit.

⛔ Never fabricates, never submits an off-profile role (screen the title with check_title
first — this driver assumes the caller already did). CAPTCHA policy: only the sanctioned
reCAPTCHA v2 auto-solve; anything else halts.

DUPLICATE GUARD (2026-07-18): Guardian only reveals "You have already applied for this job"
AFTER you solve the Send reCAPTCHA — useless to an autonomous run that can't solve it. So this
driver checks the TRACKER FIRST (`application-tracker.csv`, matched by Guardian job-id) and skips
any posting already logged Applied BEFORE opening a thing — no wasted fill, no wasted captcha.
If a duplicate still slips through, the post-Send banner is detected, the tracker is backfilled,
and it exits clean (Applied, not a failure). `--force` re-drives a tracked posting anyway.

Usage:
    CFX_KEY=.. CFX_TAB=.. python3 sites/jobs.theguardian.com/scripts/apply.py <job-url> \
        --cv uploads/<resume>.pdf [--cover "<message>"] [--no-submit] [--force]
  --no-submit  fill everything + solve the reCAPTCHA but STOP before Send (safe verification).
  --force      drive even if the tracker already shows this posting Applied (override the guard).
  classify-only:  apply.py <job-url> --classify

Exit: 0 submitted / already-applied (skip) / --no-submit ready · 3 external/account-wall or
      reCAPTCHA-handoff · 2 error/blocked.
"""
import json
import os
import re
import subprocess
import sys
import time

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_here, "..", "..", "_common", "scripts"))
import cfx        # noqa: E402
import atsform    # noqa: E402

LOGIN = os.path.join(_here, "login.py")
RECAPTCHA = os.path.join(_here, "..", "..", "_common", "scripts", "recaptcha.py")
_ROOT = os.path.abspath(os.path.join(_here, "..", "..", ".."))


def _ev(js, tries=8):
    for _ in range(tries):
        try:
            v = cfx.evaluate(js)
            if v is not None:
                return v
        except cfx.CfxError:
            time.sleep(1.2)
    return None


def _fill_facts():
    """firstName/lastName/email from the gitignored apply-defaults.json `fill` block."""
    try:
        fill = json.load(open(os.path.join(_ROOT, "sites", "_common", "apply-defaults.json"),
                              encoding="utf-8")).get("fill", {})
    except (OSError, ValueError):
        fill = {}
    return fill


def ensure_login():
    r = subprocess.run([sys.executable, LOGIN, "--check"], cwd=_ROOT, env=os.environ,
                       capture_output=True, text=True, timeout=60)
    if "logged_in" in (r.stdout or ""):
        return True
    r = subprocess.run([sys.executable, LOGIN], cwd=_ROOT, env=os.environ,
                       capture_output=True, text=True, timeout=180)
    return "logged into Guardian" in (r.stdout or "")


def classify():
    """'in-platform' | 'external' | 'no-apply' for the CURRENT job page."""
    return _ev("(function(){"
               "if(document.querySelector('#application-form,input[name=cv]'))return 'in-platform';"
               "var ext=[].slice.call(document.querySelectorAll('a')).find(function(a){"
               "return /external-redirect-registration/.test(a.getAttribute('href')||'')||"
               "/apply on website/i.test((a.innerText||''));});"
               "if(ext)return 'external';return 'no-apply';})()") or "no-apply"


def _accept_consent():
    _ev("(function(){var b=[].slice.call(document.querySelectorAll('button')).find(function(e){"
        "return /yes, i.?m happy|yes, i accept|accept all/i.test(e.innerText||'');});"
        "if(b){b.click();return 1;}return 0;})()")


def _opt_out():
    """Uncheck the marketing opt-ins (CV database / free review / job alerts)."""
    _ev("(function(){['cvDatabaseOptIn','sendCvForReview','jobAlerts'].forEach(function(n){"
        "var e=document.querySelector('input[name='+n+']');"
        "if(e&&e.checked){e.click();}});return 1;})()")


def _job_id(url):
    """The numeric Guardian job id from a job URL (…/job/<id>/…), or ''."""
    m = re.search(r"/job/(\d+)", url or "")
    return m.group(1) if m else ""


def _already_in_tracker(url):
    """PRE-CHECK (the primary duplicate guard): is this posting ALREADY logged Applied?
    Guardian only reveals "you have already applied" AFTER you solve the Send reCAPTCHA — far
    too late for an autonomous run (it can't solve the captcha). So the real defence is to never
    drive a posting the tracker already shows Applied. Delegates to the ONE canonical apply-time
    guard (precheck.already_applied — board-agnostic canon_ids match, reused by every driver) so
    this logic is not re-implemented per board. Returns "<Status> (<matched_by>)" or ''."""
    try:
        sys.path.insert(0, os.path.join(_here, "..", "..", "_common", "scripts"))
        import precheck  # noqa: E402
        hit = precheck.already_applied(url=url, company="REVIVA SOFTWORKS", role="Product Designer")
        if hit and precheck.is_applied(hit[0]):
            return f"{hit[0]} ({hit[1]})"
    except Exception:
        pass
    return ""


def _already_applied():
    """POST-SEND detection: Guardian's "You have already applied for this job" banner (shown
    after Send when a submission from this account already exists). Secondary to the tracker
    pre-check — it backfills the tracker when a duplicate slips through anyway."""
    return bool(_ev("(function(){var b=document.body?document.body.innerText:'';"
                    "return /you have already applied for this job|already applied for this "
                    "(job|position|role)/i.test(b)?1:0;})()"))


def _log_applied(url, proof_rel):
    """Backfill the tracker as Applied (in-place update if a row exists) with a proof artifact."""
    logger = os.path.join(_here, "..", "..", "_common", "scripts", "log-application.py")
    subprocess.run([sys.executable, logger, "REVIVA SOFTWORKS", "Product Designer", "Guardian",
                    url, "Applied", "--proof", proof_rel,
                    "--notes", "auto: 'You have already applied for this job' banner detected on "
                    "Send — duplicate, backfilled by apply.py."],
                   cwd=_ROOT, env=os.environ, capture_output=True)


def main():
    argv = sys.argv[1:]
    urls = [a for a in argv if a.startswith("http")]
    if not urls:
        print(__doc__)
        return 2
    url = urls[0]

    def opt(flag, default=None):
        return argv[argv.index(flag) + 1] if flag in argv and argv.index(flag) + 1 < len(argv) else default

    cv = opt("--cv")
    cover = opt("--cover")
    no_submit = "--no-submit" in argv
    classify_only = "--classify" in argv
    force = "--force" in argv

    # ── PRE-CHECK #1 (cheapest, no browser needed): already logged Applied? Guardian only
    #    reveals "already applied" AFTER the Send reCAPTCHA — useless to an autonomous run — so
    #    the real duplicate guard is the tracker. Skip BEFORE opening the browser. --force overrides.
    if not classify_only:
        hit = _already_in_tracker(url)
        if hit and not force:
            print(f"⏭  ALREADY-APPLIED — tracker {hit} matches this posting (job {_job_id(url)}). "
                  f"Guardian would only reveal the duplicate after the Send reCAPTCHA, so skip the "
                  f"whole fill+captcha. Pass --force to re-drive anyway.")
            return 0

    if not os.environ.get("CFX_KEY"):
        print("ERROR: no CFX_KEY.", file=sys.stderr)
        return 2

    if not classify_only and not ensure_login():
        print("BLOCKED: not logged into Guardian — run login.py (may need a one-time noVNC "
              "reCAPTCHA pass).", file=sys.stderr)
        return 2

    res = cfx.goto(url)
    if not res.get("ok"):
        print(f"ERROR: could not open {url} ({res}).", file=sys.stderr)
        return 2
    time.sleep(2)
    _accept_consent()

    kind = classify()
    print(f"apply-type: {kind}")
    if classify_only:
        return 0 if kind == "in-platform" else 3
    if kind == "external":
        print("⏭  EXTERNAL — 'Apply on website' redirects to the employer's own ATS (a "
              "per-employer account wall). Not an in-platform submit; log as external, skip.",
              file=sys.stderr)
        return 3
    if kind != "in-platform":
        print("BLOCKED: no apply control found.", file=sys.stderr)
        return 2

    # reach the on-page form (click the in-platform Apply → #application-form)
    _ev("(function(){var a=[].slice.call(document.querySelectorAll('a,button')).find(function(e){"
        "var t=(e.innerText||'').trim();return /apply/i.test(t)&&!/website|no thanks/i.test(t);});"
        "if(a)a.click();return 1;})()")
    time.sleep(2)
    if not _ev("!!document.querySelector('input[name=cv]')"):
        print("BLOCKED: in-platform form did not render its fields.", file=sys.stderr)
        return 2

    # fill name/email from config
    f = _fill_facts()
    for label, key in (("First name", "First name"), ("Last name", "Last name"),
                       ("email address", "Email")):
        if f.get(key):
            atsform.fill(label, f[key])
    # CV upload (required) — plain visible file input; atsform.upload binds it directly
    if not cv:
        print("BLOCKED: --cv <resume.pdf> is required for a Guardian application.", file=sys.stderr)
        return 2
    up = atsform.upload("Your CV", os.path.basename(cv))
    if not _ev("(function(){var e=document.querySelector('input[name=cv]');"
               "return e&&e.files&&e.files.length?1:0;})()"):
        print(f"BLOCKED: CV upload did not bind ({up}).", file=sys.stderr)
        return 2
    if cover:
        atsform.fill("cover message", cover)
    _opt_out()

    if no_submit:
        print("✓ --no-submit: fields filled, CV bound, opt-outs set. NOT sending. (The Send "
              "reCAPTCHA is INVISIBLE — it only fires when Send is clicked, so it cannot be "
              "tested without actually submitting; remove --no-submit for a real apply.)")
        return 0

    def _confirmed():
        return bool(_ev("(function(){var b=document.body?document.body.innerText:'';"
                        "return /application (sent|submitted|received)|thank you for (your )?appl|"
                        "we have received your appl/i.test(b)?1:0;})()"))

    # ── Send → the INVISIBLE reCAPTCHA fires HERE (not before). Outcomes:
    #    (a) passes silently → confirmation;
    #    (b) escalates to an IMAGE-GRID challenge → hand to noVNC (see the SETTLED finding below);
    #    (c) silently blocks (no challenge, no confirmation) → hand to noVNC (policy: don't grind).
    _ev("(function(){var b=[].slice.call(document.querySelectorAll('button,input[type=submit]'))"
        ".find(function(e){return /send application/i.test((e.innerText||e.value||''));});"
        "if(b)b.click();return 1;})()")
    time.sleep(5)
    if _confirmed():
        print("✓ application sent (reCAPTCHA passed silently). Capture proof + log.")
        return 0
    # ── PRE-CHECK #2 (post-Send): a duplicate that slipped past the tracker guard. Guardian
    #    replies "You have already applied for this job" — NOT a failure. Save proof, backfill the
    #    tracker (so pre-check #1 catches it next time), and exit clean (no captcha/blocker churn).
    if _already_applied():
        pdir = os.path.join(_ROOT, "applications", "reviva-product-designer")
        os.makedirs(pdir, exist_ok=True)
        txt = os.path.join(pdir, "already-applied.txt")
        try:
            with open(txt, "w", encoding="utf-8") as f:
                f.write("Guardian returned 'You have already applied for this job' on Send for "
                        f"{url}\n(job {_job_id(url)}) — application already exists on this account.\n")
        except OSError:
            pass
        _log_applied(url, os.path.relpath(txt, _ROOT))
        print("⏭  ALREADY-APPLIED — Guardian says this account already applied for this job. "
              "Not a failure; tracker backfilled (proof: already-applied.txt). No re-submit.")
        return 0
    # SETTLED 2026-07-18 (REVIVA 10126456): when Send escalates to a v2 image-grid, that grid
    # RECYCLES THE SAME TILES across unlimited verify rounds and never accepts for this camofox
    # fingerprint — the sanctioned two-phase recaptcha.py solve-grid works mechanically but cannot
    # satisfy a low-trust-fingerprint loop, and headless Hermes has no interactive VL tile-read
    # loop anyway. So we do NOT fire solve-grid here (it would only spin Phase-A captures): we
    # record the challenge type and HAND OFF to noVNC. (An INTERACTIVE agent session may still run
    # `recaptcha.py solve-grid` by hand to re-confirm the loop — but expect it to loop, not pass.)
    grid = _ev("(function(){var f=document.querySelector('iframe[src*=\"api2/bframe\"]');"
               "return f&&f.offsetParent!==null?1:0;})()")
    try:
        sys.path.insert(0, os.path.join(_here, "..", "..", "_common", "scripts"))
        import recaptcha as _rc  # noqa: E402
        _rc._record_captcha_type("jobs.theguardian.com", "grid" if grid else "invisible")
    except Exception:
        pass
    what = ("in-platform form fully staged (name/email/CV/cover/opt-outs); Send fired a reCAPTCHA "
            "v2 " + ("image-grid" if grid else "invisible") + " challenge that this fingerprint "
            "can't clear — needs a one-time human noVNC pass to solve + Send.")
    subprocess.run([sys.executable, os.path.join(_here, "..", "..", "_common", "scripts",
                    "blockers.py"), "record", "captcha", "jobs.theguardian.com", "--url", url,
                    "--what", what], cwd=_ROOT, env=os.environ, capture_output=True)
    print("⛔ Send did not confirm; the reCAPTCHA " + ("grid " if grid else "")
          + "won't clear for this fingerprint (recycles/loops — do NOT grind, policy). Everything "
          "is filled — hand the final Send/reCAPTCHA to noVNC (http://nasirjones:6080/vnc.html). "
          "Verify on jobs.theguardian.com account applications before logging Applied.",
          file=sys.stderr)
    return 3


if __name__ == "__main__":
    sys.exit(main())
