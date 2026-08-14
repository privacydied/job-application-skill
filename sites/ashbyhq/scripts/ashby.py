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
import re
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "_common", "scripts"))
import cfx  # noqa: E402
import atsform  # noqa: E402  (shared ATS form engine)
import precheck  # noqa: E402  — already_applied() apply-time dedup guard

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
    # Match the apply CTA robustly: Ashby postings vary the label ("Apply for this Job/Role/
    # Position", "Apply Now", bare "Apply") and some render it as an <a>/[role=button], not a
    # <button> — the old exact "apply for this job" <button>-only match missed those (e.g. Primer).
    # Exclude external "Apply on website/company site" links (those leave Ashby). Prefer the most
    # specific "apply for this …" phrasing, else the first bare apply CTA.
    marked = json.loads(cfx.evaluate(
        "(()=>{const els=[...document.querySelectorAll('button,a,[role=button]')].filter(x=>{"
        "const t=(x.innerText||x.textContent||'').trim();"
        "return /^apply(\\s+(for\\s+this\\s+(job|role|position)|now|to\\s+this))?\\s*$/i.test(t)"
        "&&!/website|company\\s*site|external/i.test(t);});"
        "if(!els.length)return JSON.stringify({ok:false});"
        "const b=els.find(x=>/for\\s+this/i.test(x.innerText||x.textContent||''))||els[0];"
        "b.setAttribute('data-ashby-target','1');return JSON.stringify({ok:true,label:(b.innerText||'').trim()});})()"
    ))
    if not marked.get("ok"):
        print("FAIL: no Apply CTA found (already on the form? external 'Apply on website'? wrong page?)")
        return 1
    if marked.get("label"):
        print(f"reveal: clicking Apply CTA '{marked['label']}'")
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
# upload_cv, submit, apply, check, set_radio) stay in this file.
#
# ⛔ DO NOT re-roll react-select / dropdown BINDING here. If an Ashby combobox won't bind,
# EXTEND atsform.combobox_pick (it already names Ashby + has the free-text fallback) and
# DELEGATE from this file — as combobox_commit() below does. A board-local combobox engine
# (find combobox input + iterate the option menu) is the duplicate-infra drift that cost a
# re-solve on 2026-07-24; the guard test tests/test_core.py::TestNoDivergentFormWidgets now
# fails the build if it reappears outside atsform.py.
upload = atsform.upload
set_checkbox = atsform.set_checkbox
fill = atsform.fill
review = atsform.review


