#!/usr/bin/env python3
"""
atsform.py — shared, ATS-agnostic application-form engine.

The Ashby driver (`sites/ashbyhq/scripts/ashby.py`) proved a set of primitives that
are ~90% the same on ANY ATS (Greenhouse, Lever, Workable, Workday, Recruitee, …):
fill a labelled text field, pick a dropdown option, tick a radio/checkbox, upload a
file, review, submit. Those live here so each new ATS adapter is a thin file that
just adds that ATS's quirks (its reveal button, custom controls, success signal).

Everything targets fields by a **substring of their visible LABEL**, because label
text is stable across postings while `name`/`id` are random per posting. Built on
`cfx.py`, so it inherits the pacing + referer anti-detection.

Importable (adapters do `from atsform import fill, select, ...`) or CLI:
    CFX_KEY=... CFX_TAB=... python3 atsform.py <apply|fill|select|pick|combo|combo-type|radio|checkbox|upload|review|submit|click> ...
    # pick "<label|css/#id>" "<option>" [--multi] [--clear]   ⭐ the universal dropdown driver:
    #                                native <select> AND every react-select variant via the
    #                                interaction ladder (mousedown → ArrowDown → trusted click →
    #                                type-to-filter). --multi = mark-all-that-apply; --clear =
    #                                remove existing chips first. `select`/`combo`/`pick-dropdown`
    #                                all route through this ONE engine (combobox_pick).
    # combo "<css/#id>" "<option>"   alias for `pick` by selector (kept for back-compat)
    # combo-type "<css/#id>" "<text>"  type-to-search react-select (e.g. a Location autocomplete)

Primitives (all return 0 on success, non-zero on failure, and print a status line):
  fill      "<label>" "<value|@file|->"   text/textarea by label ("@path" reads a file, "-" stdin)
  select    "<label>" "<option>"          native <select> OR react-select combobox, by option text
  radio     "<question>" "<option>"       radio group by question, option by label substring
  checkbox  "<label>" [on|off]            checkbox by label
  upload    "<label|#id>" <file-in-uploads>  file input by label or id
  click     "<button text>"               click by visible text, self-verifying: reports
                                          new_tab/same_tab_nav/same_page_dom_changed, or exit 2
                                          "NO_CHANGE" if nothing detectably happened -- never trust
                                          a bare "clicked" the way this used to
  review    "<Company>" [must,have,kw]    ⚠️ pre-submit audit — flags surviving [placeholders], any
                                          OTHER company mentioned in free-text, empty required fields,
                                          and (optional) missing JD must-have keywords. Exit !=0 if any.
  submit    "<button text>" "<success regex>"  click submit, wait, verify success text / report alerts

  apply     <config.json> [--submit]      ⚡ fill a WHOLE form from ONE JSON config in a single
                                          process — the speed primitive. One CLI call (one model
                                          turn, one python startup, in-process HTTP) instead of one
                                          call PER FIELD (each its own turn + bash/curl/python fork).
                                          Runs upload → fill → select → radios → checkboxes → review
                                          in the autofill-safe order, keeps going past a failed field,
                                          prints ONE consolidated pass/fail summary, and submits only
                                          with --submit AND a clean review. Config keys (all optional):
                                            {"defaults": true,
                                             "upload":{"<label|#id>":"<file>"},
                                             "fill":{"<label>":"<value|@file>"},
                                             "select":{"<label>":"<option>"},
                                             "radios":{"<question>":"<option>"},
                                             "checkboxes":{"<label>":"on"|"off"|true|false},
                                             "review":"<Company>", "must_haves":["kw",...],
                                             "submit":{"button":"Submit","success":"<regex>"}}
                                          "defaults": true merges sites/_common/apply-defaults.json
                                          (constant applicant facts: name/email/phone/links/
                                          opt-outs) with OPTIONAL semantics — a default matching
                                          no field on this form SKIPs silently, and any explicit
                                          config key overlapping a default key suppresses that
                                          default. The model writes ONLY the JD-specific keys.
"""
import csv
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cfx  # noqa: E402
import stagetimer  # noqa: E402  (no-op unless STAGETIMER is set)


def _js(s):
    return json.dumps(s)


# Resolve a fillable field (input/textarea) by a label → a stable CSS selector
# (prefers name, then id). Matches labels[0], aria-label, or a wrapping
# fieldset/label's text. Returns '' if none.
#
# ⚠️ MATCH PRECEDENCE (do NOT collapse back to "first substring wins"):
#   1. exact       — normalised label == want
#   2. word-prefix — label starts with want at a word boundary ("Phone" ~ "Phone Number")
#   3. word-match  — want appears in the label at word boundaries
#   4. substring   — the old loose behaviour, last resort
# Normalisation strips a trailing `*`, a parenthetical like "(Optional)", and
# collapses whitespace, so "Phone*" / "Phone (Optional)" still match "Phone".
#
# WHY: the resolver used to take the FIRST loose substring hit in DOM order, so a
# short label silently captured a *different*, earlier field whose text merely
# contained it. Verified live on Paddle's Ashby form (2026-07-17):
# `fill "Phone" "+44…"` wrote the phone number into **"Phonetic Pronunciation
# (Optional)"** — which appears first — and left the real "Phone" field empty.
# That is a silent wrong-data submission, not a crash: `check` reported the form
# "answered" while the data sat in the wrong box. Exact-first fixes the whole class
# ("Name" vs "Full Name"/"Name of referrer", "Email" vs "Email me updates", …).
_RESOLVE = r"""
(() => {
  const want = %s.toLowerCase().trim();
  const kinds = %s;  // e.g. 'input,textarea' or 'select'
  const labelText = el => {
    if (el.labels && el.labels[0]) return el.labels[0].innerText;
    if (el.getAttribute('aria-label')) return el.getAttribute('aria-label');
    const fs = el.closest('fieldset,label,div');
    return fs ? (fs.querySelector('label,legend') || fs).innerText || '' : '';
  };
  // strip required marker + trailing parenthetical, collapse whitespace
  const norm = s => (s || '')
    .replace(/\*/g, ' ')
    .replace(/\((?:optional|required)\)/ig, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .toLowerCase();
  const sel = el => {
    if (el.name) return '[name="' + el.name.replace(/"/g,'\\"') + '"]';
    if (el.id) return '[id="' + el.id.replace(/"/g,'\\"') + '"]';
    return null;  // matched but unaddressable
  };
  const esc = want.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const wordRe   = new RegExp('\\b' + esc + '\\b');
  const prefixRe = new RegExp('^' + esc + '\\b');
  const tiers = [[], [], [], []];
  for (const el of document.querySelectorAll(kinds)) {
    const lab = norm(labelText(el));
    if (!lab) continue;
    if (lab === want) tiers[0].push(el);
    else if (prefixRe.test(lab)) tiers[1].push(el);
    else if (wordRe.test(lab)) tiers[2].push(el);
    else if (lab.includes(want)) tiers[3].push(el);
  }
  for (const tier of tiers) if (tier.length) return sel(tier[0]);
  return '';
})()
""".strip()


def _resolve(label, kinds="input[type=text],input[type=email],input[type=tel],input[type=number],input[type=url],textarea"):
    return cfx.evaluate(_RESOLVE % (_js(label), _js(kinds)))


# E.2: sentinel a primitive returns (only when asked via quiet_notfound) so the
# defaults path can SKIP a field that isn't on this form without a separate
# _field_exists pre-probe (which re-resolved the same label). Default behavior of
# every primitive is unchanged — quiet_notfound defaults False.
NOTFOUND = "__ATSFORM_NOTFOUND__"

# B.2: current href + visible-text length in ONE evaluate (was two per poll iteration
# in click_button/_wait_change). Returns (href_or_'', len_or_None); on any evaluate
# error returns ('', None) so the caller treats the iteration as "no change, keep
# polling" rather than crashing.
_URL_LEN_JS = "JSON.stringify({href:location.href,len:(document.body.innerText||'').length})"


def _url_len():
    try:
        raw = cfx.evaluate(_URL_LEN_JS)
        d = json.loads(raw) if isinstance(raw, str) else (raw or {})
        return d.get("href", "") or "", (int(d["len"]) if d.get("len") is not None else None)
    except (cfx.CfxError, ValueError, TypeError):
        return "", None


