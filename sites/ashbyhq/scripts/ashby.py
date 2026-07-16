#!/usr/bin/env python3
"""
ashby.py — robust form driver for jobs.ashbyhq.com (Ashby) applications.

Encapsulates the quirks discovered on the first Ashby run (see ../NOTES.md) so an
Ashby application "just works" instead of needing the manual workarounds by hand
every time. Built on ../../_common/scripts/cfx.py (so it inherits the pacing +
referer anti-detection). Requires CFX_KEY / CFX_TAB / CFX_USER, with CFX_TAB set
to the jobs.ashbyhq.com tab.

Subcommands:
  reveal                              Click "Apply for this Job" to render the form
                                      (idempotent — no-op if fields already present).
  upload-cv <filename-in-uploads>     Attach the résumé to the CV input (id
                                      `_systemfield_resume`). Verifies + warns you to set
                                      toggles/radios/checkboxes AFTER (autofill re-renders).
  upload <id-or-label> <filename>     Attach a file to any other file field (e.g. the
                                      Portfolio field): pass its input id or a substring
                                      of its label.
  set-toggle "<question substr>" <Yes|No>
                                      Set an Ashby Yes/No toggle by a substring of its
                                      QUESTION text. Idempotent (won't toggle-off an
                                      already-correct answer) and verified: JS `.click()`
                                      on the target button (trusted clicks misfire on
                                      these toggles), settle + single retry on repaint
                                      lag, confirmed via a fail-safe button-fill read.
  set-radio "<question substr>" "<option substr>"
                                      Select a radio in the matching group (e.g.
                                      right-to-work → "Full right to work"). Verified.
  set-checkbox "<label substr>" [on|off]
                                      Check/uncheck a checkbox by its label (e.g. a
                                      startup-intensity acknowledgment). Verified.
  fill "<label substr>" "<value>"     Fill a text/textarea field by a substring of its
                                      LABEL (custom-field `name`s are random uuids per
                                      posting; labels are stable). Reads stdin if value
                                      is "-". Verified against the field's value.
  check                               Comprehensive pre-submit dump: EVERY field
                                      (text/file/radio/toggle) split into answered vs
                                      empty, plus any validation alerts — so nothing
                                      required (radios, portfolio, acknowledgments) is
                                      missed before submit.
  submit                              THE POINT OF NO RETURN — only after your own review
                                      (SKILL step 6). Clicks "Submit Application", waits
                                      for the invisible reCAPTCHA + POST, and reports
                                      SUCCESS (green banner + form gone) or the exact
                                      "Missing entry" validation errors. Does NOT decide
                                      to submit for you; you call it when you're ready.
  apply <config.json> [--submit]      ORCHESTRATOR — runs the whole flow from a JSON
                                      config in the autofill-safe order (reveal → CV →
                                      files → text → toggles/radios/checkboxes → check),
                                      then STOPS for review. Without --submit it fills +
                                      checks and stops (run `submit` yourself after
                                      reviewing). With --submit it also submits, but ONLY
                                      if every step succeeded and `check` is clean. See
                                      the apply() docstring for the config schema.

`fill`/setters/`check`/`apply` (no --submit) are safe to run anytime; `submit` (and
`apply --submit`) are the only irreversible ones.
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "_common", "scripts"))
import cfx  # noqa: E402
import atsform  # noqa: E402  (shared ATS form engine)

# --- JS building blocks -----------------------------------------------------

# Shared JS helpers for robust, FAIL-SAFE toggle selected-state detection.
# Ashby renders the CHOSEN toggle button "filled" (a saturated colour, e.g. blue
# rgb(3,116,218)) and the other transparent or near-white. fillScore() scores how
# filled a button is (0 for transparent/near-white, high for a saturated colour);
# selectedOf() returns the clearly-filled one of the pair, or null when the two
# are visually indistinguishable — deliberately NOT a guess.
#
# WHY (bug confirmed live 2026-07-13): the old read used
# `backgroundColor !== 'rgba(0,0,0,0)'` then took the FIRST match, so whenever
# BOTH buttons were non-transparent it always reported "Yes" (first in the DOM),
# silently skipped the click, and left the wrong value selected on a real
# submission. It also wasn't scoped to the field's own pair, so a sibling
# question's selected button could leak into the read. This is both fixes:
# score-based fill detection (no exact-colour assumption) + strict per-field
# scoping, returning null on ambiguity so callers fail loud instead of wrong.
_TOGGLE_HELPERS = r"""
  function fillScore(b){ const c=getComputedStyle(b).backgroundColor||''; const m=c.match(/rgba?\(([^)]+)\)/); if(!m) return 0; const p=m[1].split(',').map(x=>parseFloat(x)); const r=p[0]||0,g=p[1]||0,bl=p[2]||0,a=(p.length>3)?p[3]:1; if(!a) return 0; const lum=0.299*r+0.587*g+0.114*bl; return a*(255-lum); }
  function selectedOf(pair){ const s=pair.filter(Boolean).map(b=>({t:b.innerText.trim(), s:fillScore(b)})); if(s.length<2) return null; s.sort((x,y)=>y.s-x.s); if(s[0].s-s[1].s < 25) return null; return s[0].t; }
  function toggleDist(a,b){ let up=0,x=a; while(x){ if(x.contains(b)) return up; x=x.parentElement; up++; } return 9999; }