# Ashby's labelled multi-option radios are custom React widgets: atsform.set_radio's bare
# r.click() flips the native <input>.checked but does NOT commit React state, so submit bounces
# "Missing entry for required field: <question>" even though the driver printed OK. (set_toggle
# handles the Yes/No BUTTON toggles; this handles the <input type=radio> groups — right-to-work
# status, EEO, etc.) Fix — folded here from the former apply_specs/drive_ashby.py set_radio_native,
# verified to clear the validator (references/ashby-radio-label-click-fix.md): find the option
# <label> by text within the question block, set the bound input's `checked` via the prototype
# setter so React's onChange fires, then dispatch click/input/change. ALL radios on an Ashby form
# share ONE `name`, so match by exact option-label text (fall back to a >=3-char substring), never
# a bare "Yes"/"No" that would grab the wrong group. Defers to the shared atsform.set_radio for
# standard HTML / Workday radio groups this label path can't resolve.
_ASHBY_RADIO_JS = r"""(function(q, o){
  q=q.toLowerCase(); o=o.toLowerCase();
  function setNativeChecked(el){
    var d=Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el),'checked');
    if(d&&d.set){ d.set.call(el,true); } else { el.checked=true; }
  }
  // Pass 1: labelled <label> options (standard Ashby radio widgets)
  var labels=[].slice.call(document.querySelectorAll('label'));
  for(var i=0;i<labels.length;i++){
    if(!(labels[i].innerText||'').toLowerCase().includes(q)) continue;
    for(var j=i;j<Math.min(labels.length,i+14);j++){
      var ol=labels[j], t=(ol.innerText||'').trim().toLowerCase();
      if(!t) continue;
      if(t===o || (o.length>2 && t.includes(o))){
        var r=document.getElementById(ol.getAttribute('for'))||ol.querySelector('input[type=radio]');
        if(!r) return 'NO_INPUT';
        setNativeChecked(r);
        r.dispatchEvent(new MouseEvent('click',{bubbles:true}));
        r.dispatchEvent(new Event('input',{bubbles:true}));
        r.dispatchEvent(new Event('change',{bubbles:true}));
        return r.checked ? ('OK:'+ol.innerText.trim().slice(0,40)) : 'CLICK_FAILED';
      }
    }
  }
  // Pass 2 (2026-07-24): fieldset-anchored radios whose options are NOT wrapped in
  // <label> (e.g. right-to-work status) — the option TEXT lives in a sibling span while
  // the bare <input type=radio> sits beside it with empty label text. Match the <fieldset>
  // by question text, then find the text-bearing element containing the option and use its
  // NEAREST preceding/ancestor <input type=radio> as the control to commit.
  var fsets=[].slice.call(document.querySelectorAll('fieldset'));
  for(var f=0;f<fsets.length;f++){
    if(!(fsets[f].innerText||'').toLowerCase().includes(q)) continue;
    var all=fsets[f].querySelectorAll('*');
    for(var k=0;k<all.length;k++){
      var ot=(all[k].innerText||'').trim().toLowerCase();
      if(!ot) continue;
      if(ot===o || (o.length>2 && ot.includes(o))){
        // nearest preceding radio sibling, else a radio inside this element, else by id
        var r2=null;
        var sib=all[k].previousElementSibling;
        while(sib){ var rr=sib.querySelector&&sib.querySelector('input[type=radio]'); if(rr){r2=rr;break;} if(sib.tagName==='INPUT'&&sib.type==='radio'){r2=sib;break;} sib=sib.previousElementSibling; }
        if(!r2) r2=all[k].querySelector('input[type=radio]');
        if(!r2) r2=document.getElementById(all[k].getAttribute('for'));
        if(!r2) continue;
        setNativeChecked(r2);
        r2.dispatchEvent(new MouseEvent('click',{bubbles:true}));
        r2.dispatchEvent(new Event('input',{bubbles:true}));
        r2.dispatchEvent(new Event('change',{bubbles:true}));
        return r2.checked ? ('OK:'+ot.slice(0,40)) : 'CLICK_FAILED';
      }
    }
  }
  // Pass 3 (2026-07-24): div-anchored radios whose question + options live in a <div>
  // container (not a <fieldset>) — the common Ashby variant (right-to-work, office
  // attendance, visa sponsorship, neurodivergent). Match the nearest ancestor <div> whose
  // text contains the question, then commit the radio whose option span/text matches.
  var divs=[].slice.call(document.querySelectorAll('div'));
  for(var d3=0; d3<divs.length; d3++){
    if(!(divs[d3].innerText||'').toLowerCase().includes(q)) continue;
    var opts=divs[d3].querySelectorAll('input[type=radio]');
    for(var oi=0; oi<opts.length; oi++){
      var r3=opts[oi];
      var ot3='';
      var pl=r3.closest('label'); if(pl) ot3=pl.innerText.trim();
      if(!ot3){ var sp=r3.parentElement?r3.parentElement.innerText:''; ot3=(sp||'').trim(); }
      ot3=ot3.toLowerCase();
      if(ot3===o || (o.length>2 && ot3.includes(o))){
        setNativeChecked(r3);
        r3.dispatchEvent(new MouseEvent('click',{bubbles:true}));
        r3.dispatchEvent(new Event('input',{bubbles:true}));
        r3.dispatchEvent(new Event('change',{bubbles:true}));
        return r3.checked ? ('OK:'+ot3.slice(0,40)) : 'CLICK_FAILED';
      }
    }
  }
  return 'NO_EXACT';
})(%s, %s)"""