def fill(label, value, quiet_notfound=False):
    # "-" reads stdin, "@path" reads a file. A missing/unreadable @file must
    # fail as a clean FAIL line + non-zero exit, NOT an uncaught OSError escaping
    # main() (whose try only catches cfx.CfxError) as a raw traceback.
    if value == "-":
        value = sys.stdin.read()
    elif value.startswith("@"):
        try:
            with open(value[1:], encoding="utf-8") as f:
                value = f.read().strip()
        except OSError as e:
            print(f"FAIL fill: cannot read value file {value[1:]!r}: {e}")
            return 1
    sel = _resolve(label)
    if not sel:
        if quiet_notfound:      # E.2: defaults path skips a missing field silently
            return NOTFOUND
        print(f"FAIL fill: no text field for label ~{label!r}")
        return 1
    _read = f"(()=>{{const e=document.querySelector({_js(sel)});return e?e.value:null;}})()"
    def alnum(s):
        return re.sub(r"[^a-z0-9]", "", (s or "").lower())
    # IDEMPOTENCY: if the field ALREADY holds this value, don't re-type it. Re-running
    # `apply <config>` to fix ONE missed field would otherwise re-type EVERY field from
    # scratch — slow, and on controlled React inputs a blind re-type can DOUBLE the
    # existing text (the bug set_textarea.py exists to dodge). Skipping already-correct
    # fields makes a re-run top up only what's missing/wrong instead of rewriting the
    # whole form. The first fill still types normally (empty field won't match).
    try:
        cur = cfx.evaluate(_read)
    except cfx.CfxError:
        cur = None
    cur_s = cur if isinstance(cur, str) else ""
    if cur_s.strip() == value.strip() or (bool(alnum(value)) and alnum(cur_s) == alnum(value)):
        print(f"OK= fill {label!r} (already filled, {len(cur_s)} chars — skipped re-type)")
        return 0
    try:
        cfx.post(f"/tabs/{cfx._tab()}/type",
                 {"userId": cfx._uid(), "selector": sel, "text": value, "mode": "fill"})
    except cfx.CfxError as e:
        print(f"FAIL fill: {e}")
        return 1
    # B.3: poll until the value lands instead of a blind sleep(0.3) then one read —
    # returns the instant React commits the value (often <0.3s) and is more robust on
    # slow inputs. The reformatting-tolerant match is the predicate, so phone masks etc.
    # still settle it early; on timeout poll returns the last read and the MISMATCH
    # branch below handles it exactly as the old single read did.
    got = cfx.poll(
        _read,
        predicate=lambda r: isinstance(r, str) and (
            r.strip() == value.strip() or (bool(alnum(value)) and alnum(r) == alnum(value))),
        timeout=1.2, interval=0.1)
    # A field can legitimately reformat what we typed (phone masks, number spinners,
    # whitespace trimming, "+44 7700 900000" -> "(0) 7700 900000"). Treat the fill as
    # OK on an exact match OR when the alphanumerics round-trip (only formatting
    # differs); only a genuine content difference is a hard MISMATCH.
    got_s = got if isinstance(got, str) else ""
    exact = got_s.strip() == value.strip()
    ok = exact or (bool(alnum(value)) and alnum(got_s) == alnum(value))
    tag = "OK" if exact else ("OK~ (reformatted)" if ok else "MISMATCH")
    print(f"{tag} fill {label!r} ({len(got_s)} chars)")
    return 0 if ok else 1


# ═══════════════════════════════════════════════════════════════════════════
# combobox_pick — the ONE universal dropdown/combobox driver every ATS shares.
#
# PHILOSOPHY: drive at the INTERACTION layer, not the DOM-contract layer. Match a field
# by accessible semantics (label text / role), OPEN it with the primitive human interaction,
# and READ the resulting menu from SEVERAL fallbacks — never one framework-specific contract
# (a class name, `aria-controls`). react-select (Greenhouse, Lever, Ashby, WTTJ, SmartRecruiters
# — all the same library) toggles its menu on the control's MOUSEDOWN; some variants also open
# on ArrowDown; a few need a real trusted click; big async lists (Country/Location) need typing.
# So the OPEN LADDER tries, in order, stopping at the first rung that renders options:
#   1) synthetic pointer sequence (pointerdown/mousedown/mouseup) on the control  ← proven, fast
#   2) focus + a real ArrowDown key
#   3) a trusted Playwright click on the input (last resort — can hang ~30s on Greenhouse)
#   4) type-to-filter (real per-char keystrokes) for large async/typeahead lists
# and it READS options from: the aria-controls listbox → the open .select__menu → global
# .select__option → [role=option]. No single variant can stump a ladder, and because every
# combobox caller (select/react_select/pick_dropdown/answer) routes through this ONE engine,
# a fix here fixes every ATS at once. A widget that won't drive is a CAPABILITY GAP to debug
# (probe_widget.py), never a "structural limit" — only an eligibility question with no truthful
# answer is a legitimate stop.
# ═══════════════════════════════════════════════════════════════════════════

_COMBO_READ_OPTS = r"""
(() => {
  const inp = document.querySelector('[data-ats-target]');
  let els = [];
  if (inp) { const ac = inp.getAttribute('aria-controls'); const box = ac && document.getElementById(ac);
    if (box) els = [...box.querySelectorAll('[role=option],[class*="option"]')]; }
  if (!els.length) { const m = document.querySelector('[class*="select__menu"],[class*="-menu"]');
    if (m) els = [...m.querySelectorAll('[class*="option"],[role=option]')]; }
  if (!els.length) els = [...document.querySelectorAll('[class*="select__option"]')];
  if (!els.length) els = [...document.querySelectorAll('[role=option]')];
  return JSON.stringify(els.map(e => (e.textContent||'').replace(/\s+/g,' ').trim()).filter(Boolean).slice(0,80));
})()
"""

_COMBO_POINTER_OPEN = r"""
(() => {
  const i = document.querySelector('[data-ats-target]'); if (!i) return 'NO_INPUT';
  let c = i.closest('[class*="control"]');
  if (!c) { let n=i; for(let k=0;k<6&&n;k++,n=n.parentElement){const x=n.querySelector&&n.querySelector('[class*="control"]');if(x){c=x;break;}} }
  if (!c) c = i;
  c.scrollIntoView({block:'center'});
  ['pointerdown','mousedown','mouseup'].forEach(t => c.dispatchEvent(new MouseEvent(t,{bubbles:true,cancelable:true,view:window})));
  return 'OPENED';
})()
"""

_COMBO_CLICK = r"""
(() => {
  const t = __OPT__.replace(/\s+/g,' ').trim().toLowerCase();
  const inp = document.querySelector('[data-ats-target]');
  let els = [];
  const ac = inp && inp.getAttribute('aria-controls'); const box = ac && document.getElementById(ac);
  if (box) els = [...box.querySelectorAll('[role=option],[class*="option"]')];
  if (!els.length) { const m = document.querySelector('[class*="select__menu"],[class*="-menu"]'); if (m) els = [...m.querySelectorAll('[class*="option"],[role=option]')]; }
  if (!els.length) els = [...document.querySelectorAll('[class*="select__option"],[role=option]')];
  const norm = e => (e.textContent||'').replace(/\s+/g,' ').trim().toLowerCase();
  // exact first; else WORD-BOUNDARY substring (never mid-word — so "No" can't match
  // "Monaco" and "Man" can't match a stray "…man…"), scanned REVERSED so a real appended
  // option wins over a prefixed country-list entry (react-select Remix prepends countries).
  const esc = t.replace(/[-/\\^$*+?.()|[\]{}]/g, '\\$&');
  const wb = new RegExp('(^|[^a-z0-9])' + esc + '([^a-z0-9]|$)');
  let o = els.find(e => norm(e) === t);
  if (!o) for (let ix = els.length - 1; ix >= 0; ix--) { if (wb.test(norm(els[ix]))) { o = els[ix]; break; } }
  document.querySelectorAll('[data-ats-target]').forEach(e=>e.removeAttribute('data-ats-target'));
  if (!o) return 'NO_OPTION:'+els.map(e=>(e.textContent||'').replace(/\s+/g,' ').trim()).slice(0,10).join(' | ');
  o.scrollIntoView({block:'center'});
  ['pointerdown','mousedown','mouseup','click'].forEach(tp => o.dispatchEvent(new MouseEvent(tp,{bubbles:true,cancelable:true,view:window})));
  return 'OK:'+(o.textContent||'').replace(/\s+/g,' ').trim().slice(0,40);
})()
"""

_COMBO_RESOLVE = r"""
(() => {
  const norm = s => (s||'').replace(/\s+/g,' ').trim().toLowerCase();
  document.querySelectorAll('[data-ats-target],[data-ats-native]').forEach(e=>{e.removeAttribute('data-ats-target');e.removeAttribute('data-ats-native');});
  const target = __TARGET__;
  let el = null;
  if (/^[#.\[]/.test(target)) { try { el = document.querySelector(target); } catch(e){} }
  else { el = document.getElementById(target); }
  if (!el) { try { el = (__FIND__)(target); } catch(e){} }
  if (!el) return JSON.stringify({kind:'none'});
  if (el.tagName === 'SELECT') { el.setAttribute('data-ats-native','1');
    const cur = el.options[el.selectedIndex];
    return JSON.stringify({kind:'native', current:(cur && cur.value!=='')?[norm(cur.text)]:[]}); }
  let inp = el;
  if (el.tagName !== 'INPUT') inp = el.querySelector('input[role=combobox],input[class*="select__input"],input') || el;
  inp.setAttribute('data-ats-target','1');
  const ctrl = inp.closest('[class*="control"]');
  const single = ctrl ? [...ctrl.querySelectorAll('[class*="singleValue"]')].map(v=>norm(v.textContent)) : [];
  const chips = ctrl ? [...ctrl.querySelectorAll('[class*="multi-value__label"],[class*="multiValueLabel"]')].map(v=>norm(v.textContent)) : [];
  const box = inp.closest('div');
  const isMulti = chips.length>0 || (box && /mark all/i.test(box.innerText||''));
  return JSON.stringify({kind:'combo', current:[...single,...chips].filter(Boolean), isMulti:!!isMulti});
})()
"""

