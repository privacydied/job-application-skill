#!/usr/bin/env python3
"""
apply.py — SmartRecruiters (jobs.smartrecruiters.com) apply driver.

New driver (per AGENTS.md — build it when it doesn't exist yet). Encapsulates the
shadow-DOM recipe verified in ../NOTES.md (first live submission: Legal & General,
"Product Analyst (Funds Oversight)", 744000145913189, 2026-08-28). SmartRecruiters'
"Easy apply" widget is built entirely from `spl-*` custom elements with nested OPEN
shadow roots — no plain <label>/<input> pairing at the top level, so atsform.py's
label-substring matchers don't reach it. This driver walks the shadow DOM directly.

Requires CFX_KEY / CFX_TAB in env (cfx.py init first), CFX_TAB pointed at the
jobs.smartrecruiters.com posting page.

Subcommands:
  start <url>                  Navigate to the posting, click "I'm interested" to open
                                the oneclick-ui apply widget. Idempotent.
  fields                       Dump every SPL-* field found in the shadow DOM (id, tag,
                                current value) — use to see what's on the current page.
  fill-text <id> <value>       Set a text/textarea field's real (shadow-nested) input.
  pick <id> <option-substr>    Type into an autocomplete field and commit via Enter
                                (never a synthetic click on the option node — verified
                                unreliable in NOTES.md).
  radio <id>                   Click an SPL-RADIO host by id (no native input to set).
  checkbox <id> [on|off]       Click the nested native <input type=checkbox> inside an
                                SPL-CHECKBOX host.
  upload <id> <basename>       Upload a file (bare basename already staged in uploads/)
                                via /uploadViaChooser (more reliable than plain /upload
                                for the nested SPL-DROPZONE per NOTES.md).
  next                         Click the SPL-BUTTON labelled "Next".
  submit                       Click the SPL-BUTTON labelled "Submit" — THE POINT OF NO
                                RETURN. Screenshots the resulting page as proof (no
                                separate confirmation URL exists here).
  apply <config.json> [--submit]
                                Orchestrator: start -> personal info (fill/pick) ->
                                upload -> next -> preliminary questions (radios/
                                checkboxes/pick) -> next -> (review) -> submit if
                                --submit and no errors surfaced along the way.

Config schema (apply):
{
  "url": "https://jobs.smartrecruiters.com/<Company>/<jobId>",
  "cv": "base-resume.pdf",
  "fill": {"first-name-input": "Jane", "last-name-input": "Doe", ...},
  "pick": {"city-autocomplete-id": "London, England, United Kingdom"},
  "radios": ["spl-form-element_3"],
  "checkboxes": {"spl-form-element_7": "on"}
}
"""
import os
import sys
import json
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "_common", "scripts"))
import cfx  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

_WALK_JS = """
const walk = (root, id) => {
  for (const el of root.querySelectorAll('*')) {
    if (el.id === id) return el;
    if (el.shadowRoot) { const f = walk(el.shadowRoot, id); if (f) return f; }
  }
  return null;
};
"""

_WALK_ALL_JS = """
const walkAll = (root, out) => {
  out = out || [];
  for (const el of root.querySelectorAll('*')) {
    if (el.id) out.push(el);
    if (el.shadowRoot) walkAll(el.shadowRoot, out);
  }
  return out;
};
"""


def _js(s):
    return json.dumps(str(s))


def start(url: str) -> int:
    """Navigate to the posting and click 'I'm interested' to open the apply widget."""
    r = cfx.goto(url)
    if not r.get("ok"):
        print(f"FAIL goto {url}: {r}")
        return 1
    cfx.dismiss_cookie_banner()
    time.sleep(0.5)
    res = cfx.evaluate("""
    (() => {
      const links = [...document.querySelectorAll('a')]
        .filter(a => a.textContent.trim().toLowerCase().includes("i'm interested"));
      if (!links.length) return 'NO_CTA';
      links[0].click();
      return 'CLICKED';
    })()
    """)
    print(res)
    time.sleep(1.5)
    return 0 if res == "CLICKED" or "oneclick-ui" in (cfx.current_url() or "") else 1