def set_radio(question, option, quiet_notfound=False):
    res = cfx.evaluate(_ASHBY_RADIO_JS % (_js(question), _js(option)))
    if isinstance(res, str) and res.startswith("OK"):
        print(f"OK (Ashby native-set) {question[:44]!r} <- {option!r}: {res[3:]}")
        return 0
    # Not a labelled Ashby radio group (NO_EXACT / NO_INPUT / CLICK_FAILED) — defer to the
    # shared engine (standard HTML radios + the Workday value=true/false path + quiet_notfound).
    return atsform.set_radio(question, option, quiet_notfound=quiet_notfound)


def combobox_commit(label_sub, value):
    """Commit a required Ashby react-select combobox (location / US-auth) headlessly.

    Delegates to the SHARED atsform.combobox_pick primitive (which already names Ashby
    and has the free-text fallback + real-keystroke typing + native-setter commit) — do
    NOT keep a board-local copy of this logic (see user direction 2026-07-24). The shared
    _FIND_CONTROL resolves Ashby's label-less comboboxes via a field-anchored walk.
    """
    return atsform.combobox_pick(label_sub, value)


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

    # DEDUP GUARD: apply() runs on an already-navigated page that bypassed the sourcing
    # precheck, so re-check the live tracker (current URL's canonical id, then Company+Role)
    # before filling/submitting a role already Applied — stops re-applying to already-applied
    # roles. Only "Applied" skips (Blocked/Saved stay re-drivable); "force": true re-drives.
    if not cfg.get("force"):
        try:
            cur_url = cfx.current_url()
        except Exception:  # noqa: BLE001
            cur_url = cfg.get("url", "")
        hit = precheck.already_applied(url=cur_url or cfg.get("url"),
                                       company=cfg.get("company"), role=cfg.get("role"))
        if hit and precheck.is_applied(hit[0]):
            print(f"SKIP_ALREADY_APPLIED {cfg.get('company')} | {cfg.get('role')} — "
                  f"tracker={hit[0]} (matched {hit[1]})")
            return 0

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

    # NAVIGATE FIRST (2026-08-14). Every runcfg carries a "url" and apply() used it only as a
    # dedup fallback — it never actually went there, silently assuming the caller had already
    # navigated. When the tab was elsewhere (or on about:blank after an engine restart) the
    # run died with "FAIL: no Apply CTA found (already on the form? external 'Apply on
    # website'? wrong page?)" — a misleading message that reads like a page/driver wall rather
    # than "you are not on the posting". Both agents lose time re-diagnosing this; Hermes,
    # which has no hook pre-navigating the tab, hits it on essentially every call.
    # Idempotent: skip the nav when the tab is already on the target URL, so calling reveal/
    # fill/apply repeatedly on a part-filled form never reloads and discards the entries.
    target = cfg.get("url")
    if target:
        try:
            here = cfx.current_url()
        except Exception:  # noqa: BLE001
            here = ""
        if target.split("#")[0].rstrip("/") != (here or "").split("#")[0].rstrip("/"):
            print(f"nav -> {target}")
            try:
                cfx.navigate(target)
            except Exception as e:  # noqa: BLE001
                print(f"FAIL: could not navigate to {target}: {e}")
                return 2

    if reveal() != 0:
        print("ABORT: form did not reveal.")
        return 2

    # DEFAULTS (2026-07-24) — the standing applicant facts (contact fields, right-to-work, …)
    # from sites/_common/apply-defaults.json, same mechanism atsform.apply() uses. Delegated to
    # the shared helpers, never re-implemented. This gap is WHY a bespoke board script existed:
    # without defaults, every Ashby run had to restate name/email/phone/RTW in its config (or
    # hardcode them), so an ad-hoc driver grew to do it. `"defaults": false` opts out; an
    # explicit config key always wins (overlapping defaults are suppressed by _default_entries).
    defaults = atsform._load_defaults(cfg.get("defaults", True)) if cfg.get("defaults", True) else {}
    n_default_skips = 0

    def _run_defaults(section, kind, fn, coerce=lambda v: (v,)):
        nonlocal n_default_skips
        for label, value in atsform._default_entries(defaults, section, cfg.get(section)):
            try:
                rc = fn(label, *coerce(value), quiet_notfound=True)
            except cfx.CfxError as e:
                print(f"FAIL {kind} {label!r} (default): {e}")
                rc = 1
            if rc == atsform.NOTFOUND:
                n_default_skips += 1      # not on THIS form — expected, not an error
            elif rc != 0:
                failures.append(f"{kind}:{label} (default)")

    if cfg.get("cv"):
        if upload_cv(cfg["cv"]) != 0:
            failures.append("cv upload")
    for target, fn in (cfg.get("files") or {}).items():
        if upload(target, fn) != 0:
            failures.append(f"file:{target}")
    _run_defaults("fill", "fill", fill)
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
    _run_defaults("radios", "radio", set_radio)
    for q, opt in (cfg.get("radios") or {}).items():
        if set_radio(q, opt) != 0:
            failures.append(f"radio:{q}")
    for lbl, st in (cfg.get("checkboxes") or {}).items():
        st = st if isinstance(st, str) else ("on" if st else "off")
        if set_checkbox(lbl, st) != 0:
            failures.append(f"checkbox:{lbl}")

    # Required react-select comboboxes (location / US work authorization), committed AFTER the
    # text/toggle fills. combobox_commit() DELEGATES to the shared atsform.combobox_pick — do NOT
    # re-fork a board-local combobox here (the 2026-07-24 fork, since removed; the shared engine's
    # _FIND_CONTROL disambiguation + free-text fallback + real-keystroke typing now bind these
    # headlessly). Truthful values only:
    #   location        -> e.g. "London, United Kingdom" (applicant is London-based)
    #   authorized_in_us -> "No" for a British citizen with no US work authorization.
    # Match on a SHORT keyword (the ancestor DOM text holds only "Location" / "authorized",
    # not the full field label), so the matcher resolves the right field.
    if cfg.get("location"):
        if combobox_commit("location", cfg["location"]) != 0:
            failures.append("combobox:location")
    if cfg.get("authorized_in_us") is not None:
        if combobox_commit("authorized", str(cfg["authorized_in_us"])) != 0:
            failures.append("combobox:us_auth")

    # EEO / diversity — the SHARED filler (atsform.fill_eeo), values from apply-defaults.json ->
    # applicant per the applicant's standing instruction (profile §Demographics, 2026-07-19:
    # DISCLOSE gender/orientation/transgender/veteran/disability; only age stays "prefer not to
    # say"). ⛔ Do NOT re-add a board-local EEO answerer: the bespoke one this replaced blanket-
    # answered "I don't wish to answer", i.e. it INVERTED the applicant's instruction. Optional
    # by nature — a field absent from this form is skipped and never blocks the submit.
    if cfg.get("eeo", True):
        try:
            for field, val, rc in atsform.fill_eeo():
                if rc == "FAIL":
                    print(f"  EEO {field!r}: FAILED to set (field present but wouldn't bind)")
        except Exception as e:  # noqa: BLE001 — EEO is optional, never blocks an application
            print(f"  EEO note: {str(e)[:90]}")

    # Truthful checkbox auto-fill — tick ONLY affirmatively-true boxes; leave marketing / anti-AI /
    # unknown / false ones unticked (and report them). Delegates to the shared engine
    # (atsform.checkboxes_from_profile), which REPLACED blanket tick-all repo-wide (commit
    # d945a9c). The old board-local code here was (a) an INTEGRITY regression — a raw "click every
    # unchecked box" that would tick anti-AI/marketing/false boxes, the exact thing that commit
    # removed — and (b) DEAD: its JS had a misplaced `return` (SyntaxError), so it silently no-op'd
    # under the CfxError catch. Do NOT reintroduce a per-board tick-all; extend the shared primitive.
    try:
        rep = atsform.checkboxes_from_profile()
        if rep.get("ticked"):
            print(f"OK  truthfully ticked {len(rep['ticked'])} checkbox(es): "
                  f"{', '.join(rep['ticked'])[:120]}")
        for cat in ("left_false", "left_unknown", "left_marketing", "left_antiai"):
            if rep.get(cat):
                print(f"  left unticked [{cat[5:]}]: {', '.join(rep[cat])[:120]}")
    except Exception as e:  # noqa: BLE001 — truthful auto-fill is best-effort, never blocks apply
        print(f"  checkbox auto-fill note: {str(e)[:80]}")

    if defaults and n_default_skips:
        print(f"defaults: {n_default_skips} entr{'y' if n_default_skips == 1 else 'ies'} "
              f"skipped (no matching field on this form) — expected, not an error")

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

    # Auto-submit when clean (user authorised auto-submit)
    if failures or chk != 0 or rev != 0:
        print("ABORT --submit: unresolved failures / validation / content-review issues — nothing submitted.")
        return 1
    print("\nAll clear → auto-submitting. (User authorised.)")
    rc = submit()
    if rc == 0:
        _capture_and_log(cfg)
    return rc