_COMBO_NATIVE_SET = r"""
(() => {
  const s = document.querySelector('[data-ats-native]'); if (!s) return 'NO';
  const w = __OPT__.toLowerCase();
  const cur = s.options[s.selectedIndex];
  const esc = w.replace(/[-/\\^$*+?.()|[\]{}]/g, '\\$&');
  const wb = new RegExp('(^|[^a-z0-9])' + esc + '([^a-z0-9]|$)');
  if (cur && cur.value!=='' && (cur.text.toLowerCase()===w || wb.test(cur.text.toLowerCase()))) return 'OK=already:'+cur.text.trim().slice(0,40);
  const o = [...s.options].find(o=>o.text.trim().toLowerCase()===w) || [...s.options].find(o=>wb.test(o.text.toLowerCase()));
  if (!o) return 'NO_OPTION';
  const nv = Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype,'value').set;
  nv.call(s,o.value); s.dispatchEvent(new Event('input',{bubbles:true})); s.dispatchEvent(new Event('change',{bubbles:true}));
  return 'OK:'+o.text.trim().slice(0,40);
})()
"""

_COMBO_CLEAR_CHIPS = r"""
(() => {
  const i = document.querySelector('[data-ats-target]'); const c = i && i.closest('[class*="control"]');
  if (!c) return 0; let n=0;
  for (const b of c.querySelectorAll('[class*="multi-value__remove"],[class*="multiValueRemove"]')) {
    ['pointerdown','mousedown','mouseup','click'].forEach(t=>b.dispatchEvent(new MouseEvent(t,{bubbles:true,cancelable:true,view:window}))); n++;
  }
  return n;
})()
"""


def _combo_focus():
    cfx.evaluate("(()=>{const i=document.querySelector('[data-ats-target]');"
                 "if(i){i.scrollIntoView({block:'center'});i.focus();}})()")


def _combo_options():
    raw = cfx.evaluate(_COMBO_READ_OPTS)
    try:
        return json.loads(raw) if isinstance(raw, str) else []
    except ValueError:
        return []


def _combo_type(option):
    """Real per-char keystrokes into the focused combobox input — synthetic input events are
    IGNORED by react-select and the /type endpoint 500s, so this is how big async/typeahead
    lists (Country, Location) get filtered down to the target."""
    _combo_focus()
    for ch in str(option)[:24]:
        try:
            cfx.press(ch)
        except cfx.CfxError:
            pass
        time.sleep(0.05)
    time.sleep(0.7)


def _combo_open_and_pick(option, multi=False):
    """Open the react-select marked [data-ats-target] via the interaction LADDER, read its
    options from several fallbacks, and commit the match. THE engine every combobox caller
    shares (see the block header). Returns 0 on success, 1 otherwise."""
    want = str(option).strip().lower()
    _wb = re.compile(r'(^|[^a-z0-9])' + re.escape(want) + r'([^a-z0-9]|$)') if want else None

    def _has_match(opts):
        # exact OR word-boundary substring — never a mid-word hit (mirrors _COMBO_CLICK).
        return any(o.strip().lower() == want or (_wb and _wb.search(o.strip().lower())) for o in opts)

    _combo_focus()
    # 3) trusted click is the last-resort opener AND the one that can hang (~30s on Greenhouse
    #    remix) — time-box it to 6s so a stuck widget falls through to type-to-filter instead of
    #    stalling the whole run (the Graphcore "combobox_pick hung the run" symptom).
    rungs = (lambda: cfx.evaluate(_COMBO_POINTER_OPEN),     # 1) synthetic pointer sequence
             lambda: cfx.press("ArrowDown"),                # 2) real ArrowDown key
             lambda: cfx.click_selector('[data-ats-target]', timeout=6))  # 3) trusted click, bounded
    opts = []
    for rung in rungs:
        try:
            rung()
        except Exception:  # noqa: BLE001 — a dead rung must fall through to the next
            pass
        cfx.poll(_COMBO_READ_OPTS,
                 predicate=lambda r: isinstance(r, str) and r not in ("", "[]"), timeout=2.5)
        opts = _combo_options()
        if _has_match(opts):
            break
    if not _has_match(opts):        # 4) big typeahead (Country/Location) — filter then re-read
        _combo_type(option)
        cfx.poll(_COMBO_READ_OPTS,
                 predicate=lambda r: isinstance(r, str) and r not in ("", "[]"), timeout=2.5)
    clicked = cfx.evaluate(_COMBO_CLICK.replace("__OPT__", _js(option)))
    print(clicked if isinstance(clicked, str) else "FAIL")
    return 0 if isinstance(clicked, str) and clicked.startswith("OK") else 1


def combobox_pick(target, option, multi=False, clear_first=False, quiet_notfound=False):
    """THE universal dropdown/combobox primitive — native <select> AND every react-select
    variant, driven by the interaction ladder (see block header). `target` = a CSS/#id
    selector OR a substring of the field's visible label. `multi` = mark-all-that-apply
    (adds, doesn't replace); `clear_first` removes existing chips first (to REPLACE a wrong
    multi-select answer). Returns 0 / 1 / NOTFOUND (the last only with quiet_notfound when
    no such field exists — the defaults path uses it to skip a missing field cleanly)."""
    resolve_js = _COMBO_RESOLVE.replace("__TARGET__", _js(target)).replace("__FIND__", _FIND_CONTROL)
    try:
        info = json.loads(cfx.evaluate(resolve_js))
    except (ValueError, TypeError):
        info = {"kind": "none"}
    kind = info.get("kind")
    if kind == "none":
        if quiet_notfound:
            return NOTFOUND
        print(f"FAIL combobox_pick: no select/combobox for {target!r}")
        return 1
    want = str(option).strip().lower()
    # IDEMPOTENCY: already shows the target → don't disturb it (re-clicking a multi-select
    # option would TOGGLE it off; re-setting a native select can reset dependent fields).
    if any(c == want for c in info.get("current", [])):
        print(f"OK= combobox_pick {target!r} already = {option!r}")
        return 0
    if kind == "native":
        res = cfx.evaluate(_COMBO_NATIVE_SET.replace("__OPT__", _js(option)))
        print(res if isinstance(res, str) else "FAIL")
        return 0 if isinstance(res, str) and res.startswith("OK") else 1
    if clear_first:
        cfx.evaluate(_COMBO_CLEAR_CHIPS)
        time.sleep(0.3)
    return _combo_open_and_pick(option, multi=multi or bool(info.get("isMulti")))


