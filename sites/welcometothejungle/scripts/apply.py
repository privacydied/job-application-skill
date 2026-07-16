#!/usr/bin/env python3
"""
apply.py — driver for WTTJ's in-platform "Apply with your profile" (apply-with-otta) flow.

**PREFER this over the external ATS whenever it's available** — it's faster (no PDF
to generate, no external ATS quirks, no reCAPTCHA): work experience / education /
snippets all auto-populate from the user's WTTJ profile, so usually only the
company-specific Application Question(s) need filling. Fall back to the external ATS
only when the job is external-ONLY (no in-platform option — see `start`). Built on
`../../_common/scripts/cfx.py`.

Two WTTJ apply-modal types (detected by `start`):
  * IN-PLATFORM — modal shows **"Apply with your profile"** → this driver handles it.
  * EXTERNAL-ONLY — modal shows only **"Apply on <Company>'s website"** + "Export
    profile PDF" (no in-platform Send) → `start` reports EXTERNAL; take the company
    site and use that ATS's recipe (Ashby/Greenhouse/Lever/…).

Usage:
    CFX_KEY=... CFX_TAB=... python3 apply.py start "<job url>"
    CFX_KEY=... CFX_TAB=... python3 apply.py answer "<question substr>" "<text|@file>"
    CFX_KEY=... CFX_TAB=... python3 apply.py status
    CFX_KEY=... CFX_TAB=... python3 apply.py send            # POINT OF NO RETURN
    CFX_KEY=... CFX_TAB=... python3 apply.py open-external    # on EXTERNAL_FALLBACK (rc 3)
    CFX_KEY=... CFX_TAB=... python3 apply.py resolve-applied <yes|no>

Commands:
  start "<url>"   navigate, click Apply, dismiss the promo modal, and detect the modal
                  type. If in-platform → click "Apply with your profile" and print the
                  section status. If external-only → print EXTERNAL:<company> and stop.
  answer "<q>" "<text>"   fill a text/url/date input OR textarea Application Question whose
                  label contains <q> (binds to the control owned by that label — never the
                  first empty field). "@path" reads text from a file. Saves the section.
  pick "<q>" "<option>"   select <option> in the react-select dropdown for question <q>
                  (Yes/No eligibility, consent, privacy). Use this for dropdowns, `answer`
                  for typed fields. (opts.py/pick.py hang on WTTJ — they call /click.)
  save            commit the current section (Save button) — a section stays incomplete
                  until Saved even when every field validates.
  status          print "All done" / "N section(s) left" and whether Send now is enabled.
  send            click "Send now" and verify. rc 0 = sent, 1 = sections incomplete,
                  2 = unclear, 3 = EXTERNAL_FALLBACK (WTTJ can't relay to the company ATS
                  — apply on the company site instead). Only after review.
  open-external   on rc 3, click "Apply on <company>'s website" — the company ATS opens in
                  a NEW tab; drive it with that ATS's recipe (Ashby/Greenhouse/Lever/…).
  resolve-applied <yes|no>   answer WTTJ's "Did you apply?" toast after an external apply.
                  UNANSWERED IT LOCKS THE FEED (can't advance to the next job). Pass `yes`
                  only if you genuinely submitted on the company site.
  dismiss-promo   force-close the sticky "write better applications" promo modal.

FLOW for an external-ATS-backed WTTJ job (e.g. Maze→Ashby): start → answer/status → send.
If send returns 3 (EXTERNAL_FALLBACK): open-external → drive the company ATS to submission
→ resolve-applied yes. That last step clears the toast that otherwise freezes the feed.
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "_common", "scripts"))
import cfx  # noqa: E402


def _js(s):
    import json
    return json.dumps(s)


# WTTJ is a React SPA with two interaction traps: (a) camofox's /click endpoint HANGS on
# WTTJ's post-click re-renders (30s timeout), and (b) a bare DOM `el.click()` does NOT fire
# React's synthetic onClick. The one reliable primitive is a full pointer+mouse event
# sequence dispatched via evaluate() — verified live to drive the promo modal's close, the
# Yes/No radios, the per-section Save, "Send now", and the "Did you apply?" toast. Route
# EVERY WTTJ click through `_react_click`; never use cfx.click_selector here.
_CLICK_SEQ = "['pointerover','pointerdown','mousedown','pointerup','mouseup','click']"


def _react_click(finder_js):
    """`finder_js` is a JS expression that evaluates to the target element (or null).
    Dispatches a real pointer/mouse click sequence on it. Returns 'clicked' or 'NF'."""
    return cfx.evaluate(f"""(()=>{{
      const el=({finder_js});
      if(!el) return 'NF';
      el.scrollIntoView({{block:'center'}});
      for(const t of {_CLICK_SEQ}){{ el.dispatchEvent(new MouseEvent(t,{{bubbles:true,cancelable:true,view:window,button:0}})); }}
      return 'clicked';
    }})()""")


def _click_text(txt, exact=False):
    match = "t===w" if exact else "t===w||t.startsWith(w)"
    finder = (f"(()=>{{const w={_js(txt)}.toLowerCase();"
              f"return [...document.querySelectorAll('button,a,[role=button]')]"
              f".find(x=>{{const t=(x.innerText||'').trim().toLowerCase();return {match};}});}})()")
    return _react_click(finder)


def dismiss_promo():
    """Dismiss the sticky "We're here to help you write better applications" promo modal.
    It re-mounts on re-render and its semi-transparent backdrop intercepts EVERY click on
    the form until closed (the real reason fills/sends appeared to "do nothing"). Clicks the
    modal's X (an svg in the card header) via the dispatch primitive. Idempotent no-op if
    the modal isn't present. Returns True if it was dismissed."""
    present = cfx.evaluate("(()=>[...document.querySelectorAll('*')]"
                           ".some(e=>/write better applications/i.test(e.textContent||'')&&e.children.length<8))()")
    if present is not True:
        return False
    # climb from the heading to the nearest ancestor holding an svg (the modal card, whose
    # first svg is the close X — the CTA button is text-only), then click that svg's wrapper.
    finder = ("(()=>{const h=[...document.querySelectorAll('*')]"
              ".find(e=>/write better applications/i.test(e.textContent||'')&&e.children.length<8);"
              "if(!h) return null; let card=h;"
              "for(let i=0;i<8&&card;i++){ if(card.querySelector('svg')) break; card=card.parentElement; }"
              "if(!card) return null; const svg=card.querySelector('svg');"
              "return svg ? (svg.closest('button,[role=button],div')||svg) : null;})()")
    _react_click(finder)
    time.sleep(1)
    return True


