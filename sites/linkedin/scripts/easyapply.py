#!/usr/bin/env python3
"""
easyapply.py — LinkedIn "Easy Apply" modal driver.

⚠️ WHY THIS EXISTS (the bug it fixes)
LinkedIn's Easy Apply modal — AND its "Save this application?" confirm dialog —
render inside the **shadow DOM** of a `div.theme--light` host, NOT in the main
document. Consequences discovered live (2026-07-13, job 4430943239 FE fundinfo):
  * `document.querySelectorAll(...)` from the page never sees the modal buttons.
  * camofox `click <a11y-ref>` and `click-xy <x> <y>` DO NOT reliably resolve into
    the shadow top-layer — clicks silently no-op (byte-identical screenshots). This
    is what made the "Save this application?" dialog look like an unrecoverable
    stuck-loop in the old NOTES.md.
  * The fix: run a JS `.click()` / value read **inside the shadow root** (JS pierces
    open shadow DOM natively). That is what every primitive here does.

Playwright's own CSS engine also pierces open shadow roots, so camofox's
`/upload` and selector-based `/type` reach shadow inputs — but element *discovery*
by visible label still has to happen in JS (labels/steps are shadow-scoped), so we
resolve a stable [name]/[id] selector in the shadow root first, then hand that to
camofox for the trusted upload.

Built on cfx.py, so it inherits the pacing + referer anti-detection.

CLI:
  CFX_KEY=.. CFX_TAB=.. python3 easyapply.py <cmd> [args]
    open                     click the page's "Easy Apply" button (main doc, not shadow)
    dismiss-save             if a "Save this application?" dialog is up, cancel it
                             (click its Dismiss ✕) and return to the form. Safe no-op
                             if absent. RUN THIS right after `open` and after any step
                             where the dialog might re-appear.
    state                    JSON: {header, step, progress, nav, labels, errors} for
                             the current modal step
    fill  "<label>" "<val>"  fill a shadow text/textarea by visible-label substring
    select "<label>" "<opt>" pick a native <select> option by text (shadow)
    radio "<q>" "<opt>"      tick a radio in a group (shadow)
    check "<label>" [on|off] tick a checkbox (shadow)
    upload "<file-in-uploads>"  upload to the modal's file input (shadow-pierced)
    next [--force]           click the step's primary nav button
                             (Continue → Review → Submit), auto-detected.
                             Refuses (exit 3, BLOCKED_UNANSWERED_REQUIRED) if the
                             current step has a required text/select/radio field
                             still empty — fill it first, or pass --force if you've
                             confirmed by hand it isn't really required.
    submit                   click "Submit application"; report success/errors
    review                   dump every field label+value on the review step
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "_common", "scripts"))
import cfx  # noqa: E402

# camofox runs in a container where the skill's uploads/ dir is mounted at /uploads,
# and its /upload endpoint rejects any path that doesn't resolve inside /uploads. So
# an upload target is passed as "/uploads/<basename>" (NOT the host-side path).
UP = "/uploads"

# JS prelude: resolve the shadow root that hosts the Easy Apply modal. Falls back
# to `document` so read-only probes don't throw when the modal isn't open yet.
SR = r"""
const __host=[...document.querySelectorAll('*')].find(e=>e.shadowRoot && e.shadowRoot.querySelector('[role=dialog],[role=alertdialog]'));
const SR=__host?__host.shadowRoot:document;
// The shared shadow root can hold MORE than one [role=dialog] at once (confirmed
// live 2026-07-13: a "Phoebe R." messaging chat popup rendered its own [role=dialog]
// in the SAME shadow host as the Easy Apply modal). Picking the LAST one in DOM
// order is not reliable -- it can grab that unrelated small widget instead of the
// actual form, which then makes every field lookup silently miss (NO_FIELD/
// NO_SELECT) even though the fields genuinely exist in SR. Fix: pick the dialog
// whose own subtree actually contains form controls or the "Apply to" heading --
// i.e. the biggest/most-field-dense one -- not just "whichever is last".
const DLG=(()=>{
  const ds=[...SR.querySelectorAll('[role=dialog]')];
  if(!ds.length) return SR;
  const scored=ds.map(d=>({d,score:d.querySelectorAll('input,select,textarea,button').length}));
  scored.sort((a,b)=>b.score-a.score);
  return scored[0].d;
})();
const labelOf=el=>{ if(el.labels&&el.labels[0])return el.labels[0].innerText;
  if(el.getAttribute('aria-label'))return el.getAttribute('aria-label');
  // LinkedIn nests the question text in a PARENT container above the immediate
  // radio/select/input wrapper (no <label>/<legend>), so climb up to 4 ancestor
  // levels and aggregate their text — otherwise a substring match against the
  // question ("Bachelor's Degree?", "onsite setting") never sees it.
  const parts=[];
  let n=el;
  for(let i=0;i<5 && n; i++){ n=n.parentElement;
    if(!n) break;
    const lt=(n.innerText||'').replace(/\s+/g,' ').trim();
    if(lt) parts.push(lt);
    if(n.tagName==='FIELDSET'||n.tagName==='SECTION'||n.getAttribute('role')==='group') break; }
  const merged=parts.join(' ').replace(/\s+/g,' ').trim();
  return merged.slice(0,300); };