def select(label, option, quiet_notfound=False):
    """Native <select> first; else a react-select combobox (Greenhouse/Lever/WTTJ).
    quiet_notfound (defaults path only): return NOTFOUND instead of FAIL when NO
    select-like field for this label exists on the form (E.2 — replaces _field_exists)."""
    # 1) native <select>
    nsel = _resolve(label, kinds="select")
    if nsel:
        res = cfx.evaluate(f"""
        (() => {{
          const s = document.querySelector({_js(nsel)});
          const want = {_js(option)}.toLowerCase();
          // IDEMPOTENCY: if the desired option is ALREADY selected, don't re-set it —
          // re-dispatching 'change' can reset dependent fields (country->state cascades)
          // and a re-run of `apply` shouldn't disturb already-correct selections. Guard
          // on value!=='' so a blank placeholder (selectedIndex 0) never counts as a match.
          const cur = s.options[s.selectedIndex];
          if (cur && cur.value !== '' && cur.text.toLowerCase().includes(want))
            return 'OK=already:' + cur.text.trim().slice(0,40);
          // Prefer an EXACT option match before falling back to substring, so
          // "United States" can't silently pick "United States Minor Outlying
          // Islands" (and "Yes" can't pick "Yes, I consent…") when an exact option
          // exists. Mirrors the react-select path and pick.py's disambiguation.
          const opt = [...s.options].find(o => o.text.trim().toLowerCase() === want)
                   || [...s.options].find(o => o.text.toLowerCase().includes(want));
          if (!opt) return 'NO_OPTION';
          s.value = opt.value;
          s.dispatchEvent(new Event('change', {{bubbles:true}}));
          return 'OK:' + opt.text.trim().slice(0,40);
        }})()
        """)
        print(res if isinstance(res, str) else "FAIL")
        return 0 if isinstance(res, str) and res.startswith("OK") else 1
    # 2) react-select combobox (Greenhouse/Lever/WTTJ). Resolve by label (labels[0]
    # for/id association first, then aria-label, then nearest container text), JS-focus
    # the input, and open the menu with a REAL ArrowDown key.
    #   Why not a trusted /click on the input? On Greenhouse it HANGS ~30s (the click
    #   triggers a React re-render Playwright waits on) and often leaves the menu shut;
    #   a synthetic value-set does NOT open the menu either (aria-expanded stays false).
    #   A real ArrowDown on the JS-focused input opens it reliably — verified live.
    # Then match the option scoped to THIS input's aria-controls listbox, so the
    # always-in-DOM react-phone country list (200 [role=option]s) can't pollute the match.
    opened = cfx.evaluate(f"""
    (() => {{
      const want = {_js(label)}.toLowerCase();
      const wantOpt = {_js(option)}.trim().toLowerCase();
      document.querySelectorAll('[data-ats-target]').forEach(e=>e.removeAttribute('data-ats-target'));
      const inputs = [...document.querySelectorAll('input[role=combobox],input[aria-autocomplete=list],input[id^="react-select"]')];
      for (const inp of inputs) {{
        const lbl = (inp.labels && inp.labels[0]) ? inp.labels[0].innerText
                  : (inp.getAttribute('aria-label')
                  || (inp.closest('fieldset,div,label') || {{}}).innerText || '');
        if ((lbl || '').toLowerCase().includes(want)) {{
          // IDEMPOTENCY: if this react-select ALREADY displays EXACTLY the target
          // option, skip — don't re-open/re-click. A re-run of `apply` shouldn't
          // disturb a correct selection, and on a MULTI-select re-clicking the
          // chosen option would toggle it OFF. EXACT match only (via react-select's
          // [class*=singleValue]) so a different value that merely CONTAINS the
          // target ("Yes, I consent" vs "Yes") still proceeds and gets corrected;
          // any non-match falls through to the normal open+click below.
          const ctrl = inp.closest('[class*=control]');
          const cur = ctrl ? [...ctrl.querySelectorAll('[class*=singleValue]')]
                              .map(v => (v.textContent||'').trim().toLowerCase()) : [];
          if (cur.some(v => v === wantOpt)) return 'ALREADY:' + wantOpt;
          inp.setAttribute('data-ats-target','1'); inp.scrollIntoView({{block:'center'}}); inp.focus();
          return '1';
        }}
      }}
      return '';
    }})()
    """)
    if not opened:
        # 3) Workday multiselect prompt — NOT a react-select: the widget is a
        # [data-automation-id=multiSelectContainer] with an input[placeholder="Search"]
        # inside a [data-automation-id^="formField-"] whose text carries the label
        # (e.g. "How Did You Hear About Us?"). Options render as
        # [data-automation-id=promptOption]. Buttons/inputs here need a TRUSTED click
        # (synthetic .click() no-ops on Workday — see sites/myworkdayjobs/NOTES.md), so
        # drive it via cfx.click_selector, not an in-page .click().
        wd = cfx.evaluate(f"""
        (() => {{
          const want = {_js(label)}.toLowerCase();
          document.querySelectorAll('[data-ats-target]').forEach(e=>e.removeAttribute('data-ats-target'));
          for (const f of document.querySelectorAll('[data-automation-id^="formField-"]')) {{
            if (!(f.innerText||'').toLowerCase().includes(want)) continue;
            const inp = f.querySelector('[data-automation-id=multiSelectContainer] input, input[placeholder="Search"]');
            if (!inp) continue;
            inp.setAttribute('data-ats-target','1'); inp.scrollIntoView({{block:'center'}}); inp.focus();
            return '1';
          }}
          return '';
        }})()
        """)
        if wd != "1":
            if quiet_notfound:
                return NOTFOUND  # E.2: no select-like field on this form → defaults skip
            print(f"FAIL select: no native <select>, react-select, or Workday multiselect for {label!r}")
            return 1
        try:
            cfx.click_selector('input[data-ats-target="1"]')
        except cfx.CfxError:
            pass
        cfx.poll("[...document.querySelectorAll('[data-automation-id=promptOption]')].map(o=>o.textContent.trim())",
                 predicate=lambda r: isinstance(r, list) and len(r) > 0, timeout=3.0)
        picked = cfx.evaluate(f"""
        (() => {{
          document.querySelectorAll('[data-ats-pick]').forEach(e=>e.removeAttribute('data-ats-pick'));
          const t = {_js(option)}.trim().toLowerCase();
          const els = [...document.querySelectorAll('[data-automation-id=promptOption]')];
          const o = els.find(x => x.textContent.trim().toLowerCase() === t)
                 || els.find(x => x.textContent.trim().toLowerCase().includes(t));
          if (!o) return 'NO_OPTION:' + els.map(x=>x.textContent.trim()).slice(0,8).join('|');
          o.setAttribute('data-ats-pick','1'); return 'MARK';
        }})()
        """)
        if not (isinstance(picked, str) and picked == "MARK"):
            print(f"FAIL select Workday {label!r}: {picked}")
            return 1
        try:
            cfx.click_selector('[data-ats-pick="1"]')
        except cfx.CfxError:
            cfx.evaluate("(()=>{const e=document.querySelector('[data-ats-pick]');if(e)e.click();})()")
        ok = cfx.evaluate(f"""
        (() => {{
          const f = [...document.querySelectorAll('[data-automation-id^="formField-"]')]
                    .find(x => (x.innerText||'').toLowerCase().includes({_js(label)}.toLowerCase()));
          if (!f) return '?';
          const t = f.innerText || '';
          return (/\\bselected\\b/i.test(t) && !/\\b0 items? selected\\b/i.test(t)) ? 'OK' : '?';
        }})()
        """)
        print(f"OK: Workday multiselect {label!r} <- {option!r}" if ok == "OK"
              else f"select Workday {label!r}: clicked option but 'selected' not confirmed ({ok})")
        return 0 if ok == "OK" else 1
    if isinstance(opened, str) and opened.startswith("ALREADY"):
        print(f"OK= select {label!r} (already shows {option!r} — skipped re-open)")
        return 0
    time.sleep(0.3)
    # react-select branch resolved (the input is marked data-ats-target) → hand off to the
    # ONE shared ladder engine so every combobox caller benefits from the same fix.
    return _combo_open_and_pick(option)


def set_radio(question, option, quiet_notfound=False):
    res = cfx.evaluate(f"""
    (() => {{
      const wq = {_js(question)}.toLowerCase(), wo = {_js(option)}.toLowerCase();
      for (const r of document.querySelectorAll('input[type=radio]')) {{
        const fs = r.closest('fieldset');
        const q = (fs ? (fs.querySelector('legend,label')||{{}}).innerText : r.name) || '';
        const lbl = (r.labels && r.labels[0]) ? r.labels[0].innerText : (r.value||'');
        if (q.toLowerCase().includes(wq) && lbl.toLowerCase().includes(wo)) {{
          if (!r.checked) r.click();
          return r.checked ? ('OK:'+lbl.slice(0,40)) : 'CLICK_FAILED';
        }}
      }}
      return 'NOT_FOUND';
    }})()
    """)
    if isinstance(res, str) and res.startswith("OK"):
        print(res)
        return 0
    # Workday fallback: its Yes/No radios carry NO visible label on the input
    # (r.labels is empty, r.value is "true"/"false"), so the text-match loop above
    # can't find them. Match the enclosing [data-automation-id^="formField-"] by the
    # QUESTION text, then pick input[type=radio][value=true|false]. Trusted click
    # (synthetic .click() no-ops on Workday) — see sites/myworkdayjobs/NOTES.md.
    wo = option.strip().lower()
    val = "true" if wo in ("yes", "true") else ("false" if wo in ("no", "false") else "")
    if val:
        mk = cfx.evaluate(f"""
        (() => {{
          const wq = {_js(question)}.toLowerCase();
          document.querySelectorAll('[data-ats-radio]').forEach(e=>e.removeAttribute('data-ats-radio'));
          const f = [...document.querySelectorAll('[data-automation-id^="formField-"]')]
                    .find(x => (x.innerText||'').toLowerCase().includes(wq));
          if (!f) return 'NO_FIELD';
          const r = f.querySelector('input[type=radio][value="{val}"]');
          if (!r) return 'NO_RADIO';
          if (r.checked) return 'ALREADY';
          r.setAttribute('data-ats-radio','1'); return 'MARK';
        }})()
        """)
        if mk in ("ALREADY", "MARK"):
            if mk == "MARK":
                try:
                    cfx.click_selector('input[data-ats-radio="1"]')
                except cfx.CfxError:
                    cfx.evaluate("(()=>{const e=document.querySelector('[data-ats-radio]');if(e)e.click();})()")
            print(f"OK: Workday radio {question!r} <- {option!r} (value={val})")
            return 0
        if quiet_notfound and mk == "NO_FIELD":
            return NOTFOUND  # E.2: no radio group for this question → defaults skip
        print(f"set_radio Workday {question!r}: {mk}")
        return 1
    if quiet_notfound and res == "NOT_FOUND":
        return NOTFOUND  # E.2: no radio matched this question → defaults skip
    print(res)
    return 1


def set_checkbox(label, state="on", quiet_notfound=False):
    want = state != "off"
    res = cfx.evaluate(f"""
    (() => {{
      const w = {_js(label)}.toLowerCase();
      for (const c of document.querySelectorAll('input[type=checkbox]')) {{
        const lbl = (c.labels && c.labels[0]) ? c.labels[0].innerText : '';
        if (lbl.toLowerCase().includes(w)) {{
          if (c.checked !== {str(want).lower()}) c.click();
          return c.checked === {str(want).lower()} ? ('OK checked='+c.checked) : 'CLICK_FAILED';
        }}
      }}
      return 'NOT_FOUND';
    }})()
    """)
    if quiet_notfound and res == "NOT_FOUND":
        return NOTFOUND  # E.2: no checkbox for this label → defaults skip
    print(res)
    return 0 if isinstance(res, str) and res.startswith("OK") else 1