def _progress():
    import re
    body = cfx.evaluate("document.body.innerText") or ""
    m = re.search(r"All done|\d+\s*section\(?s?\)?\s*(left|to)", body, re.I)
    return m.group(0) if m else "?"


def _send_enabled():
    return cfx.evaluate("""(()=>{const b=[...document.querySelectorAll('button')].find(x=>/send now/i.test(x.innerText));
      return b? !b.disabled : null;})()""")


def start(url):
    cfx.navigate(url)
    time.sleep(5)
    if _click_text("Apply") == "NF":
        print("FAIL: no Apply button (already applied, or wrong page?)")
        return 1
    time.sleep(2)
    # detect modal type
    kind = cfx.evaluate(r"""(()=>{
      const btns=[...document.querySelectorAll('button,a')].map(b=>(b.innerText||'').trim());
      if (btns.some(t=>/apply with your profile/i.test(t))) return 'IN_PLATFORM';
      const ext=btns.find(t=>/apply on .+ website/i.test(t));
      return ext ? ('EXTERNAL:'+ext) : 'UNKNOWN';
    })()""")
    if kind.startswith("EXTERNAL"):
        print(f"EXTERNAL-ONLY — no in-platform apply. {kind[9:]}. Take the company site + use that ATS's recipe.")
        return 2
    if kind != "IN_PLATFORM":
        print(f"UNKNOWN modal state: {kind}")
        return 1
    _click_text("Apply with your profile")
    time.sleep(4)
    dismiss_promo()  # the "write better applications" promo modal blocks the form until closed
    print(f"IN-PLATFORM apply open. Progress: {_progress()} | Send enabled: {_send_enabled()}")
    return 0


# A WTTJ question is a label followed by its answer control in a SEPARATE sibling div, so the
# control's owning question = the nearest PRECEDING label with substantive (non-hint) text.
# Binding by this walk is deterministic; the old "first empty textarea globally" mis-routed
# answers between fields on multi-question forms (e.g. a salary landing in the AI-example box).
_LABELWALK = r"""
  function _labelOf(el){let n=el;
    for(let hop=0;hop<8;hop++){let s=n.previousElementSibling;
      while(s){const t=(s.textContent||'').replace(/\s+/g,' ').trim();
        if(t.length>10 && !/^\(optional\)|recommend|type your answer|choose an option|select\.\.\.|great length|by putting|please note|if you are|please detail|we know this/i.test(t)) return t.toLowerCase();
        s=s.previousElementSibling;}
      n=n.parentElement; if(!n)break;}
    return '';}"""