def _capture_and_log(cfg):
    """ATOMIC submit->proof->log. On a CONFIRMED submit, screenshot the confirmation into
    applications/<slug>/ and write the tracker row in THIS process.

    Why it's here (2026-07-24): ashby.apply() used to submit and stop, leaving capture+log to
    the caller — and callers forget. That is exactly how today's run produced confirmed Ashby
    submissions the close-out never counted, and it's the ORPHAN_SUCCESS class
    scripts/close_out.py now reports. A bespoke board script grew partly to add this; folding it
    in here removes that reason to fork. Needs `company` + `role` (+ `url`) in the config;
    without them it says so rather than logging a half-identified row. Best-effort — the
    submission already stands, so a logging hiccup must never raise."""
    import subprocess
    company, role = cfg.get("company"), cfg.get("role")
    url = cfg.get("url") or (cfx.current_url() or "")
    if not (company and role):
        print("  NOT LOGGED: config has no 'company'/'role' — log by hand with "
              "log-application.py (SKILL step 8), or add them to the config.")
        return
    root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                        "..", "..", ".."))
    slug = re.sub(r"[^a-z0-9]+", "-", f"{company}-{role}".lower()).strip("-")[:80]
    appdir = os.path.join(root, "applications", slug)
    os.makedirs(appdir, exist_ok=True)
    proof = os.path.join(appdir, "confirmation.png")
    try:
        cfx.shot(proof)
    except Exception as e:  # noqa: BLE001
        print(f"  proof screenshot failed ({str(e)[:60]}) — logging Applied? instead")
    ok = os.path.isfile(proof) and os.path.getsize(proof) > 0
    cmd = ["python3", os.path.join(root, "sites", "_common", "scripts", "log-application.py"),
           company, role, cfg.get("source", "Ashby"), url,
           "Applied" if ok else "Applied?"]
    if ok:
        cmd += ["--proof", proof]
    cmd += ["--notes", "auto-logged by ashby.apply on confirmed submit"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=40, cwd=root)
        out = (r.stdout or r.stderr).strip()
        print("  log:", out.splitlines()[-1][:150] if out else f"rc={r.returncode}")
    except Exception as e:  # noqa: BLE001
        print(f"  log FAILED (submission stands — log by hand): {str(e)[:90]}")


def check() -> int:
    """Comprehensive pre-submit state dump — enumerates EVERY answerable field
    (text/file/radio-group/Yes-No toggle/consent checkbox), flags what's empty or
    unanswered, and surfaces any validation alerts. This catches missing radios /
    file fields / acknowledgments BEFORE submit (a naive name/email/cv check missed
    TILT's right-to-work radio, portfolio file, and startup-acknowledgment)."""
    import json
    expr = r"""
    (() => {
""" + _TOGGLE_HELPERS + r"""
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
        // Use the SAME score-based read as the fill path (selectedOf), not the discredited
        // "first non-transparent button" heuristic — that always reported 'Yes' (first in DOM)
        // when both buttons were non-transparent, so this human-review surface showed the wrong
        // toggle value. null on ambiguity => shown as empty (review it), never a wrong guess.
        const noB = [...box.querySelectorAll('button')].find(b=>b.innerText.trim()==='No');
        const sel = selectedOf([y, noB]);
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