def upload(target, filename):
    sel = cfx.evaluate(f"""
    (() => {{
      const t = {_js(target)};
      let el = document.getElementById(t.replace(/^#/,''));
      if (el && el.type === 'file') return 'input[id="'+el.id+'"]';
      const tl = t.toLowerCase();
      const files = [...document.querySelectorAll('input[type=file]')];
      const labs = [...document.querySelectorAll('label,h1,h2,h3,h4,p,span,div')]
        .filter(e => e.childElementCount<=2 && e.textContent && e.textContent.toLowerCase().includes(tl)
          && e.textContent.replace(/\\s+/g,' ').trim().length < 80);
      for (const lab of labs) {{
        const f = files.find(fi => lab.compareDocumentPosition(fi) & Node.DOCUMENT_POSITION_FOLLOWING);
        if (f && f.id) return 'input[id="'+f.id+'"]';
      }}
      return '';
    }})()
    """)
    if not sel:
        print(f"FAIL upload: no file input for {target!r}")
        return 1
    try:
        cfx.post(f"/tabs/{cfx._tab()}/upload",
                 {"userId": cfx._uid(), "selector": sel, "path": filename})
    except cfx.CfxError as e:
        print(f"FAIL upload: {e}")
        return 1
    # B.3: poll for the attached filename instead of a blind sleep(1.2) — returns as
    # soon as the file input reflects the upload (often sub-second) and is more robust
    # on a slow attach; on timeout returns the last read ('NONE') and FAILs as before.
    want = os.path.basename(filename)
    _read_file = f"(()=>{{const f=document.querySelector({_js(sel)});return f&&f.files[0]?f.files[0].name:'NONE';}})()"
    got = cfx.poll(_read_file,
                   predicate=lambda r: isinstance(r, str) and r != "NONE"
                   and (r == want or r.endswith(want)),
                   timeout=2.5, interval=0.2)
    ok = isinstance(got, str) and (got == want or got.endswith(want))
    print(f"{'OK' if ok else 'FAIL'} upload {target!r}: {got}")
    return 0 if ok else 1


def upload_chooser(trigger, filename):
    """Upload to a CHOOSER-GATED file input — one that only mounts after clicking a
    "Select file from device" button that fires a native OS file-chooser (e.g. CVLibrary),
    which plain `upload()` cannot bind (the <input type=file> is absent until the click).
    Uses the camofox `/uploadViaChooser` endpoint (arms Playwright's filechooser listener,
    clicks `trigger`, sets the file on the chooser — no native dialog). `trigger` = a CSS
    selector for the button/element that opens the chooser; `filename` = relative to /uploads.
    Requires the server.js route (deployed via a camofox container restart)."""
    try:
        cfx.post(f"/tabs/{cfx._tab()}/uploadViaChooser",
                 {"userId": cfx._uid(), "trigger": trigger, "path": filename})
    except cfx.CfxError as e:
        print(f"FAIL upload_chooser {trigger!r}: {e} "
              f"(needs the /uploadViaChooser server.js route + camofox restart)")
        return 1
    print(f"OK upload_chooser via {trigger!r}: set {os.path.basename(filename)}")
    return 0


# ===========================================================================
# React / custom-widget interaction (Amazon-jobs-class SPAs). A DOM `.click()`
# via evaluate() often does NOT fire a React onClick (synthetic-event system),
# so custom dropdowns / radio-cards / step-nav buttons don't respond. The fix:
# evaluate() LOCATES the target by accessible text/role and MARKS it with
# data-cfx-hit; cfx.click_selector('[data-cfx-hit]') then issues a real
# server-side Playwright click (proper mouse events + force fallback) that DOES
# fire React handlers. Works via already-deployed endpoints, so BOTH Claude Code
# and Hermes get it — no server change.
# ===========================================================================

# JS: find the best VISIBLE clickable whose accessible name matches `want`,
# optionally scoped to `scopeSel`. Prefers interactive roles; exact > prefix > includes.
_FIND_CLICKABLE = r"""
function(want, scopeSel){
  const norm = s => (s||'').replace(/\s+/g,' ').trim().toLowerCase();
  const w = norm(want);
  const root = scopeSel ? (document.querySelector(scopeSel) || document) : document;
  const cands = [...root.querySelectorAll(
    'button,a,[role=button],[role=radio],[role=option],[role=menuitemradio],'+
    '[role=checkbox],[role=tab],[role=menuitem],[role=switch],label,input[type=submit]')];
  let best=null, bestScore=-1;
  for (const e of cands){
    if (e.offsetParent===null && e.getClientRects().length===0) continue;   // not visible
    if (e.disabled || e.getAttribute('aria-disabled')==='true') continue;
    const s=norm(e.textContent), al=norm(e.getAttribute('aria-label')), v=norm(e.value);
    let sc=-1;
    if (s===w||al===w||v===w) sc=100;
    else if (s.startsWith(w)||al.startsWith(w)) sc=60 - Math.min(40, s.length*0.05);
    else if (w.length>=3 && (s.includes(w)||al.includes(w))) sc=25 - Math.min(20, s.length*0.03);
    if (sc>bestScore){ best=e; bestScore=sc; }
  }
  return best;
}
"""


def _mark(finder_call):
    """Run a JS expression returning an element (or null); mark it with data-cfx-hit and
    scroll it into view. Returns True if an element was marked."""
    js = ("(()=>{document.querySelectorAll('[data-cfx-hit]')"
          ".forEach(e=>e.removeAttribute('data-cfx-hit'));"
          f"const el=({finder_call});"
          "if(!el)return false;try{el.scrollIntoView({block:'center',inline:'center'});}catch(e){}"
          "el.setAttribute('data-cfx-hit','1');return true;})()")
    try:
        return cfx.evaluate(js) is True
    except cfx.CfxError:
        return False


def rclick(text, scope=None):
    """Click a button/link/radio-card/menu-item/tab by its accessible TEXT via a REAL
    Playwright click (fires React handlers a DOM .click() misses). `scope` = optional CSS
    selector to search within. Returns True on click."""
    finder = f"({_FIND_CLICKABLE})({_js(text)}, {_js(scope) if scope else 'null'})"
    if not _mark(finder):
        return False
    try:
        cfx.click_selector('[data-cfx-hit="1"]')
        return True
    except cfx.CfxError:
        return False


def _rs_focus(selector):
    """JS-focus a react-select's <input> and confirm focus landed. Reliable focus is the
    load-bearing step — click_selector times out / focus doesn't move between comboboxes."""
    return cfx.evaluate(f"(()=>{{const i=document.querySelector({_js(selector)});"
                        f"if(!i)return 'NF';i.scrollIntoView({{block:'center'}});i.focus();"
                        f"return document.activeElement===i?'ok':'no-focus';}})()")


def react_select(selector, option, timeout=6):
    """Pick `option` in a react-select combobox by CSS/#id `selector`. Now a thin wrapper
    over the ONE combobox engine (`combobox_pick`) so it inherits the full interaction ladder
    (mousedown → ArrowDown → trusted click → type) and multi-source menu reads — the old
    ArrowDown/aria-controls-only recipe was blind to Greenhouse "remix" (aria-controls: null).
    Returns 'ok' on success, 'FAIL' otherwise (CLI `combo` only checks == 'ok')."""
    return "ok" if combobox_pick(selector, option) == 0 else "FAIL"


def react_select_type(selector, text, pick_first=True):
    """Type-to-search react-select (e.g. a Location autocomplete): JS-focus, type `text` with
    REAL per-char keystrokes (dispatched input events are ignored by these widgets AND /type
    500s), then — the first suggestion is auto-highlighted after typing — Enter selects it.
    `pick_first=False` just types (leaves the menu open). Returns 'ok' / 'FOCUS_FAIL' / 'NF'."""
    cfx.press("Escape"); time.sleep(0.3)
    if _rs_focus(selector) != "ok":
        return "FOCUS_FAIL"
    time.sleep(0.3)
    for ch in text:
        cfx.press(ch); time.sleep(0.1)
    time.sleep(1.0)
    if pick_first:
        cfx.press("Enter"); time.sleep(0.5)   # first suggestion is already highlighted — no ArrowDown
    return "ok"


def pick_dropdown(label, option, settle=0.9):
    """Open a custom/react-select dropdown by `label` and choose `option`. Now a thin wrapper
    over the ONE combobox engine (`combobox_pick`) — native <select> and every react-select
    variant, via the full interaction ladder. Returns 0 on success."""
    return combobox_pick(label, option)


def pick_radio(question, option):
    """Select `option` in the radio-card/radio group whose question text contains
    `question`. Scopes to the question's container so the right group is hit. Returns 0."""
    finder = f"""(() => {{
      const norm=s=>(s||'').replace(/\\s+/g,' ').trim().toLowerCase();
      const w=norm({_js(question)}), opt=norm({_js(option)});
      const q=[...document.querySelectorAll('legend,label,h3,h4,p,div,span')]
        .find(e=>norm(e.textContent).includes(w) && norm(e.textContent).length < w.length+70);
      const scope=q?(q.closest('fieldset,div,section')||q.parentElement):document;
      const opts=[...scope.querySelectorAll(
        '[role=radio],[role=option],label,button,[class*=option i],[class*=card i],[class*=choice i]')];
      return opts.find(e=>norm(e.textContent)===opt)
          || opts.find(e=>norm(e.textContent).startsWith(opt))
          || opts.find(e=>opt.length>=3 && norm(e.textContent).includes(opt)) || null;
    }})()"""
    if _mark(finder):
        try:
            cfx.click_selector('[data-cfx-hit="1"]')
            print(f"OK pick_radio {question[:24]!r} = {option!r}")
            return 0
        except cfx.CfxError as e:
            print(f"FAIL pick_radio click: {e}")
    print(f"FAIL pick_radio: no {option!r} under {question[:24]!r}")
    return 1