def fields() -> int:
    """Dump every id'd element found in the shadow DOM."""
    js = _WALK_ALL_JS + """
    (() => {
      const out = walkAll(document);
      return JSON.stringify(out.map(el => el.tagName + '#' + el.id +
        (el.value !== undefined ? '=' + String(el.value).slice(0,30) : '')));
    })()
    """
    res = cfx.evaluate(js)
    try:
        rows = json.loads(res)
    except (ValueError, TypeError):
        print(f"FAIL fields: {res}")
        return 1
    for r in rows:
        print(r)
    return 0


def fill_text(field_id: str, value: str) -> int:
    """Set a text/textarea field's real input (duplicate-id-safe, see _FIND_REAL_INPUT_JS)."""
    if value == "-":
        value = sys.stdin.read().strip()
    js = _FIND_REAL_INPUT_JS + f"""
    (() => {{
      const real = findReal(document, {_js(field_id)});
      if (!real) return 'NOT_FOUND';
      real.value = {_js(value)};
      real.dispatchEvent(new Event('input', {{bubbles: true}}));
      real.dispatchEvent(new Event('change', {{bubbles: true}}));
      return 'OK:' + real.value.slice(0, 40);
    }})()
    """
    res = cfx.evaluate(js)
    print(res)
    return 0 if isinstance(res, str) and res.startswith("OK") else 1


_FIND_REAL_INPUT_JS = """
// ids can DUPLICATE across nesting levels (e.g. an SPL-AUTOCOMPLETE wrapper and its
// inner SPL-INPUT sharing the same id — verified live, Mirantis 2026-09-04). Collect
// EVERY element with this id, then prefer the deepest real <input>, never the first
// (outer wrapper) match — writing to the wrapper's own value setter can report success
// on read-back without ever updating the visibly-rendered native input (NOTES.md).
const findReal = (root, id) => {
  const hits = [];
  const collect = (r) => {
    for (const el of r.querySelectorAll('*')) {
      if (el.id === id) hits.push(el);
      if (el.shadowRoot) collect(el.shadowRoot);
    }
  };
  collect(root);
  // Prefer a real native <input>/<textarea> among the hits.
  const native = hits.find(el => el.tagName === 'INPUT' || el.tagName === 'TEXTAREA');
  if (native) return native;
  // Else drill one level into the LAST hit (innermost wrapper)'s shadow root.
  const last = hits[hits.length - 1];
  if (last && last.shadowRoot) {
    const inner = last.shadowRoot.querySelector('input,textarea');
    if (inner) return inner;
  }
  return last || null;
};
"""


