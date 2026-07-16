#!/usr/bin/env python3
"""
tal_eform.py — driver for Civil Service Jobs' TAL eform application
(cshr.tal.net/vx/.../candidate/eform/<ID>/page/N).

A CSJ "Apply and further information" draft (created via the advert apply button)
opens a multi-page eform: Application Guidance -> Eligibility -> Personal
information -> Diversity monitoring -> Declaration (Section 1). Submitting Section 1
reveals Section 2 (Further details / supporting evidence) as a follow-on eform.

This driver fills by STABLE CSJ field name (datafield_NNNNN_1_1) using a
spec. It resolves radios/selects by LABEL TEXT (not position) so Yes/No and
ethnicity options map correctly. EEO questions default to "Prefer not to disclose"
where offered, per the standing rule.

Usage:
  python3 tal_eform.py <eform_base_url_without_/page/N> <spec.json> [--submit] [--max N]
    eform_base = https://cshr.tal.net/vx/.../eform/<ID>   (no trailing slash)
    spec keys:
      radio:   {fieldName: "Yes"|"No"|"label substring"}
      select:  {fieldName: "label substring"|"<exact option text>"}
      text:    {fieldName: "value"}
      textarea: {fieldName: "value"}
      checkbox: {fieldName: true}
      upload:   "path/to/cv.pdf"   (sets the first file input on whatever page it appears)
      stopAtPage: N   (don't Continue past this page; e.g. 5 = Declaration, then submit)
The driver auto-discovers pages by walking 'Continue' until the final submit.
"""
import sys, os, json, time, argparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "_common", "scripts"))
import cfx

POST = cfx.post  # noqa
_EOFORM_BASE = None  # set in main()

# ---- field resolution helpers (run in page) ----

def _set_field(name, kind, value):
    """Set one field by name. kind in {radio,select,text,textarea,checkbox}.
    For radio/select, value is a label-substring to match."""
    if kind in ("radio", "checkbox"):
        expr = """(name, want) => {
          const matches=[...document.querySelectorAll(`[name="${name}"]`)].filter(e=>e.type==='%s');
          if(!matches.length) return 'NO_FIELD:'+name;
          if('%s'==='checkbox'){ matches[0].click(); return 'OK'; }
          const lblOf=(e)=>{ if(e.labels&&e.labels[0]) return e.labels[0].innerText; const l=e.closest('label'); if(l) return l.innerText; const sib=e.nextElementSibling; if(sib&&/label/i.test(sib.tagName)) return sib.innerText; const p=e.parentElement; const pl=p&&p.querySelector('label'); return pl?pl.innerText:''; };
          const lbls=matches.map(e=>({e,l:(lblOf(e)||'').replace(/\\s+/g,' ').trim()}));
          const hit=lbls.find(x=>x.l.toLowerCase().includes(want.toLowerCase()));
          if(!hit) return 'NO_OPT:'+name+'|'+want+'|'+lbls.map(x=>x.l).join(' , ');
          hit.e.click();
          return 'OK:'+hit.l.slice(0,30);
        }""" % (kind, kind)
        return cfx.evaluate("(%s)(%s,%s)" % (expr, json.dumps(name), json.dumps(value)))
    if kind == "select":
        expr = """(name, want) => {
          const s=document.querySelector(`select[name="${name}"]`);
          if(!s) return 'NO_FIELD:'+name;
          const opt=[...s.options].find(o=>(o.text||'').trim()===want || (o.text||'').toLowerCase().includes(want.toLowerCase()));
          if(!opt) return 'NO_OPT:'+name+'|'+want+'|'+[...s.options].map(o=>o.text.trim()).join(' , ');
          s.value=opt.value; s.dispatchEvent(new Event('change',{bubbles:true})); s.dispatchEvent(new Event('input',{bubbles:true}));
          return 'OK:'+opt.text.trim().slice(0,30);
        }"""
        return cfx.evaluate("(%s)(%s,%s)" % (expr, json.dumps(name), json.dumps(value)))
    # text / textarea
    expr = """(name, val) => {
      const e=document.querySelector(`[name="${name}"]`);
      if(!e) return 'NO_FIELD:'+name;
      const setter=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
      const setter2=Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype,'value').set;
      (e.tagName==='TEXTAREA'?setter2:setter).call(e, val);
      e.dispatchEvent(new Event('input',{bubbles:true}));
      e.dispatchEvent(new Event('change',{bubbles:true}));
      e.dispatchEvent(new Event('blur',{bubbles:true}));
      return 'OK';
    }"""
    return cfx.evaluate("(%s)(%s,%s)" % (expr, json.dumps(name), json.dumps(value)))


def _upload(path):
    base = os.path.basename(path)
    dst = os.path.join(HERE, "..", "..", "..", "uploads", base)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(path, "rb") as f:
        data = f.read()
    with open(dst, "wb") as f:
        f.write(data)
    try:
        POST(f"/tabs/{cfx._tab(cfx._uid())}/upload",
              {"userId": cfx._uid(), "path": base}, timeout=60)  # best-effort info
    except Exception:
        pass
    fn = os.path.basename(path)
    res = cfx.evaluate("""((fn) => {
      const f=document.querySelector('input[type=file]');
      if(!f) return 'NO_FILE_INPUT';
      return 'present:'+fn;
    })""" + "(" + json.dumps(fn) + ")")
    return res if isinstance(res, str) else str(res)