# JS: resolve the CONTROL for a question by aria-labelledby -> aria-label -> <label for>
# -> container heading (covers Amazon-jobs / Workday-class a11y wiring).
_FIND_CONTROL = r"""
function(question){
  const norm=s=>(s||'').replace(/\s+/g,' ').trim().toLowerCase();
  const w=norm(question);
  const match=e=>{const t=norm(e.textContent);return t.includes(w)&&t.length<w.length+60;};
  const esc=s=>(window.CSS&&CSS.escape)?CSS.escape(s):s;
  for (const le of [...document.querySelectorAll('[id]')]){
    if(!match(le))continue;
    const c=document.querySelector('[aria-labelledby~="'+esc(le.id)+'"]');
    if(c) return c;
  }
  let c=[...document.querySelectorAll('input:not([type=hidden]),select,textarea,[role=radiogroup],[role=combobox]')]
        .find(e=>norm(e.getAttribute('aria-label')).includes(w));
  if(c) return c;
  const lab=[...document.querySelectorAll('label')].find(match);
  if(lab&&lab.htmlFor){const e=document.getElementById(lab.htmlFor); if(e)return e;}
  const h=[...document.querySelectorAll('label,legend,h3,h4,span,div,p')].find(match);
  if(h){const sc=h.closest('fieldset,div,section')||h.parentElement;
        if(sc) return sc.querySelector('input:not([type=hidden]),select,textarea,[role=radiogroup],[role=combobox]');}
  return null;
}
"""


def answer(question, value):
    """Answer a form question by its text, auto-detecting the control (radio-group / native
    or react select / text|date) and its a11y wiring. The one call to use for SPA question
    forms — robust for both Claude Code and Hermes. Returns 0 on success."""
    find = f"({_FIND_CONTROL})({_js(question)})"
    kind = cfx.evaluate(f"""(() => {{
      const el=({find}); if(!el) return 'NONE';
      const role=el.getAttribute('role'), tag=el.tagName.toLowerCase();
      if(role==='radiogroup'||el.type==='radio') return 'radio';
      if(tag==='select') return 'select';
      if(role==='combobox'||el.getAttribute('aria-haspopup')) return 'combo';
      return 'text';
    }})()""")
    if not isinstance(kind, str) or kind == 'NONE':
        print(f"FAIL answer: no control for {question[:34]!r}")
        return 1
    if kind == 'text':
        if _mark(find):
            try:
                cfx.post(f"/tabs/{cfx._tab()}/type",
                         {"userId": cfx._uid(), "selector": '[data-cfx-hit="1"]',
                          "text": str(value), "mode": "fill"})
                print(f"OK answer(text) {question[:26]!r}={value!r}")
                return 0
            except cfx.CfxError as e:
                print(f"FAIL answer type: {e}")
        return 1
    if kind == 'select':
        # React-controlled <select>: a plain `el.value=` is IGNORED by React's onChange —
        # must call the prototype value setter + dispatch input+change (proven on amazon.jobs).
        r = cfx.evaluate(f"""(()=>{{const el=({find});if(!el)return false;
          const w={_js(str(value))}.toLowerCase();
          const o=[...el.options].find(o=>o.text.toLowerCase()===w)
               || [...el.options].find(o=>o.text.toLowerCase().includes(w));
          if(!o)return false;
          const nv=Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype,'value').set;
          nv.call(el,o.value);
          el.dispatchEvent(new Event('input',{{bubbles:true}}));
          el.dispatchEvent(new Event('change',{{bubbles:true}}));
          return true;}})()""")
        print(f"{'OK' if r is True else 'FAIL'} answer(select) {question[:26]!r}={value!r}")
        return 0 if r is True else 1
    if kind == 'combo':
        # react-select / custom combobox → the ONE shared ladder engine (mousedown-open,
        # multi-source menu read, type-to-filter). Was a bespoke open+rclick that inherited
        # none of the combobox_pick robustness.
        return combobox_pick(question, str(value))
    # radio-group: scope to the group and click the matching option
    finder = f"""(() => {{
      const norm=s=>(s||'').replace(/\\s+/g,' ').trim().toLowerCase();
      const el=({find}); if(!el) return null;
      const scope=el.closest('fieldset,[role=radiogroup],div,section')||el.parentElement;
      const opt=norm({_js(str(value))});
      const opts=[...scope.querySelectorAll('[role=radio],input[type=radio],[role=option],label,button')];
      return opts.find(e=>norm(e.textContent)===opt)
          || opts.find(e=>norm(e.getAttribute('aria-label'))===opt)
          || opts.find(e=>(e.value||'').toLowerCase()===opt)
          || opts.find(e=>norm(e.textContent).startsWith(opt)) || el;
    }})()"""
    if not _mark(finder):
        print(f"FAIL answer(radio/combo): no {value!r} for {question[:26]!r}")
        return 1
    try:
        cfx.click_selector('[data-cfx-hit="1"]')
    except cfx.CfxError as e:
        print(f"FAIL answer click: {e}")
        return 1
    if kind == 'combo':
        time.sleep(0.8)
        rclick(str(value))
    print(f"OK answer({kind}) {question[:26]!r}={value!r}")
    return 0


def active_step():
    """Name of the current wizard step (highlighted progress-nav item), or ''. Used to
    VERIFY a step actually advanced instead of trusting a possibly-stale screenshot."""
    try:
        r = cfx.evaluate(r"""(()=>{
          const marks=[...document.querySelectorAll('[aria-current],[class*=active i],[class*=current i],[class*=selected i]')];
          const step=marks.find(e=>/contact|sms|general|education|job.?specific|work elig|acknowledg|self.?id|military|review/i.test(e.textContent||'') && e.childElementCount<=3);
          return step?(step.textContent||'').replace(/\s+/g,' ').trim().slice(0,40):'';})()""")
        return r if isinstance(r, str) else ""
    except cfx.CfxError:
        return ""


def advance(verify=True, timeout=9):
    """Click the step-advance control (Save & continue / Continue / Next / Skip) via a real
    Playwright click and VERIFY the wizard moved to a new step (polls active_step). Retries
    once. Returns 0 on a confirmed advance."""
    before = active_step() if verify else None
    for _ in range(2):
        clicked = (rclick("Save & continue") or rclick("Save and continue")
                   or rclick("Continue") or rclick("Next") or rclick("Skip this step")
                   or rclick("Skip"))
        if clicked:
            if not verify:
                return 0
            deadline = time.time() + timeout
            while time.time() < deadline:
                time.sleep(0.6)
                now = active_step()
                if now and now != before:
                    print(f"OK advance: {before!r} -> {now!r}")
                    return 0
        time.sleep(1.0)
    print(f"FAIL advance: still on {before!r}")
    return 1


def click_button(text, timeout_s=6.0, poll_interval=0.4):
    """Click a button by visible text and VERIFY something actually happened —
    do NOT trust the click call's own return value alone. A click can report
    "clicked" while the page does nothing at all (a real multi-hour
    misdiagnosis on LinkedIn was caused by exactly this — see
    sites/linkedin/NOTES.md and cfx.py's click_and_follow docstring). This
    gives every ATS site script the same new_tab / same_tab_nav / no_change
    check for free, instead of each one re-discovering "clicked != something
    happened" independently."""
    before_url = cfx.current_url()
    before_tabs = {t.get("tabId") for t in cfx.list_tabs() if isinstance(t, dict)}
    # Cheap DOM-content fingerprint (not just URL/tabs) -- many ATS multi-step forms
    # (Greenhouse, Lever, etc.) advance a step client-side with NO URL change and NO
    # new tab, so URL/tab-diffing alone would misreport a legitimate "Next" click as
    # NO_CHANGE. A blunt length-of-visible-text signal is enough to catch "the page
    # content actually changed" without needing a real diff.
    before_len = cfx.evaluate("(document.body.innerText||'').length") or 0

    # Tag the matched button so a trusted-click retry can re-target it. Also report
    # whether it's a Workday control (has data-automation-id) — Workday submit/nav
    # buttons NO-OP on this synthetic .click() and need a trusted /click (see
    # sites/myworkdayjobs/NOTES.md); the retry below is gated to that case so other
    # ATSes are untouched.
    res = cfx.evaluate(f"""
    (() => {{
      const w = {_js(text)}.toLowerCase();
      document.querySelectorAll('[data-ats-btn]').forEach(e=>e.removeAttribute('data-ats-btn'));
      const b = [...document.querySelectorAll('button,[role=button],a')].find(x => (x.innerText||'').trim().toLowerCase().includes(w));
      if (!b) return 'NOT_FOUND';
      b.setAttribute('data-ats-btn','1');
      b.scrollIntoView({{block:'center'}}); b.click();
      return b.getAttribute('data-automation-id') ? 'clicked:wd' : 'clicked';
    }})()
    """)
    if res == "NOT_FOUND":
        print("NOT_FOUND")
        return 1

    def _wait_change():
        deadline = time.time() + timeout_s
        while True:
            tabs_now = cfx.list_tabs()
            now_ids = {t.get("tabId") for t in tabs_now if isinstance(t, dict)}
            new_ids = now_ids - before_tabs
            if new_ids:
                new_id = next(iter(new_ids))
                url = next((t.get("url", "") for t in tabs_now
                            if isinstance(t, dict) and t.get("tabId") == new_id), "")
                return f"new_tab {new_id} {url}"
            # B.2: one evaluate returns href AND visible-text length, halving the
            # per-iteration page reads (was current_url() + a separate length evaluate).
            url_now, after_len = _url_len()
            if url_now and url_now != before_url:
                return f"same_tab_nav {url_now}"
            if after_len is not None and abs(after_len - before_len) > 40:  # real step change, not a spinner blip
                return f"same_page_dom_changed (visible text length {before_len} -> {after_len})"
            if time.time() >= deadline:
                return None
            time.sleep(poll_interval)

    outcome = _wait_change()
    # Workday-gated trusted-click retry: the synthetic .click() above no-ops on
    # Workday's pageFooterNextButton/signInSubmitButton, so if nothing changed and the
    # button was a Workday control, click it for real via the /click endpoint and wait
    # once more before declaring it dead.
    if outcome is None and res == "clicked:wd":
        try:
            cfx.click_selector('[data-ats-btn="1"]')
            outcome = _wait_change()
            if outcome:
                print(f"{outcome} (via trusted retry — Workday synthetic-click no-op)")
                return 0
        except cfx.CfxError:
            pass
    if outcome is not None:
        print(outcome)
        return 0
    print(f"NO_CHANGE: clicked {text!r} but nothing detectably changed "
          f"(same URL, no new tab, no meaningful DOM change) after "
          f"{timeout_s}s — do NOT assume success. Verify with `state`/"
          f"`review` before deciding this failed, then treat as a real "
          f"dead click if confirmed (see sites/linkedin/NOTES.md for the "
          f"pattern).")
    return 2