def pick(field_id: str, option_substr: str, option_value: str = None) -> int:
    """Commit an autocomplete field (city, etc.) via REAL Playwright focus+keyboard typing
    then a REAL Playwright click on the suggestion node — verified 2026-09-04 (Mirantis
    744000132893057) as the only path that actually binds the component's internal state.

    Two prior approaches both LOOKED like they worked (value read back correctly, visible
    text updated) but did NOT commit and left the "Please provide your place of residence"
    validation error lit — the field is a lit-element component whose real state binds only
    to genuine browser focus + genuine keydown events + a genuine mouse click on the
    rendered <spl-select-option>, not JS .value=/.dispatchEvent() or a JS .click():
      1. JS `.focus()` + `.value=` + dispatchEvent('input'/'change') on the real <input>
         (found via _FIND_REAL_INPUT_JS) — value read back correctly but
         `document.activeElement !== input` (JS .focus() didn't take on this shadow-nested
         input), so the subsequent Enter keypress went nowhere.
      2. Real focus+typing via /type mode=keyboard (page.focus + keyboard.press per char)
         WITHOUT a following real click — text visibly updates and reads back correctly,
         but the error persists; Enter alone does not select the highlighted option here
         (unlike other ATS autocompletes documented elsewhere in this skill).
    The fix: /type mode=keyboard to filter the list, THEN cfx.click_selector() (a REAL
    Playwright mouse click, not a JS .click()) on the matching <spl-select-option>. If
    `option_value` isn't given, derived heuristically as GB_ENG_CITY_<slug> for a UK city
    (SmartRecruiters' observed value scheme) — pass it explicitly for anything else."""
    sel = f'input#{field_id} >> nth=0'
    # clear any stale content first (mode=fill replaces, doesn't append)
    cfx.post(f"/tabs/{cfx._tab()}/type", {"userId": cfx._uid(), "selector": sel, "text": "", "mode": "fill"})
    time.sleep(0.3)
    cfx.post(f"/tabs/{cfx._tab()}/type", {"userId": cfx._uid(), "selector": sel, "text": option_substr, "mode": "keyboard"})
    time.sleep(1.5)  # async suggestion list round-trip
    if option_value is None:
        slug = option_substr.strip().lower().replace(" ", "_")
        option_value = f"GB_ENG_CITY_{slug}"
    opt_sel = f'spl-select-option[value="{option_value}"] >> nth=0'
    res = cfx.click_selector(opt_sel)
    if not res.get("ok"):
        print(f"FAIL pick {field_id!r}: could not click option {opt_sel!r}: {res}")
        return 1
    time.sleep(0.5)
    verify_js = _FIND_REAL_INPUT_JS + f"""
    (() => {{
      const real = findReal(document, {_js(field_id)});
      return real ? (real.value || '') : 'NOT_FOUND';
    }})()
    """
    committed = cfx.evaluate(verify_js)
    print(f"OK committed={committed!r}")
    return 0


def radio(field_id: str) -> int:
    """Click an SPL-RADIO host by id — no native input exists, the click itself toggles it."""
    js = _WALK_JS + f"""
    (() => {{
      const host = walk(document, {_js(field_id)});
      if (!host) return 'NOT_FOUND';
      host.click();
      return 'CLICKED';
    }})()
    """
    res = cfx.evaluate(js)
    print(res)
    return 0 if res == "CLICKED" else 1


def checkbox(field_id: str, state: str = "on") -> int:
    """Click the nested native <input type=checkbox> inside an SPL-CHECKBOX host."""
    want_checked = state != "off"
    js = _WALK_JS + f"""
    (() => {{
      const host = walk(document, {_js(field_id)});
      if (!host) return 'NOT_FOUND';
      let real = host;
      if (host.tagName !== 'INPUT' && host.shadowRoot) {{
        real = host.shadowRoot.querySelector('input[type=checkbox]') || host;
      }}
      if (real.checked === {str(want_checked).lower()}) return 'OK=already';
      real.click();
      return 'CLICKED:' + real.checked;
    }})()
    """
    res = cfx.evaluate(js)
    print(res)
    return 0 if isinstance(res, str) and (res.startswith("OK") or res.startswith("CLICKED")) else 1


def upload(field_id: str, basename: str) -> int:
    """Upload the resume. Plain /upload with a bare id selector — Playwright's built-in
    shadow-piercing CSS engine reaches the nested <input type=file> directly (verified in
    NOTES.md). Falls back to /uploadViaChooser if the plain path 500s."""
    path = os.path.join(ROOT, "uploads", basename)
    if not os.path.exists(path):
        print(f"FAIL upload: {path} not found in uploads/")
        return 1
    # SmartRecruiters duplicates some ids across a mobile/desktop DOM copy (verified:
    # 2x <input id="file-input">, both visible/sized) — Playwright's locator is
    # strict-mode and 500s on a multi-match. `>> nth=0` pins the first match.
    sel = f'input[id="{field_id}"] >> nth=0'
    try:
        res = cfx.post(f"/tabs/{cfx._tab()}/upload",
                        {"userId": cfx._uid(), "selector": sel, "path": f"/uploads/{basename}"})
        print(res)
        if res.get("ok"):
            return 0
    except cfx.CfxError as e:
        print(f"plain /upload failed: {e}; trying /uploadViaChooser")
    try:
        res = cfx.post(f"/tabs/{cfx._tab()}/uploadViaChooser",
                        {"userId": cfx._uid(), "trigger": sel, "path": f"/uploads/{basename}"})
        print(res)
        return 0 if res.get("ok") else 1
    except cfx.CfxError as e:
        print(f"FAIL upload: {e}")
        return 1