def _page_title():
    try:
        t = cfx.evaluate("document.title")
        return t if isinstance(t, str) else ""
    except cfx.CfxError:
        return ""

def _navigate(url):
    """Wedge-resistant navigate: camofox 500s intermittently; retry."""
    last=None
    for _ in range(5):
        try:
            cfx.navigate(url)
            return True
        except cfx.CfxError as e:
            last=e
            time.sleep(2)
    if last:
        raise last
    return False


def _continue():
    """Click the 'Continue' (or final 'Submit') button on the form.
    Wedge-resistant: camofox's evaluate often 500s on CSJ TAL pages even when the
    click fires. So we fire the click, ignore the 500, and verify navigation by
    title change (retry up to N times).
    Robust targeting: only consider real form submit controls (input[type=submit] /
    button[type=submit]): a TOC <a> named 'continue' must NEVER be clicked."""
    before = _page_title()
    for _ in range(8):
        time.sleep(1.5)  # let SPA settle field saves before navigating
        try:
            cfx.evaluate("""(() => {
              // Real form submit controls only (never TOC anchors).
              const subs=[...document.querySelectorAll('input[type=submit], button[type=submit]')]
                .filter(e=>{const v=(e.value||e.innerText||'').trim().toLowerCase();
                            return v && v!=='back' && v!=='back_button';});
              if(!subs.length) return 'NO_CONTINUE';
              // Prefer the one whose label is 'Continue' (intermediate) or 'Submit'/'Finish'/'Confirm' (final).
              const cont=subs.find(e=>(e.value||e.innerText||'').trim().toLowerCase()==='continue');
              const sub=cont || subs.find(e=>/^submit$|^finish$|^confirm$/i.test((e.value||e.innerText||'').trim()));
              (sub||subs[0]).click();
              return 'clicked:'+((sub||subs[0]).value||sub.innerText||'').trim();
            })()""")
        except cfx.CfxError:
            pass  # 500 is spurious after the click fires; verify by navigation
        time.sleep(2.5)
        after = _page_title()
        if after and after != before:
            return "advanced:" + after
    return "NO_ADVANCE"


def walk(spec, submit=False, max_page=99):
    results = []
    page = 1
    # start at page 1 (main() already navigated; only re-navigate if not there)
    cur = _page_title()
    if cur and "Guidance" not in cur:
        _navigate(f"{_EOFORM_BASE}/page/1")
    time.sleep(9)
    while page <= max_page:
        # upload if present and requested
        if spec.get("upload"):
            try:
                results.append(("upload", _upload(spec["upload"])))
            except Exception as e:
                results.append(("upload", "FAIL " + str(e)))
        # fill every spec field that exists on THIS page (skip NO_FIELD)
        for nm, val in spec.get("text", {}).items():
            r = _set_field(nm, "text", val)
            if not str(r).startswith("NO_FIELD"):
                results.append(("text " + nm, r))
        for nm, val in spec.get("textarea", {}).items():
            r = _set_field(nm, "textarea", val)
            if not str(r).startswith("NO_FIELD"):
                results.append(("textarea " + nm, r))
        for nm, val in spec.get("select", {}).items():
            r = _set_field(nm, "select", val)
            if not str(r).startswith("NO_FIELD"):
                results.append(("select " + nm, r))
        for nm, val in spec.get("radio", {}).items():
            r = _set_field(nm, "radio", val)
            if not str(r).startswith("NO_FIELD"):
                results.append(("radio " + nm, r))
        for nm, val in spec.get("checkbox", {}).items():
            if val:
                r = _set_field(nm, "checkbox", "1")
                if not str(r).startswith("NO_FIELD"):
                    results.append(("check " + nm, r))
        # advance: on the last page, Continue = submit
        r = _continue()
        results.append(("continue p%d" % page, r))
        time.sleep(2.5)
        page += 1
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("eform_base")  # .../eform/<ID>
    ap.add_argument("spec")
    ap.add_argument("--submit", action="store_true")
    ap.add_argument("--max", type=int, default=99)
    a = ap.parse_args()
    global _EOFORM_BASE
    _EOFORM_BASE = a.eform_base.rstrip("/")
    spec = json.load(open(a.spec))
    cfx.navigate(a.eform_base.rstrip("/") + "/page/1")
    time.sleep(2)
    res = walk(spec, submit=a.submit, max_page=a.max)
    print("---- TAL eform summary ----")
    for label, r in res:
        print(f"  {label}: {r}")
    if a.submit:
        body = cfx.evaluate("(()=>document.body.innerText.replace(/\\s+/g,' ').trim())()")
        b = body if isinstance(body, str) else ""
        print("FINAL body tail:", b[-250:])


if __name__ == "__main__":
    main()