def _tracker_companies():
    """Distinct Company names from application-tracker.csv (best-effort, lowercased),
    so the wrong-company audit isn't limited to a hardcoded grab-bag — every company
    you've previously applied to becomes a name the current letter must not mention."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "..", "..", "..", "application-tracker.csv")
    out = set()
    try:
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                c = (row.get("Company") or "").strip().lower()
                # Skip placeholder/junk company values (blank-title cards etc.) — they
                # aren't real names and would only add noise to the wrong-company audit.
                if c and not c.startswith("(") and "unknown" not in c and len(c) >= 3:
                    out.add(c)
    except (FileNotFoundError, OSError, csv.Error):
        pass
    return out


def review(company, must_haves=None):
    """⚠️ Pre-submit audit. Reads every text/textarea value + selection state and flags:
      - surviving [bracketed] template placeholders,
      - any OTHER company name in free-text (wrong-company cover letter = #1 failure),
      - empty `required` text fields / unselected required radio groups,
      - (optional) JD must-have keywords absent from the free-text answers.
    Prints findings; exit 0 only if clean."""
    must_haves = must_haves or []
    try:
        _raw = cfx.evaluate(r"""
    (() => {
      const out = { texts: [], emptyRequired: [], radioGroups: {} };
      for (const i of document.querySelectorAll('input[type=text],input[type=email],input[type=tel],input[type=url],input[type=number],textarea')) {
        const lbl = ((i.labels&&i.labels[0]?i.labels[0].innerText:'')||i.name||'').replace(/\s+/g,' ').trim().slice(0,50);
        out.texts.push({ label: lbl, value: i.value, required: i.required, long: i.tagName==='TEXTAREA' });
        if (i.required && !i.value.trim()) out.emptyRequired.push('text: ' + lbl);
      }
      const g = {};
      for (const r of document.querySelectorAll('input[type=radio]')) (g[r.name]=g[r.name]||[]).push(r);
      for (const n in g) { const fs=g[n][0].closest('fieldset'); const q=((fs?(fs.querySelector('legend,label')||{}).innerText:n)||'').replace(/\s+/g,' ').trim().slice(0,50);
        out.radioGroups[q] = g[n].some(r=>r.checked); }
      return JSON.stringify(out);
    })()
    """)
        data = json.loads(_raw) if isinstance(_raw, str) else None
    except (cfx.CfxError, ValueError):
        data = None
    # FAIL-CLOSED: a blank/errored read must NEVER pass the pre-submit gate (that would
    # let a submit through un-reviewed) nor traceback on json.loads(None). The old
    # `json.loads(cfx.evaluate(...))` did both. Report clearly and block instead.
    if not isinstance(data, dict) or "texts" not in data:
        print("REVIEW — could NOT read the form state (blank/errored response). Do NOT "
              "submit; re-snapshot the tab, confirm the form loaded, and re-run review.")
        return 1
    findings = []
    freetext = " ".join(t["value"] for t in data["texts"] if t["long"] and t["value"])
    # A wrong company can appear in ANY free-text answer, not only the long ones, so
    # scan every text/textarea value for the wrong-company check.
    all_text_low = " ".join((t["value"] or "") for t in data["texts"]).lower()
    # 1) placeholders
    for t in data["texts"]:
        for m in re.findall(r"\[[A-Za-z][^\]]*\]", t["value"] or ""):
            findings.append(f"PLACEHOLDER {m!r} in {t['label']!r}")
    # 2) wrong company in free-text — a hardcoded seed set UNIONED with every company
    # from the tracker, minus the target (and near-variants of it). Word-boundary
    # match, so "lever" doesn't fire on "clever" / "tilt" on "tilted".
    tgt = company.strip().lower()
    OTHERS = {"loveholidays", "tilt", "ashby", "greenhouse", "workday", "workable", "lever",
              "xelix", "financial times", "closerstill", "experian", "lloyds", "amber labs",
              "welcome to the jungle"} | _tracker_companies()
    for co in sorted(OTHERS):
        if not co or co == tgt or (tgt and (tgt in co or co in tgt)):
            continue  # target itself or a near-variant of it — not "wrong company"
        if re.search(r"\b" + re.escape(co) + r"\b", all_text_low):
            findings.append(f"WRONG-COMPANY mention {co!r} in free-text")
    # 3) company should appear in the cover/why free-text
    if freetext and tgt and tgt not in freetext.lower():
        findings.append(f"target company {company!r} NOT found in free-text answers")
    # 4) empty required
    findings += data["emptyRequired"]
    # unanswered radios, EXCEPT optional demographic/EEO groups (age/gender/etc.),
    # which are legitimately left blank and would otherwise be false-positive noise.
    EEO = re.compile(r"age|gender|transgender|sexual orientation|ethnic|disab|veteran|neurodiver|"
                     r"prefer not|race|nationality|pronoun", re.I)
    for q, answered in data["radioGroups"].items():
        if not answered and not EEO.search(q):
            findings.append(f"unanswered radio: {q}")
    # 5) must-have keywords (checked against all free-text the applicant wrote)
    for kw in must_haves:
        if kw and kw.lower() not in all_text_low:
            findings.append(f"missing JD keyword {kw!r} in free-text")
    if findings:
        print("REVIEW — issues found (fix before submit):")
        for f in findings:
            print("  - " + f)
        return 1
    print(f"REVIEW OK: no placeholders, no wrong-company, {company!r} present, no empty required text.")
    return 0


def submit(button_text="Submit", success_re="successfully submitted|application (received|sent)|thank you|we're rooting"):
    clicked = cfx.evaluate(f"""
    (() => {{
      const w = {_js(button_text)}.toLowerCase();
      const b = [...document.querySelectorAll('button,[type=submit]')].find(x => (x.innerText||x.value||'').trim().toLowerCase().includes(w));
      if (!b) return 'NO_BUTTON';
      b.scrollIntoView({{block:'center'}}); b.click(); return 'clicked';
    }})()
    """)
    if clicked != "clicked":
        print(f"FAIL: no submit button matching {button_text!r}")
        return 2
    # B.3: poll at a fine interval instead of a coarse sleep(3) — the confirmation page
    # (or a validation error) often renders in <1s, so a 3s step wasted up to ~2.5s per
    # submit. Same success/error snapshot JS, same 18s ceiling and UNCLEAR fallthrough.
    _state_js = r"""
        (() => JSON.stringify({
          body: document.body.innerText.slice(0, 4000),
          errors: [...new Set([...document.querySelectorAll('[role=alert],[class*=error i]')]
            .map(e=>e.innerText.replace(/\s+/g,' ').trim()).filter(t=>/missing|required|invalid/i.test(t)))].slice(0,5),
        }))()
    """
    deadline = time.time() + 18
    time.sleep(0.5)  # brief grace so the click's own re-render starts before the first read
    while time.time() < deadline:
        try:
            state = json.loads(cfx.evaluate(_state_js))
        except (cfx.CfxError, ValueError):
            time.sleep(0.7)
            continue
        if re.search(success_re, state["body"], re.I):
            print("SUCCESS: submission confirmed.")
            return 0
        if state["errors"]:
            print("BLOCKED — validation errors:")
            for e in state["errors"]:
                print("  - " + e[:200])
            return 1
        time.sleep(0.7)
    print("UNCLEAR: no success text and no errors after 18s — screenshot to check.")
    return 2


_DEFAULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DEFAULTS_PATH = os.path.join(_DEFAULTS_DIR, "apply-defaults.json")
# The real apply-defaults.json holds YOUR contact/answers and is gitignored; a fresh
# clone ships only apply-defaults.example.json. Fall back to it so defaults still work
# (with placeholder values) until you `cp apply-defaults.example.json apply-defaults.json`.
DEFAULTS_EXAMPLE_PATH = os.path.join(_DEFAULTS_DIR, "apply-defaults.example.json")
# (_field_exists removed — E.2 gave every primitive a `quiet_notfound` NOTFOUND sentinel,
#  so the defaults path no longer pre-probes then re-resolves; nothing called it.)


def _load_defaults(spec):
    """spec: true -> the bundled apply-defaults.json (or its .example fallback); a
    string -> that path."""
    path = spec if isinstance(spec, str) else DEFAULTS_PATH
    if not isinstance(spec, str) and not os.path.exists(path) and os.path.exists(DEFAULTS_EXAMPLE_PATH):
        path = DEFAULTS_EXAMPLE_PATH
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return {k: v for k, v in d.items() if not k.startswith("_")} if isinstance(d, dict) else {}
    except (OSError, ValueError) as e:
        print(f"WARN defaults: cannot read {path!r}: {e} — continuing without defaults")
        return {}


def _default_entries(defaults, section, cfg_section):
    """Yield (label, value) defaults for `section`, minus any that overlap an
    explicit config key (case-insensitive substring either way — a config 'Name'
    must suppress the 'First name'/'Last name'/'Full name' defaults)."""
    cfg_keys = [k.lower() for k in (cfg_section or {})]
    for label, value in (defaults.get(section) or {}).items():
        low = label.lower()
        if any(low in ck or ck in low for ck in cfg_keys):
            continue
        yield label, value


def apply(config_path, do_submit=False):
    """Fill a whole ATS form from a JSON config in ONE process — the speed path.

    WHY: driving a form field-by-field costs one MODEL TURN per field (the
    dominant latency on a slow endpoint) plus, on the CLI path, a fresh
    `python3` startup and a bash+curl+python fork per field. Running the whole
    form here is one turn, one interpreter, and in-process HTTP via cfx.post()
    (no forks). See the module docstring for the config schema.

    Runs in the autofill-safe order (uploads first — an ATS résumé upload often
    triggers an autofill re-render that would reset fields set before it), and
    deliberately KEEPS GOING past a failed field so one bad selector doesn't hide
    the rest — every problem comes back in a single summary, so the agent fixes
    them in one more turn instead of rediscovering them one at a time. Submits
    only when asked AND the pre-submit review is clean. Returns 0 iff every step
    passed (and review, if requested, found nothing)."""
    try:
        with open(config_path, encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError) as e:
        print(f"FAIL apply: cannot read config {config_path!r}: {e}")
        return 2
    if not isinstance(cfg, dict):
        print(f"FAIL apply: config must be a JSON object, got {type(cfg).__name__}")
        return 2

    import contextlib
    import io as _io
    results = []  # (human label, rc, captured_output) for the final summary
    n_default_skips = 0

    def _run(label, fn, *fn_args, **fn_kwargs):
        # E.1: capture the primitive's own stdout so the ALL-OK path can suppress the
        # ~15-25 "OK fill …" lines (re-read by every later model turn); failures are
        # replayed verbatim in the summary so the KEEP-GOING detail is never lost.
        buf = _io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                rc = fn(*fn_args, **fn_kwargs)
        except cfx.CfxError as e:
            buf.write(f"FAIL {label}: {e}\n")
            rc = 1
        results.append((label, rc, buf.getvalue()))
        return rc

    defaults = _load_defaults(cfg["defaults"]) if cfg.get("defaults") else {}

    def _run_defaults(section, kind, fn, coerce=lambda v: (v,)):
        nonlocal n_default_skips
        for label, value in _default_entries(defaults, section, cfg.get(section)):
            # E.2: every primitive now supports quiet_notfound, so there's no separate
            # _field_exists pre-probe (which re-resolved the same label). A default
            # missing from THIS form returns the NOTFOUND sentinel → silent skip; a
            # present field runs normally. One resolve per default instead of two/three.
            buf = _io.StringIO()
            try:
                with contextlib.redirect_stdout(buf):
                    rc = fn(label, *coerce(value), quiet_notfound=True)
            except cfx.CfxError as e:
                buf.write(f"FAIL {kind} {label!r} (default): {e}\n")
                rc = 1
            if rc == NOTFOUND:
                n_default_skips += 1
            else:
                results.append((f"{kind} {label!r} (default)", rc, buf.getvalue()))

    # 1) uploads first (may trigger an autofill re-render), then settle
    for target, filename in (cfg.get("upload") or {}).items():
        _run(f"upload {target!r}", upload, target, filename)
    if cfg.get("upload"):
        time.sleep(1.0)
    # 2) text, 3) selects, 4) radios, 5) checkboxes — defaults first within each
    # phase (optional facts), then the config's own entries (explicit, always win
    # on overlap because overlapping defaults were already suppressed).
    _run_defaults("fill", "fill", fill)
    for label, val in (cfg.get("fill") or {}).items():
        _run(f"fill {label!r}", fill, label, val)
    _run_defaults("select", "select", select)
    for label, opt in (cfg.get("select") or {}).items():
        _run(f"select {label!r}", select, label, opt)
    _run_defaults("radios", "radio", set_radio)
    for question, opt in (cfg.get("radios") or {}).items():
        _run(f"radio {question!r}", set_radio, question, opt)
    _run_defaults("checkboxes", "checkbox", set_checkbox,
                  coerce=lambda v: (v if isinstance(v, str) else ("on" if v else "off"),))
    for label, st in (cfg.get("checkboxes") or {}).items():
        state = st if isinstance(st, str) else ("on" if st else "off")
        _run(f"checkbox {label!r}", set_checkbox, label, state)
    if defaults and n_default_skips:
        print(f"defaults: {n_default_skips} entr{'y' if n_default_skips == 1 else 'ies'} "
              f"skipped (no matching field on this form) — expected, not an error")

    review_rc = 0
    if cfg.get("review"):
        print("--- pre-submit review ---")
        review_rc = review(cfg["review"], cfg.get("must_haves") or [])

    n_failed = sum(1 for _l, rc, _o in results if rc != 0)
    # Speed lever #4 (shrink context per turn): on the ALL-OK path, don't enumerate
    # every passing field — that summary is re-read by every later model turn, and a
    # big form with merged defaults is 15-25 lines of pure "OK". Collapse it to one
    # count line (E.1 also suppresses the primitives' own per-field OK chatter, which
    # used to print during the run regardless). When ANYTHING failed (or review
    # flagged), replay each FAILED field's captured detail verbatim so the model fixes
    # every issue in one more turn; passing fields stay a terse one-liner.
    print("---- apply summary ----")
    if n_failed or review_rc != 0:
        for label, rc, out in results:
            if rc != 0:
                det = (out or "").strip()
                print(det if det else f"  FAIL {label}")
            else:
                print(f"  OK   {label}")
        if cfg.get("review"):
            print(f"  {'OK  ' if review_rc == 0 else 'FAIL'} review {cfg['review']!r}")
    else:
        # (the default-skip count is already reported on its own line above)
        note = f"  OK   {len(results)} field(s) filled"
        if cfg.get("review"):
            note += f"; review {cfg['review']!r} clean"
        print(note)
    if n_failed or review_rc != 0:
        print(f"apply: {n_failed} field(s) failed"
              + (" + review flagged issues" if review_rc != 0 else "")
              + " — fix before submit.")
        return 1

    # Submit only when explicitly asked AND everything above is clean.
    sub = cfg.get("submit")
    if do_submit or sub:
        sub = sub or {}
        return submit(sub.get("button", "Submit"),
                      sub.get("success") or
                      "successfully submitted|application (received|sent)|thank you|we're rooting")
    print("apply: all fields OK and review clean — not submitting (pass --submit or a "
          "\"submit\" config block to submit).")
    return 0


def main():
    a = sys.argv[1:]
    if not a:
        print(__doc__)
        return 1
    cmd = a[0]
    try:
        if cmd == "fill" and len(a) == 3:      return fill(a[1], a[2])
        if cmd == "select" and len(a) == 3:    return select(a[1], a[2])
        if cmd == "combo" and len(a) == 3:
            r = react_select(a[1], a[2]); print(f"combo {a[1]!r} -> {a[2]!r}: {r}"); return 0 if r == "ok" else 1
        if cmd == "combo-type" and len(a) == 3:
            r = react_select_type(a[1], a[2]); print(f"combo-type {a[1]!r} -> {a[2]!r}: {r}"); return 0 if r == "ok" else 1
        if cmd == "pick" and len(a) >= 3:
            # pick "<label|css/#id>" "<option>" [--multi] [--clear] — the universal driver
            # (native <select> + every react-select variant via the interaction ladder).
            # --multi = mark-all-that-apply (adds); --clear = remove existing chips first.
            return combobox_pick(a[1], a[2], multi="--multi" in a, clear_first="--clear" in a)
        if cmd == "radio" and len(a) == 3:     return set_radio(a[1], a[2])
        if cmd == "checkbox" and len(a) in (2, 3): return set_checkbox(a[1], a[2] if len(a) == 3 else "on")
        if cmd == "upload" and len(a) == 3:    return upload(a[1], a[2])
        if cmd == "click" and len(a) == 2:     return click_button(a[1])
        if cmd == "review" and len(a) in (2, 3): return review(a[1], (a[2].split(",") if len(a) == 3 else []))
        if cmd == "submit":                    return submit(*(a[1:3] if len(a) > 1 else []))
        if cmd == "apply" and len(a) in (2, 3):
            with stagetimer.timed("fill", meta=a[1]):
                return apply(a[1], do_submit=(len(a) == 3 and a[2] == "--submit"))
    except cfx.CfxError as e:
        print(f"ERROR: {e}")
        return 2
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
