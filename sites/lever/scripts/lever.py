#!/usr/bin/env python3
"""
lever.py — apply driver for jobs.lever.co, the third guest-submittable ATS.

WHY THIS EXISTS (2026-08-15). `sites/lever/NOTES.md` has carried a correct recipe since July
("handled by the shared engine atsform.py … not independently live-tested"), and
`ats_router.py` classified Lever as *recognised ATS, no shipped driver* → routed to manual/VNC.
So every Lever posting the funnel found was unreachable to an autonomous run purely because
nobody had turned the recipe into a file. Ashby and Greenhouse each needed a driver for their
genuine quirks (Ashby's toggle pairs, Greenhouse's emailed code gate); Lever needs almost
nothing — it is standard label-associated inputs plus a file upload — so this is deliberately
THIN and delegates every widget decision to `atsform`.

⛔ NO WIDGET LOGIC LIVES HERE. Text fill, dropdowns, radios, checkboxes, upload, EEO and the
screener-bank gap-fill all come from `sites/_common/scripts/atsform.py` (AGENTS.md §6, guarded
by tests/test_core.py::TestNoDivergentFormWidgets). If a Lever widget won't bind, extend the
shared engine — never grow a copy in here.

Subcommands:
  apply <config.json> [--submit]   fill the whole form from a config, run the pre-submit
                                   check, and STOP. With --submit, submit too — but ONLY if
                                   every step passed and no required field is still empty.
  check                            enumerate answered vs empty fields + validation errors.
  submit                           the irreversible step, on demand.

Config (all sections optional; same shape as the Ashby/Greenhouse configs):
  {"cv": "base-resume.pdf", "company": "Acme", "role": "…", "url": "…",
   "defaults": true, "fill": {...}, "select": {...}, "radios": {...}, "checkboxes": {...}}

Exit: 0 applied/filled cleanly · 1 needs a human (required field unanswerable, attestation,
CAPTCHA) · 2 config/nav error.
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
import atsform  # noqa: E402
import cfx  # noqa: E402
import precheck  # noqa: E402

# Lever serves the posting at /<company>/<uuid> and the FORM at /<company>/<uuid>/apply.
# Navigating straight to /apply skips the intermediate "Apply for this job" click entirely
# (NOTES.md), which is one less render to race.
_APPLY_SUFFIX = "/apply"


def form_url(url):
    u = (url or "").split("?")[0].rstrip("/")
    return u if u.endswith(_APPLY_SUFFIX) else u + _APPLY_SUFFIX


_CHECK_JS = r"""
(() => {
  const clean = s => (s||'').replace(/\s+/g,' ').trim();
  const out = {empty: [], answered: [], errors: []};
  // Climb PAST the control's own text. A radio's nearest labelled ancestor is its own
  // option ("Yes"), so the old walk reported every unanswered required group as
  // `*choice: Yes` — unreadable, and it hid that these were US work-authorisation questions
  // on US postings (which must be SKIPPED, not answered). Keep going until an ancestor says
  // something the option itself doesn't.
  const lab = e => {
    const own = clean((e.closest('label') || e).innerText || e.value || '');
    let t = clean(e.labels && e.labels[0] ? e.labels[0].innerText : '');
    if (t && t !== own) return t.slice(0, 90);
    let b = e;
    for (let k=0;k<7&&b;k++){
      b = b.parentElement; if (!b) continue;
      const x = clean(b.innerText);
      if (!x || x.length > 250) continue;
      if (own && (x === own || x.replace(own,'').trim().length < 3)) continue;
      return x.slice(0, 90);
    }
    return (t || e.name || e.id || '?').slice(0, 90);
  };
  for (const e of document.querySelectorAll('input,textarea,select')) {
    const ty = (e.type||'').toLowerCase();
    if (['hidden','submit','button','reset','image'].includes(ty)) continue;
    if (ty === 'radio' || ty === 'checkbox') continue;          // counted per-group below
    const req = e.required || /\*/.test(lab(e));
    const filled = ty === 'file' ? !!(e.files && e.files[0]) : !!clean(e.value);
    (filled ? out.answered : out.empty).push((req?'*':'') + ty + ': ' + lab(e));
  }
  // ⛔ A CHOICE GROUP CAN BE REQUIRED TOO (2026-08-15). This used to report every radio/
  // checkbox group WITHOUT the '*' marker, so `apply` never counted an unanswered required
  // group as blocking. Palantir's form has a REQUIRED languages checkbox group and a REQUIRED
  // "AI notetaker" consent radio; with both unticked the form looked complete, and the submit
  // click was a silent no-op — no confirmation, no error, nothing to diagnose. Lever marks
  // `required` on the inputs themselves, so read it there and prefix '*' like any other field.
  const groups = {};
  for (const r of document.querySelectorAll('input[type=radio],input[type=checkbox]'))
    (groups[r.name] ||= []).push(r);
  for (const rs of Object.values(groups)) {
    const on = rs.some(r => r.checked);
    const req = rs.some(r => r.required);
    (on ? out.answered : out.empty).push((req && !on ? '*' : '') + 'choice: ' + lab(rs[0]));
  }
  for (const e of document.querySelectorAll('[class*=error],[role=alert],[aria-invalid=true]')) {
    const t = clean(e.innerText); if (t) out.errors.push(t.slice(0, 90));
  }
  out.errors = [...new Set(out.errors)];
  return JSON.stringify(out);
})()
"""


def set_location(city="London"):
    """Bind Lever's geo autocomplete — the ONE field on a Lever form that needs more than a
    value set, and the only reason a fully-filled Lever application bounces.

    ⛔ IT LISTENS ON `keydown`, NOT `input` (verified live 2026-08-15 by reading Lever's own
    https://jobs.lever.co/js/retrieveLocations.js: `$('input.location-input').on('keydown', …)`
    → debouncedGetLocationResultsByInput). So the usual React native-setter + `input` event
    NEVER fires the search: the dropdown renders "No location found. Try entering a different
    location", nothing is picked, and the server rejects the submit with
    "Please select a location from the dropdown menu and try again." That looks exactly like
    the structural async-location wall seen on Ashby — it isn't one; it's an event-name
    mismatch. REAL per-character keystrokes populate the list every time.

    Picking an option fills the hidden `selectedLocation` with Lever's own structured payload
    ({"name": …, "id": …}), which is what the server actually validates. Prefers a UK match so
    "London" can't silently resolve to London, Ontario or London, Ohio — both of which Lever
    offers first-class. Returns 0 on a structured pick."""
    marked = "NO_OPTIONS"
    # Two rounds: keystrokes only land in a field the browser considers focused, and a JS
    # .focus() alone is not always enough after the résumé re-render. Round 2 uses a TRUSTED
    # click to focus, and a shorter query (a longer prefix over-filters some geo lists).
    for attempt, query in enumerate((str(city)[:24], str(city)[:4]), start=1):
        try:
            ready = cfx.evaluate("""(function(){var i=document.getElementById('location-input');
              if(!i) return 'NO_INPUT'; i.scrollIntoView({block:'center'});
              i.setAttribute('data-lever-locin','1'); i.focus();
              var s=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
              s.call(i,''); i.dispatchEvent(new Event('input',{bubbles:true})); return 'ready';})()""")
        except cfx.CfxError as e:
            print(f"FAIL location: {e}")
            return 1
        if ready == "NO_INPUT":
            return 1
        if attempt == 2:
            try:
                cfx.click_selector('[data-lever-locin="1"]', timeout=6)
            except cfx.CfxError:
                pass
        for ch in query:
            try:
                cfx.press(ch)
            except cfx.CfxError:
                pass
            time.sleep(0.08)
        time.sleep(2.5)
        try:
            marked = cfx.evaluate("""(function(){
              var els=[].slice.call(document.querySelectorAll('.dropdown-location'));
              if(!els.length) return 'NO_OPTIONS';
              var t=els.filter(function(e){return /GBR|United Kingdom|England|Scotland|Wales/i
                     .test(e.innerText||'');})[0] || els[0];
              t.setAttribute('data-lever-loc','1'); return t.innerText.trim();})()""")
        except cfx.CfxError as e:
            print(f"FAIL location list: {e}")
            return 1
        if marked not in ("NO_INPUT", "NO_OPTIONS"):
            break
    if marked in ("NO_INPUT", "NO_OPTIONS"):
        print(f"FAIL location: {marked} (geo list empty after 2 keystroke rounds)")
        return 1
    try:
        cfx.click_selector('[data-lever-loc="1"]', timeout=8)
    except cfx.CfxError:
        cfx.evaluate("(()=>{const e=document.querySelector('[data-lever-loc]');if(e)e.click();})()")
    time.sleep(1.0)
    sel = cfx.evaluate("(()=>((document.getElementById('selected-location')||{}).value||''))()")
    if sel:
        print(f"OK location -> {marked}")
        return 0
    print(f"FAIL location: clicked {marked!r} but selectedLocation stayed empty")
    return 1


def check(quiet=False):
    """Answered vs empty + any validation errors. Required fields are prefixed '*'."""
    try:
        data = json.loads(cfx.evaluate(_CHECK_JS))
    except (ValueError, TypeError, cfx.CfxError) as e:
        print(f"FAIL check: {e}")
        return {"empty": [], "answered": [], "errors": [f"check failed: {e}"]}
    if not quiet:
        print(json.dumps(data, indent=1))
    return data


def submit():
    """The point of no return. Lever's button reads 'Submit application'."""
    return atsform.submit(
        "Submit application",
        r"thank you|application (received|submitted)|we.{0,3}(ve|have) received")