"""

# Find the Yes/No toggle field whose question text contains `want`, mark the
# target button (data-ashby-target), and report the currently-selected answer.
# A field is "a Yes/No toggle field" = an ancestor that contains both a "Yes" and
# a "No" <button>; its question is that container's first non-button text line.
_MARK_TOGGLE = (r"""
(() => {
  const want = %s.toLowerCase();
  const answer = %s;
  document.querySelectorAll('[data-ashby-target]').forEach(e => e.removeAttribute('data-ashby-target'));
""" + _TOGGLE_HELPERS + r"""
  const yesButtons = [...document.querySelectorAll('button')].filter(b => b.innerText.trim() === 'Yes');
  for (const yes of yesButtons) {
    let box = yes;
    for (let i = 0; i < 8 && box; i++) {
      box = box.parentElement;
      if (!box) break;
      const btns = [...box.querySelectorAll('button')];
      const hasNo = btns.some(b => b.innerText.trim() === 'No');
      if (hasNo && box.innerText.toLowerCase().includes(want)) {
        // Target = the answer button of THIS field (nearest to this field's Yes),
        // not merely the first same-labelled button in the box (which could
        // belong to a sibling toggle question sharing the container).
        const answerBtns = btns.filter(b => b.innerText.trim() === answer);
        let target = null, tbest = 9999;
        for (const ab of answerBtns) { const d = toggleDist(yes, ab); if (d < tbest) { tbest = d; target = ab; } }
        if (!target) return JSON.stringify({ found: false, reason: 'no ' + answer + ' button' });
        target.setAttribute('data-ashby-target', '1');
        // The field's opposite button = the nearest button with the other label.
        const other = answer === 'Yes' ? 'No' : 'Yes';
        let opp = null, obest = 9999;
        for (const b of btns) { if (b.innerText.trim() === other) { const d = toggleDist(target, b); if (d < obest) { obest = d; opp = b; } } }
        return JSON.stringify({ found: true, selected: opp ? selectedOf([target, opp]) : null });
      }
    }
  }
  return JSON.stringify({ found: false, reason: 'question not found' });
})()
""").strip()

# Read which button (Yes/No) is currently selected for the marked field. Scoped
# strictly to the target's own pair (target + the NEAREST opposite-label button),
# so a sibling toggle can't pollute the read. Returns 'Yes'/'No', or 'NONE' when
# the pair is visually indistinguishable (fail safe).
_READ_SELECTED = (r"""
(() => {
  const t = document.querySelector('[data-ashby-target]');
  if (!t) return 'NO_TARGET';
""" + _TOGGLE_HELPERS + r"""
  const mine = t.innerText.trim();
  const other = mine === 'Yes' ? 'No' : 'Yes';
  const cands = [...document.querySelectorAll('button')].filter(b => b.innerText.trim() === other);
  let opp = null, best = 9999;
  for (const c of cands) { const d = toggleDist(t, c); if (d < best) { best = d; opp = c; } }
  if (!opp) return 'NONE';
  return selectedOf([t, opp]) || 'NONE';
})()
""").strip()

_JS_CLICK_TARGET = r"""
(() => { const t = document.querySelector('[data-ashby-target]'); if (!t) return 'NO_TARGET'; t.click(); return 'clicked'; })()
""".strip()

_UNMARK = "document.querySelectorAll('[data-ashby-target]').forEach(e => e.removeAttribute('data-ashby-target'));"


def _js(s):
    import json
    return json.dumps(s)


def set_toggle(question: str, answer: str) -> int:
    if answer not in ("Yes", "No"):
        print(f"answer must be Yes or No, got {answer!r}")
        return 2
    import json
    state = json.loads(cfx.evaluate(_MARK_TOGGLE % (_js(question), _js(answer))))
    if not state.get("found"):
        print(f"FAIL: {state.get('reason', 'not found')} for question ~{question!r}")
        return 1
    if state.get("selected") == answer:
        cfx.evaluate(_UNMARK)
        print(f"OK (already {answer}): {question[:50]!r}")
        return 0

    # JS `.click()` on the marked target ONLY — no trusted camofox click. A
    # trusted click does NOT reliably register on these toggles and, worse, a
    # misfiring one can land on the ADJACENT button and toggle the WRONG way
    # (NOTES.md; confirmed live 2026-07-13 — the old trusted-click-then-JS-click
    # path double-toggled and left the wrong value selected). Click once, settle
    # long enough for the repaint, then verify.
    cfx.evaluate(_JS_CLICK_TARGET)
    time.sleep(1.2)
    sel = cfx.evaluate(_READ_SELECTED)

    # Retry the JS click ONCE, but ONLY on a DEFINITE opposite reading — the read
    # positively shows the other answer, so the first click missed or lagged the
    # repaint. NEVER retry on an ambiguous 'NONE': a toggle-click on an
    # already-selected target would flip it back OFF, so ambiguity fails loud at
    # the final check below instead of risking a double-toggle.
    if sel != answer and sel in ("Yes", "No"):
        cfx.evaluate(_JS_CLICK_TARGET)
        time.sleep(1.0)
        sel = cfx.evaluate(_READ_SELECTED)

    cfx.evaluate(_UNMARK)
    if sel == answer:
        print(f"OK -> {answer}: {question[:50]!r}")
        return 0
    print(f"FAIL: wanted {answer}, field shows {sel!r}: {question[:50]!r}")
    return 1


def reveal() -> int:
    has_fields = cfx.evaluate("!!document.querySelector('input[name=_systemfield_name]')")
    if has_fields:
        print("OK: form already revealed")
        return 0
    import json
    marked = json.loads(cfx.evaluate(
        "(()=>{const b=[...document.querySelectorAll('button')].find(x=>/apply for this job/i.test(x.innerText));"
        "if(!b)return JSON.stringify({ok:false});b.setAttribute('data-ashby-target','1');return JSON.stringify({ok:true});})()"
    ))
    if not marked.get("ok"):
        print("FAIL: no 'Apply for this Job' button found (already on the form? or wrong page)")
        return 1
    # JS click directly: a camofox trusted click on this button HANGS (~30s) because
    # its post-click ref-rebuild stalls on the form re-render this click triggers.
    # The button is a plain <button>, so a JS click renders the form without that
    # stall (same class of fix as the Yes/No toggles).
    cfx.evaluate(_JS_CLICK_TARGET)
    cfx.evaluate(_UNMARK)
    ok = cfx.poll("!!document.querySelector('input[name=_systemfield_name]')", predicate=bool, timeout=6.0)
    print("OK: form revealed" if ok else "FAIL: form did not render after click")
    return 0 if ok else 1


def _upload_to(selector: str, filename: str, label: str) -> int:
    try:
        cfx.post(f"/tabs/{cfx._tab()}/upload",
                 {"userId": cfx._uid(), "selector": selector, "path": filename})
    except cfx.CfxError as e:
        print(f"FAIL upload ({label}): {e}")
        return 1
    time.sleep(1.5)
    got = cfx.evaluate(f"(()=>{{const f=document.querySelector({_js(selector)});return f&&f.files[0]?f.files[0].name:'NONE';}})()")
    # f.files[0].name is only the BASENAME; `filename` may be a full path, so compare
    # basenames — `got.endswith(full_path)` would spuriously FAIL a good upload (same
    # fix as atsform.upload).
    want = os.path.basename(filename)
    if isinstance(got, str) and (got == want or got.endswith(want)):
        print(f"OK: {label} attached ({got}).")
        return 0
    print(f"FAIL: {label} not attached (input shows {got!r})")
    return 1


def upload_cv(filename: str) -> int:
    # The CV input's stable id is `_systemfield_resume` — target it directly. (The
    # old accept-based selector `:not([accept*=image])` grabbed the WRONG input on
    # forms where several file inputs are all documents-only, e.g. TILT's, leaving
    # the required résumé empty. Bug fixed 2026-07-12.)
    rc = _upload_to("input[id=_systemfield_resume]", filename, "CV")
    if rc == 0:
        # Wait out the "Autofill from resume" re-render before the caller sets
        # toggles/radios (they'd otherwise be reset). Poll until the form is
        # present and settled rather than a blind sleep.
        cfx.poll("!!document.querySelector('input[name=_systemfield_name]')", predicate=bool, timeout=5.0)
        time.sleep(1.0)
        print("NOTE: Ashby autofills + re-renders after the résumé upload — set "
              "toggles/radios/checkboxes AFTER this and re-verify before submit.")
    return rc


# Generic form primitives live in the shared engine (atsform.py) — single source of
# truth reused by every ATS adapter. Ashby-specific bits (reveal, set_toggle,
# upload_cv, submit, apply, check) stay in this file.
upload = atsform.upload
set_radio = atsform.set_radio
set_checkbox = atsform.set_checkbox
fill = atsform.fill
review = atsform.review


def submit() -> int:
    """Click Submit Application, wait for the invisible reCAPTCHA + POST, and verify
    the outcome. Point of no return — caller reviews first. Returns 0 on confirmed
    success, 1 if validation errors block it (prints them), 2 if the outcome is
    unclear after the wait."""
    clicked = cfx.evaluate(
        "(()=>{const b=[...document.querySelectorAll('button')].find(x=>/submit application/i.test(x.innerText));"
        "if(!b)return 'NO_BUTTON';b.scrollIntoView({block:'center'});b.click();return 'clicked';})()"
    )
    if clicked != "clicked":
        print("FAIL: no 'Submit Application' button found")
        return 2
    import json
    deadline = time.time() + 18
    while time.time() < deadline:
        time.sleep(3)
        state = json.loads(cfx.evaluate(r"""
        (() => JSON.stringify({
          success: /successfully submitted/i.test(document.body.innerText),
          formGone: !document.querySelector('input[name=_systemfield_name]'),
          errors: [...new Set([...document.querySelectorAll('[role=alert]')]
            .map(e => e.innerText.replace(/\s+/g,' ').trim())
            .filter(t => /missing entry|required field/i.test(t)))],
        }))()
        """))
        if state["success"] and state["formGone"]:
            print("SUCCESS: application submitted (green banner + form gone).")
            return 0
        if state["errors"]:
            print("BLOCKED — validation errors (fix these, then submit again):")
            for e in state["errors"]:
                print("  - " + e[:200])
            return 1
    print("UNCLEAR: no success banner and no validation errors after 18s — screenshot the tab to check.")
    return 2


def apply(config_path: str, do_submit: bool = False) -> int:
    """Orchestrate a whole Ashby application from a JSON config, in the
    autofill-safe order (reveal → CV → other files → text → toggles/radios/
    checkboxes → check), then STOP for review. Only submits if --submit is passed
    AND `check` finds no validation errors (a wrong-company free-text answer is a
    semantic check only the caller can make — that's why submit stays opt-in).

    Config (all sections optional):
      {
        "cv": "resume.pdf",                      # -> #_systemfield_resume
        "files": { "Portfolio": "portfolio.pdf" },   # label-or-id -> file in uploads/
        "fill": { "Name": "Jane Doe", "why you want to join": "@why.txt" },
                                                 # label substr -> value ("@path" reads a file)
        "toggles": { "London office": "Yes" },
        "radios":  { "right to work status": "Full right to work" },
        "checkboxes": { "fully understand and accept": "on" }
      }
    """
    import json
    try:
        with open(config_path, encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError) as e:
        print(f"FAIL: cannot read config {config_path!r}: {e}")
        return 2

    cfg_dir = os.path.dirname(os.path.abspath(config_path))

    def resolve(v):
        # "@path" -> file contents (relative to the config's directory, then cwd)
        if isinstance(v, str) and v.startswith("@"):
            p = v[1:]
            for cand in (p, os.path.join(cfg_dir, p)):
                if os.path.exists(cand):
                    with open(cand, encoding="utf-8") as fh:
                        return fh.read().strip()
            raise FileNotFoundError(f"fill file not found: {p}")
        return v

    failures = []

    if reveal() != 0:
        print("ABORT: form did not reveal.")
        return 2

    if cfg.get("cv"):
        if upload_cv(cfg["cv"]) != 0:
            failures.append("cv upload")
    for target, fn in (cfg.get("files") or {}).items():
        if upload(target, fn) != 0:
            failures.append(f"file:{target}")
    for label, val in (cfg.get("fill") or {}).items():
        try:
            if fill(label, resolve(val)) != 0:
                failures.append(f"fill:{label}")
        except FileNotFoundError as e:
            print(f"FAIL fill {label!r}: {e}")
            failures.append(f"fill:{label}")
    # booleans LAST (résumé/file uploads re-render and reset them)
    for q, ans in (cfg.get("toggles") or {}).items():
        if set_toggle(q, ans) != 0:
            failures.append(f"toggle:{q}")
    for q, opt in (cfg.get("radios") or {}).items():
        if set_radio(q, opt) != 0:
            failures.append(f"radio:{q}")
    for lbl, st in (cfg.get("checkboxes") or {}).items():
        st = st if isinstance(st, str) else ("on" if st else "off")
        if set_checkbox(lbl, st) != 0:
            failures.append(f"checkbox:{lbl}")

    print("\n===== pre-submit check =====")
    chk = check()

    # Auto content-review (wrong-company / placeholders / missing keywords) if the
    # config names the company — the #1 silent failure guard.
    rev = 0
    if cfg.get("company"):
        print("\n===== content review =====")
        rev = review(cfg["company"], cfg.get("must_haves") or [])

    print("\n===== orchestrator summary =====")
    if failures:
        print("STEP FAILURES (fix these): " + ", ".join(failures))
    if chk != 0:
        print("VALIDATION: form still has errors (see above).")
    if rev != 0:
        print("CONTENT REVIEW: issues found (see above).")
    if not failures and chk == 0 and rev == 0:
        print("All steps OK, no validation or content-review issues.")

    if do_submit:
        if failures or chk != 0 or rev != 0:
            print("ABORT --submit: unresolved failures / validation / content-review issues — nothing submitted.")
            return 1
        print("\n--submit given and clean → submitting. (Caller confirmed review: right "
              "company in free-text, correct answers.)")
        return submit()
    print("\nStopped for REVIEW (no --submit). Check the values above, then run: "
          "python3 ashby.py submit")
    return 1 if (failures or chk != 0) else 0


def check() -> int:
    """Comprehensive pre-submit state dump — enumerates EVERY answerable field
    (text/file/radio-group/Yes-No toggle/consent checkbox), flags what's empty or
    unanswered, and surfaces any validation alerts. This catches missing radios /
    file fields / acknowledgments BEFORE submit (a naive name/email/cv check missed
    TILT's right-to-work radio, portfolio file, and startup-acknowledgment)."""
    import json
    expr = r"""
    (() => {
      const clean = s => (s||'').replace(/\s+/g,' ').trim();
      const out = { empty: [], answered: [], errors: [] };
      // text-like inputs
      for (const i of document.querySelectorAll('input[type=text],input[type=email],input[type=tel],input[type=number],input[type=url],textarea')) {
        if (i.name === 'g-recaptcha-response') continue;
        const lbl = clean((i.labels&&i.labels[0]?i.labels[0].innerText:'')) || i.name || i.id;
        (i.value ? out.answered : out.empty).push('text: ' + lbl.slice(0,45));
      }
      // file inputs (dedupe by id)
      const seenFile = new Set();
      for (const f of document.querySelectorAll('input[type=file]')) {
        const id = f.id || '(noid)'; if (seenFile.has(id)) continue; seenFile.add(id);
        (f.files && f.files[0] ? out.answered : out.empty).push('file: ' + id.slice(0,30) + (f.files&&f.files[0]?' ('+f.files[0].name+')':''));
      }
      // radio groups
      const groups = {};
      for (const r of document.querySelectorAll('input[type=radio]')) (groups[r.name]=groups[r.name]||[]).push(r);
      for (const name in groups) {
        const rs = groups[name]; const fs = rs[0].closest('fieldset');
        const q = clean(fs?(fs.querySelector('legend,label')||{}).innerText:name).slice(0,45);
        const sel = rs.find(r=>r.checked);
        (sel ? out.answered : out.empty).push('radio: ' + q + (sel?(' = '+clean((sel.labels&&sel.labels[0]?sel.labels[0].innerText:'')).slice(0,25)):''));
      }
      // Yes/No toggle buttons
      const yesBtns = [...document.querySelectorAll('button')].filter(b=>b.innerText.trim()==='Yes');
      for (const y of yesBtns) {
        let box=y; for(let i=0;i<8;i++){box=box.parentElement; if(box&&[...box.querySelectorAll('button')].some(b=>b.innerText.trim()==='No')&&box.innerText.length>20)break;}
        const q = clean(box.innerText.split('\n').map(s=>s.trim()).filter(Boolean)[0]).slice(0,45);
        const sel = [...box.querySelectorAll('button')].filter(b=>getComputedStyle(b).backgroundColor!=='rgba(0, 0, 0, 0)').map(b=>b.innerText.trim())[0];
        (sel ? out.answered : out.empty).push('toggle: ' + q + (sel?(' = '+sel):''));
      }
      out.errors = [...new Set([...document.querySelectorAll('[role=alert]')].map(e=>clean(e.innerText)).filter(t=>/missing|required|correction/i.test(t)))];
      return JSON.stringify(out);
    })()
    """
    r = json.loads(cfx.evaluate(expr))
    print(json.dumps(r, indent=1, ensure_ascii=False))
    if r.get("errors"):
        return 1
    # heuristic: warn if anything's empty (may include optional EEO — driver judges)
    return 0


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    cmd = args[0]
    try:
        if cmd == "reveal":
            return reveal()
        if cmd == "upload-cv" and len(args) == 2:
            return upload_cv(args[1])
        if cmd == "upload" and len(args) == 3:
            return upload(args[1], args[2])
        if cmd == "set-toggle" and len(args) == 3:
            return set_toggle(args[1], args[2])
        if cmd == "set-radio" and len(args) == 3:
            return set_radio(args[1], args[2])
        if cmd == "set-checkbox" and len(args) in (2, 3):
            return set_checkbox(args[1], args[2] if len(args) == 3 else "on")
        if cmd == "fill" and len(args) == 3:
            return fill(args[1], args[2])
        if cmd == "check":
            return check()
        if cmd == "review" and len(args) in (2, 3):
            return review(args[1], args[2].split(",") if len(args) == 3 else [])
        if cmd == "submit":
            return submit()
        if cmd == "apply" and len(args) >= 2:
            return apply(args[1], do_submit="--submit" in args[2:])
    except cfx.CfxError as e:
        print(f"ERROR: {e}")
        return 2
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