def save_section():
    """Commit the current WTTJ section by clicking its Save button (a section stays incomplete
    until Saved even when every field validates). Returns 'clicked'/'NF'."""
    r = _react_click("[...document.querySelectorAll('button')]"
                     ".find(x=>/^save$/i.test((x.textContent||'').trim()) && x.getBoundingClientRect().width>0)")
    time.sleep(2)
    return r


def answer(question, text, save=True):
    """Fill a WTTJ Application Question (text/url/date input OR textarea) by a substring of its
    label. Reveals the field (React needs a dispatched click, not DOM .click()), then sets the
    value on the control whose nearest-preceding label matches — NOT the first empty field. Use
    `pick` for the react-select (Yes/No) dropdowns. Saves the section unless save=False."""
    if text.startswith("@"):
        with open(text[1:], encoding="utf-8") as f:
            text = f.read().strip()
    q = _js(question)
    # 1) reveal: dispatch-click the "Type your answer here" placeholder owned by this question
    _react_click(f"""(()=>{{{_LABELWALK}
      const q={q}.toLowerCase();
      return [...document.querySelectorAll('p,div,span')].find(e=>e.children.length===0
        && /type your answer/i.test(e.textContent||'') && _labelOf(e).includes(q)) || null;}})()""")
    time.sleep(0.8)
    # 2) set value on the input/textarea owned by this question (React-safe native setter)
    res = cfx.evaluate(f"""(()=>{{{_LABELWALK}
      const q={q}.toLowerCase();
      const el=[...document.querySelectorAll('input,textarea')].find(e=>
        !/radio|checkbox|hidden/.test(e.type||'') && (e.id||'').indexOf('react-select')<0 && _labelOf(e).includes(q));
      if(!el) return 'FIELD_NF';
      const proto=el.tagName==='TEXTAREA'?window.HTMLTextAreaElement.prototype:window.HTMLInputElement.prototype;
      const set=Object.getOwnPropertyDescriptor(proto,'value').set;
      el.focus(); set.call(el,''); el.dispatchEvent(new Event('input',{{bubbles:true}}));
      set.call(el,{_js(text)});
      el.dispatchEvent(new Event('input',{{bubbles:true}})); el.dispatchEvent(new Event('change',{{bubbles:true}})); el.blur();
      return 'set:'+el.value.length;
    }})()""")
    if not (isinstance(res, str) and res.startswith("set:")):
        print(f"FAIL answer set: {res} for {question!r}")
        return 1
    time.sleep(0.6)
    if save:
        save_section()
    print(f"answered {question!r} ({res[4:]} chars). Progress: {_progress()}")
    return 0


def pick(question, option):
    """Select `option` in the react-select dropdown owned by `question` (Yes/No eligibility,
    consent, etc.). opts.py/pick.py can't be used on WTTJ — they call /click, which HANGS — so
    this opens the control and clicks the option entirely via the dispatch primitive."""
    q = _js(question)
    opened = cfx.evaluate(f"""(()=>{{{_LABELWALK}
      const q={q}.toLowerCase();
      const inp=[...document.querySelectorAll('[id^=react-select-][id$=-input]')].find(e=>_labelOf(e).includes(q));
      if(!inp) return 'SELECT_NF';
      let ctrl=inp; for(let i=0;i<4;i++){{ctrl=ctrl.parentElement; if(ctrl&&(ctrl.className||'').toString().includes('control'))break;}}
      if(!ctrl) ctrl=inp.parentElement; ctrl.scrollIntoView({{block:'center'}});
      for(const t of {_CLICK_SEQ}) ctrl.dispatchEvent(new MouseEvent(t,{{bubbles:true,cancelable:true,view:window}}));
      return 'opened';}})()""")
    if opened != "opened":
        print(f"FAIL pick: {opened} for {question!r}")
        return 1
    time.sleep(1)
    r = _react_click(f"""(()=>{{const s={_js(option)}.toLowerCase();
      const opts=[...document.querySelectorAll('[id*=option]')].filter(e=>(e.textContent||'').trim());
      return opts.find(e=>(e.textContent||'').trim().toLowerCase()===s)
          || opts.find(e=>(e.textContent||'').toLowerCase().includes(s)) || null;}})()""")
    time.sleep(0.6)
    print(f"picked {option!r} for {question!r}: {r}")
    return 0 if r == "clicked" else 1


def status():
    print(f"Progress: {_progress()} | Send now enabled: {_send_enabled()}")
    return 0 if _progress().lower().startswith("all done") else 1


# WTTJ shows this error when its backend fails to relay an in-platform application to the
# company's real ATS (common for external-ATS-backed jobs, e.g. Maze on Ashby). It is NOT a
# click failure — the Send fired; WTTJ just can't submit. The fallback is "Apply on <co>'s
# website". This is the true cause of the old "Send lands, no confirmation" reports.
_CANT_SUBMIT = r"can.?t submit your application right now|couldn.?t submit your application"
_SENT_OK = r"rooting for you|application sent|we.?ve sent your application|thanks for applying"