def apply(config_path, do_submit=False):
    try:
        with open(config_path, encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError) as e:
        print(f"FAIL: cannot read config {config_path!r}: {e}")
        return 2

    company, role = cfg.get("company") or "Unknown", cfg.get("role") or ""
    url = cfg.get("url") or ""

    # Apply-time dedup guard, same contract as ashby.apply: this runs on a page reached
    # outside the sourcing precheck, so re-check the live tracker before spending a submit.
    if not cfg.get("force"):
        try:
            if precheck.already_applied(url, company, role):
                print(f"SKIP already applied: {company} | {role}")
                # rc=6, not 0 — see the note in gh_apply: rc=0 made apply_queue
                # count a SKIPPED duplicate as an application.
                return 10
        except Exception:  # noqa: BLE001 — a dedup probe must never block a real application
            pass

    if url:
        nav = cfx.goto(form_url(url))
        if not nav.get("ok"):
            print(f"FAIL nav: blank render after {nav.get('attempts')} attempts")
            return 2

    failures = []
    if cfg.get("cv"):
        # Lever's file input is labelled Resume/CV; target by label via the shared uploader.
        for target in ("Resume", "resume", "CV"):
            try:
                if atsform.upload(target, cfg["cv"]) == 0:
                    break
            except Exception:  # noqa: BLE001
                continue
        else:
            failures.append("cv upload")
        # ⛔ WAIT OUT THE RÉSUMÉ PARSE (2026-08-15). Lever shows "Analyzing resume…" and then
        # RE-RENDERS the form when parsing finishes — the same autofill hazard Ashby documents.
        # Filling during that window looks like it worked (every setter returns OK) and then
        # the re-render wipes the custom `cards[…]` answers, so the pre-submit check reports
        # them empty and the submit aborts with no visible cause. Poll until the parse settles.
        for _ in range(20):
            try:
                state = cfx.evaluate(
                    "(()=>{const t=document.body.innerText||'';"
                    "return /analyz|analys/i.test(t) ? 'BUSY' : 'READY';})()")
            except cfx.CfxError:
                break
            if state == "READY":
                break
            time.sleep(1.0)
        time.sleep(1.0)

    defaults = atsform._load_defaults(cfg.get("defaults", True)) if cfg.get("defaults", True) else {}

    def _run_defaults(section, kind, fn):
        for label, value in atsform._default_entries(defaults, section, cfg.get(section)):
            try:
                rc = fn(label, value, quiet_notfound=True)
            except cfx.CfxError as e:
                print(f"FAIL {kind} {label!r} (default): {e}")
                rc = 1
            if rc not in (0, atsform.NOTFOUND):
                failures.append(f"{kind}:{label} (default)")

    _run_defaults("fill", "fill", atsform._fill_with_aliases)
    for label, val in (cfg.get("fill") or {}).items():
        if atsform.fill(label, val) != 0:
            failures.append(f"fill:{label}")
    for label, val in (cfg.get("select") or {}).items():
        if atsform.combobox_pick(label, val) != 0:
            failures.append(f"select:{label}")
    for q, opt in (cfg.get("radios") or {}).items():
        if atsform.set_radio(q, opt) != 0:
            failures.append(f"radio:{q}")
    for label, state in (cfg.get("checkboxes") or {}).items():
        if atsform.set_checkbox(label, state) != 0:
            failures.append(f"checkbox:{label}")

    # Lever's geo autocomplete needs real keystrokes + a structured pick — see set_location.
    if cfx.evaluate("!!document.getElementById('location-input')"):
        if set_location((cfg.get("location") or "London")) != 0:
            failures.append("location (structured pick)")

    try:
        atsform.fill_eeo()
    except Exception as e:  # noqa: BLE001 — EEO is optional and must never block a submit
        print(f"  eeo note: {str(e)[:80]}")
    try:
        atsform.checkboxes_from_profile()
    except Exception as e:  # noqa: BLE001
        print(f"  checkbox note: {str(e)[:80]}")
    try:
        atsform.fill_gaps_from_bank()
    except Exception as e:  # noqa: BLE001
        print(f"  screener-bank note: {str(e)[:80]}")

    # REQUIRED CHOICE GROUPS that are truthful and generic (2026-08-15). Two classes appear on
    # Lever forms and both silently no-op the submit when unanswered — no confirmation, no
    # error (Palantir Product Designer):
    #   * a required LANGUAGES checkbox list — English is true for this applicant;
    #   * a required AI-notetaker / recording consent radio — a preference, not a fact, and
    #     consenting is the non-obstructive answer (same call already made on Accurx's Gemini
    #     question). Anything that is NOT one of these stays untouched for the human.
    # JS .click() on the LABEL, because Lever's radios sit under a label wrapper and a trusted
    # click on the input itself times out.
    try:
        rep = cfx.evaluate(r"""(function(){
          var done=[];
          function pick(pred){
            var r=[].slice.call(document.querySelectorAll('input[type=radio],input[type=checkbox]'))
              .filter(function(x){return x.required && !x.checked && pred(x);})[0];
            if(!r) return null;
            var grp=[].slice.call(document.querySelectorAll('[name="'+(r.name||'').replace(/"/g,'\\"')+'"]'));
            if(grp.some(function(g){return g.checked;})) return null;
            var lab=r.closest('label')||document.querySelector('label[for="'+r.id+'"]');
            (lab||r).click();
            return r.value||r.id;
          }
          var langs=pick(function(x){return /^english\b/i.test((x.value||'')) ||
                                            /^english\b/i.test((x.closest('label')||{}).innerText||'');});
          if(langs) done.push('language:'+langs);
          var ai=pick(function(x){
            var t=((x.closest('label')||{}).innerText||'')+' '+(x.value||'');
            if(!/consent|agree/i.test(t)) return false;
            if(/do not consent|don.t consent|decline/i.test(t)) return false;
            var card=x.closest('div');
            for(var k=0;k<5&&card;k++,card=card.parentElement){
              if(/notetaker|transcri|record|privacy|contact me/i.test(card.innerText||'')) return true;
            }
            return false;});
          if(ai) done.push('consent:'+ai);
          return JSON.stringify(done);})()""")
        if rep and rep != "[]":
            print(f"  truthful required choices ticked: {rep}")
    except Exception as e:  # noqa: BLE001
        print(f"  choice-group note: {str(e)[:80]}")

    print("\n===== pre-submit check =====")
    chk = check()
    missing = [f for f in chk["empty"] if f.startswith("*")]

    print("\n===== summary =====")
    if failures:
        print(f"STEP FAILURES: {', '.join(failures)}")
    if missing:
        print(f"REQUIRED STILL EMPTY: {missing}")
    if chk["errors"]:
        print(f"VALIDATION: {chk['errors']}")
    if not do_submit:
        print("filled; not submitting (pass --submit).")
        return 1 if (failures or missing) else 0
    if failures or missing:
        print("ABORT --submit: unresolved required fields — nothing submitted.")
        return 1

    rc = submit()
    if rc != 0:
        print("submit did not confirm — NOT logging Applied.")
        return 1

    appdir = os.path.join(_ROOT, "applications",
                          re.sub(r"[^a-z0-9]+", "-", f"{company} {role}".lower()).strip("-")[:70])
    os.makedirs(appdir, exist_ok=True)
    proof = os.path.join(appdir, "confirmation.png")
    try:
        cfx.shot(proof, full_page=True)
    except Exception:  # noqa: BLE001
        proof = None
    _log(company, role, "Lever", url, "Applied", proof=proof)
    return 0


def _log(company, role, source, url, status, note=None, proof=None):
    """Same contract as gh_apply._log — CHECK the return code. A swallowed logging failure
    means an application that was really submitted is invisible to the tracker, so the next
    drain re-applies to it (that cost a real duplicate on Greenhouse, 2026-08-15)."""
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
    print(f"⛔ LOG_FAILED {company} | {role} | {status} — tracker NOT updated.", file=sys.stderr)
    return False


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__.strip().splitlines()[1])
        print("Usage: lever.py <apply <config.json> [--submit] | check | submit>")
        return 2
    cmd = args[0]
    if cmd == "apply":
        if len(args) < 2:
            print("apply needs a config path")
            return 2
        return apply(args[1], do_submit="--submit" in args[2:])
    if cmd == "check":
        check()
        return 0
    if cmd == "submit":
        return submit()
    print(f"Unknown command: {cmd}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