def _click_spl_button(label: str) -> int:
    js = f"""
    (() => {{
      const all = [...document.querySelectorAll('*')];
      const walkAll2 = (root, out) => {{
        for (const el of root.querySelectorAll('*')) {{
          out.push(el);
          if (el.shadowRoot) walkAll2(el.shadowRoot, out);
        }}
        return out;
      }};
      const found = walkAll2(document, []);
      const btn = found.find(el => el.tagName === 'SPL-BUTTON' &&
        el.textContent.trim() === {_js(label)});
      if (!btn) return 'NOT_FOUND';
      btn.click();
      return 'CLICKED';
    }})()
    """
    res = cfx.evaluate(js)
    print(res)
    return 0 if res == "CLICKED" else 1


def next_step() -> int:
    return _click_spl_button("Next")


def submit(slug: str = None) -> int:
    """THE POINT OF NO RETURN. Screenshot the result as proof."""
    rc = _click_spl_button("Submit")
    if rc != 0:
        return rc
    time.sleep(2.5)
    body = cfx.evaluate("document.body.innerText.slice(0,500)") or ""
    ok = "submitted" in str(body).lower() or "application submitted" in str(body).lower()
    if slug:
        out_dir = os.path.join(ROOT, "applications", slug)
        os.makedirs(out_dir, exist_ok=True)
        cfx.shot(os.path.join(out_dir, "confirmation.png"))
    print("SUBMIT_OK" if ok else f"SUBMIT_UNCONFIRMED: {body[:200]}")
    return 0 if ok else 1


def apply(config_path: str, do_submit: bool = False) -> int:
    with open(config_path) as f:
        cfg = json.load(f)
    url = cfg["url"]
    if start(url) != 0:
        print("ABORT: could not open apply widget")
        return 1
    time.sleep(1)
    if cfg.get("cv"):
        upload("file-input", cfg["cv"])
        time.sleep(1)
    for fid, val in (cfg.get("fill") or {}).items():
        fill_text(fid, val)
    for fid, val in (cfg.get("pick") or {}).items():
        pick(fid, val)
    next_step()
    time.sleep(1)
    # preliminary questions page (dynamically generated per posting)
    for fid in (cfg.get("radios") or []):
        radio(fid)
    for fid, val in (cfg.get("checkboxes") or {}).items():
        checkbox(fid, val)
    for fid, val in (cfg.get("pick_questions") or {}).items():
        pick(fid, val)
    next_step()
    time.sleep(1)
    if not do_submit:
        print("--- filled; NOT submitting (--submit not passed) ---")
        return 0
    company = cfg.get("company", "company")
    role = cfg.get("role", "role")
    slug = f"{company}-{role}".lower().replace(" ", "-")
    return submit(slug)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    cmd = sys.argv[1]
    args = sys.argv[2:]
    if cmd == "start" and args:
        return start(args[0])
    if cmd == "fields":
        return fields()
    if cmd == "fill-text" and len(args) >= 2:
        return fill_text(args[0], args[1])
    if cmd == "pick" and len(args) >= 2:
        return pick(args[0], args[1])
    if cmd == "radio" and args:
        return radio(args[0])
    if cmd == "checkbox" and args:
        return checkbox(args[0], args[1] if len(args) > 1 else "on")
    if cmd == "upload" and len(args) >= 2:
        return upload(args[0], args[1])
    if cmd == "next":
        return next_step()
    if cmd == "submit":
        return submit(args[0] if args else None)
    if cmd == "apply" and args:
        return apply(args[0], do_submit="--submit" in args)
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