def send():
    """Submit the in-platform application. Returns:
      0  submitted (WTTJ confirmation shown)
      1  not ready (sections incomplete)
      2  unclear (no confirmation text — screenshot to verify)
      3  EXTERNAL_FALLBACK — WTTJ can't submit in-platform; apply on the company ATS
         instead (run `open-external`, drive that ATS, then `resolve-applied yes`)."""
    import re
    dismiss_promo()
    if not _send_enabled():
        print(f"NOT READY: Send now is disabled ({_progress()}). Finish the remaining section(s) first.")
        return 1
    _click_text("Send now")
    deadline = time.time() + 18
    while time.time() < deadline:
        time.sleep(3)
        body = cfx.evaluate("document.body.innerText") or ""
        if re.search(_SENT_OK, body, re.I):
            print("SUCCESS: application sent ('We're rooting for you!').")
            return 0
        if re.search(_CANT_SUBMIT, body, re.I):
            comp = cfx.evaluate(r"""(()=>{const b=[...document.querySelectorAll('button,a')]
              .find(x=>/apply on .+ website/i.test(x.textContent||''));return b?(b.textContent||'').trim():'';})()""") or ""
            print(f"EXTERNAL_FALLBACK: WTTJ can't submit in-platform. Apply on the company ATS. [{comp}]")
            return 3
    print("UNCLEAR: no confirmation text after send — screenshot to verify.")
    return 2


def open_external():
    """Click WTTJ's "Apply on <company>'s website" button (the external-ATS fallback). The
    ATS opens in a NEW tab; the caller drives it with the matching recipe (Ashby/Greenhouse/
    …) and then calls `resolve_applied_prompt`. Prints the company label; the new tab's URL
    identifies the ATS (poll `GET /tabs`). Returns 0 if clicked, 1 if no external button."""
    label = cfx.evaluate(r"""(()=>{const b=[...document.querySelectorAll('button,a')]
      .find(x=>/apply on .+ website/i.test(x.textContent||''));return b?(b.textContent||'').trim():'';})()""") or ""
    if not label:
        print("NF: no 'Apply on <company>'s website' button on this page.")
        return 1
    _react_click(r"[...document.querySelectorAll('button,a')].find(x=>/apply on .+ website/i.test(x.textContent||''))")
    time.sleep(3)
    print(f"OPENED external ATS ({label}). Find the new tab via GET /tabs and drive it with that ATS's recipe.")
    return 0


def resolve_applied_prompt(applied=True):
    """After an external-apply redirect, WTTJ shows a bottom-right "Did you apply?" toast with
    Yes/No. LEFT UNANSWERED IT BLOCKS THE FEED (can't advance to the next job — the "carousel
    lock-up"). Click Yes if we genuinely applied on the company site, else No. Idempotent:
    returns 0 if a toast was found and cleared, 1 if none was present."""
    import re
    body = cfx.evaluate("document.body.innerText") or ""
    if not re.search(r"did you apply", body, re.I):
        return 1
    label = "Yes" if applied else "No"
    _react_click(f"[...document.querySelectorAll('button')]"
                 f".find(x=>/^{label}$/i.test((x.textContent||'').trim()) && x.getBoundingClientRect().width>0)")
    time.sleep(2)
    still = re.search(r"did you apply", cfx.evaluate("document.body.innerText") or "", re.I)
    print(f"resolved 'Did you apply?' -> {label}" if not still else f"WARN: toast still present after clicking {label}")
    return 0


def main():
    a = sys.argv[1:]
    if not a:
        print(__doc__)
        return 1
    try:
        if a[0] == "start" and len(a) == 2:
            return start(a[1])
        if a[0] == "answer" and len(a) == 3:
            return answer(a[1], a[2])
        if a[0] == "pick" and len(a) == 3:
            return pick(a[1], a[2])
        if a[0] == "save":
            return 0 if save_section() == "clicked" else 1
        if a[0] == "status":
            return status()
        if a[0] == "send":
            return send()
        if a[0] == "open-external":
            return open_external()
        if a[0] == "resolve-applied" and len(a) <= 2:
            applied = (a[1].lower() in ("yes", "y", "true", "1")) if len(a) == 2 else True
            return resolve_applied_prompt(applied)
        if a[0] == "dismiss-promo":
            return 0 if dismiss_promo() else 1
    except cfx.CfxError as e:
        print(f"ERROR: {e}")
        return 2
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