"""


def _ev(body):
    return cfx.evaluate("(()=>{" + SR + body + "})()")


def cmd_dismiss_save():
    r = _ev(r"""
      const dlg=[...SR.querySelectorAll('[role=alertdialog],[role=dialog]')]
        .find(d=>/Save this application/i.test(d.textContent||''));
      if(!dlg) return 'none';
      const x=[...dlg.querySelectorAll('button')].find(b=>/dismiss/i.test(b.getAttribute('aria-label')||''));
      if(!x) return 'no-dismiss';
      x.click(); return 'dismissed';
    """)
    print(r)
    return 0 if r in ("none", "dismissed") else 1


def cmd_state():
    r = _ev(r"""
      const header=(DLG.querySelector('h2,h3')?.innerText||'').replace(/\s+/g,' ').trim().slice(0,50);
      const step=([...DLG.querySelectorAll('h3,h4')].map(h=>h.innerText.trim()).find(Boolean)||'').slice(0,40);
      const progress=(DLG.innerText.match(/(\d+)%/)||[])[1]||null;
      const nav=[...DLG.querySelectorAll('button[aria-label]')].map(b=>b.getAttribute('aria-label'))
        .filter(a=>/next step|review|submit|continue/i.test(a));
      const labels=[...DLG.querySelectorAll('label,legend,h3,h4')].map(e=>e.innerText.replace(/\s+/g,' ').trim())
        .filter(Boolean).slice(0,120);
      const errors=[...DLG.querySelectorAll('[class*=error i],[role=alert]')].map(e=>e.innerText.replace(/\s+/g,' ').trim())
        .filter(t=>t && /required|select|enter|invalid|must/i.test(t)).slice(0,8);
      const saveDialog=/Save this application/i.test(SR.textContent||'');
      return JSON.stringify({header,step,progress,nav,saveDialog,errors,labels});
    """)
    print(r)
    return 0


def cmd_fill(label, value):
    if value == "-":
        value = sys.stdin.read()
    elif value.startswith("@"):
        with open(value[1:], encoding="utf-8") as f:
            value = f.read().strip()
    r = _ev(r"""
      const want=%s.toLowerCase();
      for(const el of DLG.querySelectorAll('input[type=text],input[type=email],input[type=tel],input[type=number],input[type=url],textarea')){
        if((labelOf(el)||'').toLowerCase().includes(want)){
          const set=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value')||
                    Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype,'value');
          const proto=el.tagName==='TEXTAREA'?window.HTMLTextAreaElement.prototype:window.HTMLInputElement.prototype;
          Object.getOwnPropertyDescriptor(proto,'value').set.call(el,%s);
          el.dispatchEvent(new Event('input',{bubbles:true}));
          el.dispatchEvent(new Event('change',{bubbles:true}));
          return 'OK:'+(el.value||'').slice(0,30);
        }
      }
      return 'NO_FIELD';
    """ % (json.dumps(label), json.dumps(value)))
    print(r)
    return 0 if isinstance(r, str) and r.startswith("OK") else 1


def cmd_select(label, option):
    r = _ev(r"""
      const want=%s.toLowerCase(), opt=%s.toLowerCase();
      for(const s of DLG.querySelectorAll('select')){
        if((labelOf(s)||'').toLowerCase().includes(want)){
          const o=[...s.options].find(o=>o.text.trim().toLowerCase()===opt)
                ||[...s.options].find(o=>o.text.toLowerCase().includes(opt));  // exact-first: don't let "United States" pick "…Minor Outlying Islands"
          if(!o) return 'NO_OPTION:'+[...s.options].map(o=>o.text.trim()).slice(0,12).join('|');
          s.value=o.value; s.dispatchEvent(new Event('change',{bubbles:true}));
          return 'OK:'+o.text.trim().slice(0,40);
        }
      }
      return 'NO_SELECT';
    """ % (json.dumps(label), json.dumps(option)))
    print(r)
    return 0 if isinstance(r, str) and r.startswith("OK") else 1


def cmd_radio(question, option):
    r = _ev(r""" 
      const wq=%s.toLowerCase(), wo=%s.toLowerCase();
      const ctxOf=el=>{ const parts=[]; let n=el;
        // Do NOT break at the first <fieldset>/<section>/[role=group]: LinkedIn wraps
        // each radio in an inner fieldset whose text is only "Yes/No", while the actual
        // question ("Are you comfortable commuting...") lives in a PARENT container.
        // Climb several ancestors and aggregate — the option match (wo) keeps it precise.
        for(let i=0;i<6 && n; i++){ n=n.parentElement; if(!n) break;
          const lt=(n.innerText||'').replace(/\s+/g,' ').trim(); if(lt) parts.push(lt);
          if(n===DLG) break; }
        return parts.join(' ').replace(/\s+/g,' ').trim().toLowerCase().slice(0,400); };
      for(const rb of DLG.querySelectorAll('input[type=radio]')){
        const fs=rb.closest('fieldset');
        const q=(fs?(fs.querySelector('legend,label')||{}).innerText:rb.name)||'';
        const lbl=(rb.labels&&rb.labels[0])?rb.labels[0].innerText:(rb.value||'');
        const ctx=ctxOf(rb);
        // match the QUESTION against the fieldset legend/name OR the wider container
        // text (LinkedIn often omits a <legend>, nesting the question in a plain div).
        if((q.toLowerCase().includes(wq)||ctx.includes(wq))&&lbl.toLowerCase().includes(wo)){ if(!rb.checked)rb.click();
          return rb.checked?('OK:'+lbl.trim().slice(0,30)):'CLICK_FAILED'; }
      }
      return 'NOT_FOUND';
    """ % (json.dumps(question), json.dumps(option)))
    print(r)
    return 0 if isinstance(r, str) and r.startswith("OK") else 1


def cmd_check(label, state="on"):
    want = "true" if state != "off" else "false"
    r = _ev(r"""
      const w=%s.toLowerCase();
      for(const c of DLG.querySelectorAll('input[type=checkbox]')){
        const lbl=(c.labels&&c.labels[0])?c.labels[0].innerText:labelOf(c);
        if((lbl||'').toLowerCase().includes(w)){ if(c.checked!==%s)c.click();
          return c.checked===%s?('OK checked='+c.checked):'CLICK_FAILED'; }
      }
      return 'NOT_FOUND';
    """ % (json.dumps(label), want, want))
    print(r)
    return 0 if isinstance(r, str) and r.startswith("OK") else 1


def cmd_upload(filename):
    """Resolve the modal's file input to a stable selector in the shadow root, then
    hand it to camofox /upload (Playwright's selector engine pierces open shadow)."""
    sel = _ev(r"""
      const f=DLG.querySelector('input[type=file]')||SR.querySelector('input[type=file]');
      if(!f) return '';
      if(f.id) return 'input[id="'+f.id+'"]';
      if(f.name) return 'input[name="'+f.name+'"]';
      f.setAttribute('data-ea-file','1'); return 'input[data-ea-file="1"]';
    """)
    if not sel:
        print("FAIL upload: no file input in modal")
        return 1
    path = filename if filename.startswith("/uploads/") else f"{UP}/{os.path.basename(filename)}"
    try:
        cfx.post(f"/tabs/{cfx._tab()}/upload",
                 {"userId": cfx._uid(), "selector": sel, "path": path})
    except cfx.CfxError as e:
        print(f"FAIL upload: {e}")
        return 1
    time.sleep(1.5)
    # LinkedIn moves the picked file OUT of the <input> into a selected "resume card"
    # almost immediately, so input.files[0] is usually already empty — checking it is a
    # false negative. Verify against the modal's rendered text (the card shows the
    # filename with a "Deselect resume <name>" control) instead.
    base = os.path.basename(filename)
    got = _ev(r"""
      const f=DLG.querySelector('input[type=file]')||SR.querySelector('input[type=file]');
      const inInput=f&&f.files&&f.files[0]?f.files[0].name:'';
      const inCard=(DLG.textContent||'').includes(%s)?%s:'';
      return inInput||inCard||'NONE';
    """ % (json.dumps(base), json.dumps(base)))
    ok = isinstance(got, str) and got.endswith(base)
    print(f"{'OK' if ok else 'CHECK'} upload: {got}")
    return 0 if ok else 1


def _click_nav(patterns):
    return _ev(r"""
      const re=new RegExp(%s,'i');
      const b=[...DLG.querySelectorAll('button')].find(x=>re.test(x.getAttribute('aria-label')||x.innerText||''));
      if(!b) return 'NO_BUTTON';
      b.scrollIntoView({block:'center'}); b.click(); return 'clicked:'+((b.getAttribute('aria-label')||b.innerText).trim().slice(0,30));
    """ % json.dumps(patterns))


def _unanswered_required():
    """Real, required screener fields on the CURRENT step that are still empty —
    checked before every `next` so a caller that forgets to fill a field (or a loop
    that advances too eagerly) can't silently skip past it. THIS EXISTS because a
    real run advanced past an "Additional Questions" step without answering it,
    which looked to the user like "the bot just dismissed" the questions — `next`
    only ever clicked whatever nav button matched, with no check that the step it
    was leaving still had unfilled required fields. Covers required text/textarea/
    number/email/tel/url inputs, required <select>s with no real option chosen, and
    required radio-button groups with nothing checked. Does NOT check checkboxes
    (a required consent checkbox and an optional "Follow company" one are not
    reliably distinguishable here, and false-blocking on a legitimate optional
    checkbox would be worse than missing this one category)."""
    r = _ev(r"""
      const unanswered=[];
      for(const el of DLG.querySelectorAll('input[type=text],input[type=email],input[type=tel],input[type=number],input[type=url],textarea')){
        const req=el.required||el.getAttribute('aria-required')==='true';
        if(req&&!(el.value||'').trim()) unanswered.push((labelOf(el)||el.name||'(unlabeled field)').slice(0,60));
      }
      for(const s of DLG.querySelectorAll('select')){
        const req=s.required||s.getAttribute('aria-required')==='true';
        if(req&&(!s.value||s.selectedIndex<=0)) unanswered.push((labelOf(s)||'(unlabeled select)').slice(0,60));
      }
      const seen=new Set();
      for(const rb of DLG.querySelectorAll('input[type=radio]')){
        const name=rb.name; if(!name||seen.has(name)) continue; seen.add(name);
        const group=[...DLG.querySelectorAll('input[type=radio][name="'+CSS.escape(name)+'"]')];
        const req=group.some(x=>x.required||x.getAttribute('aria-required')==='true');
        const any=group.some(x=>x.checked);
        if(req&&!any){
          const fs=rb.closest('fieldset');
          unanswered.push(((fs&&(fs.querySelector('legend,label')||{}).innerText)||name||'(unlabeled question)').slice(0,60));
        }
      }
      return JSON.stringify(unanswered);
    """)
    try:
        return json.loads(r) if isinstance(r, str) else []
    except (ValueError, TypeError):
        return []


def cmd_next(force=False):
    # Prefer Submit, then Review, then Continue — so a single `next` always advances
    # toward completion and naturally lands on submit at the end.
    if not force:
        missing = _unanswered_required()
        if missing:
            print("BLOCKED_UNANSWERED_REQUIRED: " + " | ".join(missing))
            print("Fill each of these with `fill`/`select`/`radio` (see `state`'s labels), "
                  "then call `next` again. Pass --force only if you've confirmed by hand "
                  "these aren't actually required.")
            return 3
    for pat in ("submit application", "review your application|^review$", "continue to next step|next"):
        r = _click_nav(pat)
        if isinstance(r, str) and r.startswith("clicked"):
            print(r)
            return 0
    print("NO_NAV_BUTTON")
    return 1


def cmd_submit():
    r = _click_nav("submit application")
    if not (isinstance(r, str) and r.startswith("clicked")):
        # NO_BUTTON here is ambiguous, not necessarily a real failure: if a human is
        # also driving this same session (e.g. via VNC) and clicks Submit between our
        # own state-check and click attempt, the button is legitimately gone by the
        # time we look — same DOM signature as "we clicked it and it's gone", but we
        # get here reporting FAIL instead of SUCCESS. Confirmed live 2026-07-13: this
        # exact race happened (user clicked Submit on the Baller League application
        # while the bot was mid-flow), and the bot's FAIL report was actively
        # misleading — it read as "not submitted yet, safe to keep editing fields",
        # when the application had already gone out. Before reporting failure, check
        # for the same success text cmd_submit's own poll loop looks for.
        already_sent = cfx.evaluate(r"""(()=>{
          const t=document.body.innerText||'';
          return /application sent|your application was sent|application submitted/i.test(t) ? 'SENT' : '';
        })()""")
        if already_sent == "SENT":
            print("SUCCESS: application sent (submit button was already gone when checked - "
                  "likely someone else, e.g. the user via VNC, clicked it first. Verify against "
                  "the site's own Applied/tracker list before trusting this, same as any other "
                  "confirmation).")
            return 0
        print(f"FAIL: no submit button ({r})")
        return 1
    print(r)
    deadline = time.time() + 18
    while time.time() < deadline:
        time.sleep(3)
        done = cfx.evaluate(r"""(()=>{
          const t=document.body.innerText||'';
          return /application sent|your application was sent|application submitted|done|premium/i.test(t) &&
                 /application (was )?sent|applied|submitted/i.test(t) ? 'SENT' : '';
        })()""")
        if done == "SENT":
            print("SUCCESS: application sent.")
            return 0
    print("UNCLEAR: screenshot to confirm.")
    return 2


def cmd_review():
    r = _ev(r"""
      const rows=[];
      for(const el of DLG.querySelectorAll('input,textarea,select')){
        const lbl=(labelOf(el)||'').replace(/\s+/g,' ').trim().slice(0,40);
        let v=el.value; if(el.type==='checkbox'||el.type==='radio')v=el.checked?'[x]':'[ ]';
        if(lbl) rows.push(lbl+' = '+(v||'').slice(0,50));
      }
      return JSON.stringify(rows,null,1);
    """)
    print(r)
    return 0


def cmd_open():
    r = cfx.evaluate(r"""(()=>{
      const b=[...document.querySelectorAll('button,a')].find(x=>/easy apply to this job|^easy apply$/i.test(
        (x.getAttribute('aria-label')||x.innerText||'').trim()));
      if(!b) return 'NO_BUTTON'; b.click(); return 'clicked';
    })()""")
    print(r)
    return 0 if r == "clicked" else 1


def main():
    a = sys.argv[1:]
    if not a:
        print(__doc__)
        return 1
    c = a[0]
    try:
        if c == "open":                       return cmd_open()
        if c == "dismiss-save":               return cmd_dismiss_save()
        if c == "state":                      return cmd_state()
        if c == "fill" and len(a) == 3:       return cmd_fill(a[1], a[2])
        if c == "select" and len(a) == 3:     return cmd_select(a[1], a[2])
        if c == "radio" and len(a) == 3:      return cmd_radio(a[1], a[2])
        if c == "check" and len(a) in (2, 3): return cmd_check(a[1], a[2] if len(a) == 3 else "on")
        if c == "upload" and len(a) == 2:     return cmd_upload(a[1])
        if c == "next":                       return cmd_next(force="--force" in a)
        if c == "submit":                     return cmd_submit()
        if c == "review":                     return cmd_review()
    except cfx.CfxError as e:
        print(f"ERROR: {e}")
        return 2
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
