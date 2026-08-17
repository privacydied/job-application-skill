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

═══ TWO RULES THIS FILE KEEPS RE-LEARNING (read before touching a matcher) ═══

**1. A label walk must climb PAST the control's own rendering.**
Every "find this field's question" walk takes the nearest ancestor with text. That
ancestor is usually the control itself, because controls render their own text:
an empty react-select shows "Select...", a radio group shows its option labels, a
chosen option shows itself. Taking it yields a question that matches nothing.

This has now been fixed THREE times, in three branches, one at a time — because each
fix was applied only where the symptom was seen:
    set_radio qtext      returned the OPTIONS container ("Yes No Prefer not to say")
    _UNANSWERED texts    returned a multi-question ancestor blob
    _UNANSWERED combos   returned the placeholder "Select..." — which meant the answer
                         bank could never answer a Greenhouse dropdown at all
                         (measured live: "0 answered, 7 unknown" on a form where all
                         seven answers were banked)
If you fix this again, fix it in EVERY walk in the file, not just the one in front of you.

**2. A matcher must never commit an option that carries a claim the applicant did not make.**
Scorers optimise for "closest string", which is not the same as "same claim". Every
false answer this repo has shipped is one of these:
    "Mixed or Multiple ethnic groups" -> "Mixed – White and Asian"   (narrower ancestry)
    "Man"                             -> "Woman"                     (substring)
    "relocation assistance -> No"     -> a question asking the INVERSE (negation)
    "Job board"                       -> "University job board"      (affiliation)
    "sponsorship -> No"               -> "able to work WITHOUT sponsorship?" (negation)
When the best match is not equivalent, REFUSE. An unanswered required field blocks the
submit and asks for a human, which is recoverable; a confidently wrong answer is submitted
under the applicant's name and is not.

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
import precheck  # noqa: E402  (apply-time dedup guard; no cycle — precheck doesn't import atsform)


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
    const viaFs = fs ? ((fs.querySelector('label,legend') || fs).innerText || '') : '';
    if (viaFs.trim()) return viaFs;
    // ⛔ LABEL-LESS FIELDS (2026-08-15). Lever renders every CUSTOM question as
    // `cards[<uuid>][fieldN]` with NO <label> element at all — the question text sits in an
    // ancestor. `closest('fieldset,label,div')` often lands on a bare wrapper whose innerText
    // is empty, so labelText returned '' and _resolve SKIPPED the field entirely (`if (!lab)
    // continue`). Net effect: fill_gaps_from_bank could SEE those questions (it climbs
    // ancestors) and had answers for them, but fill() could never bind one — the bank
    // reported "0 answered" on a form where it knew every answer. Climb until real text
    // appears, exactly like the _UNANSWERED walk, so the two agree on what a field is called.
    // ⛔ THE ANCESTOR MUST DESCRIBE THIS FIELD ALONE (2026-08-16). The climb used to accept
    // the first ancestor with any text under 400 chars, with nothing tying that text to THIS
    // control. When two label-less siblings share a text-bearing wrapper — the documented
    // Lever `cards[<uuid>][fieldN]` shape, e.g. "Why do you want to work here?" and "Describe
    // a project you're proud of" in one card — BOTH normalised to the same wrapper blob, both
    // landed in the same match tier, and `sel(tier[0])` returned the FIRST for both. Filling
    // the second question therefore OVERWROTE the first question's answer in field #1, and
    // the round-trip read matched what was just typed so it printed OK: one question answered
    // with the other's text, the other left empty. An ancestor whose subtree holds more than
    // one fillable control is describing a GROUP, not this field — keep climbing past it, and
    // if nothing qualifies, resolve to nothing so the caller skips rather than guesses.
    const fillable = 'input:not([type=hidden]):not([type=submit]):not([type=button])'
                   + ':not([type=reset]):not([type=image]),textarea,select';
    // ⛔ PREFER a single-control ancestor, but do NOT return nothing (regression fixed
    // 2026-08-16, same day). Returning '' when no ancestor holds exactly one control traded
    // "bind the wrong field" for "bind NO field", and the commonest layout in existence —
    // First Name and Last Name side by side in one row — is exactly that shape. Live cost on
    // Proton: "defaults: 9 entries skipped (no matching field on this form)" while the form
    // was simultaneously refusing to submit for want of First Name and Last Name.
    // Keep the preference (it is what stops one Lever card's two textareas colliding), but
    // fall back to the nearest text-bearing ancestor rather than giving up entirely.
    let b = el, fallback = '';
    for (let k = 0; k < 5 && b; k++) {
      b = b.parentElement;
      if (!b) break;
      const t = (b.innerText || '').trim();
      if (!t || t.length >= 400) continue;   // empty, or so large it's the whole form
      if (!fallback) fallback = t;           // remember the first usable ancestor
      if (b.querySelectorAll(fillable).length > 1) continue;  // describes a group, not this one
      return t;                              // precise: this ancestor describes ONE control
    }
    if (fallback) return fallback;
    // LAST resort only. A placeholder is frequently generic filler — Lever's card inputs all
    // say "Type your response" — so preferring it over the ancestor text would make every
    // custom question on the form resolve to the SAME meaningless string.
    return el.getAttribute('placeholder') || '';
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

# Returned when a primitive REFUSES to answer an anti-AI / "own words" attestation
# affirmatively (see combobox_pick's ANTI-AI OATH GUARD). Distinct from a plain failure (1):
# nothing is broken and retrying cannot help — the posting simply requires the applicant's own
# words, so the caller should route it to the human queue rather than treat it as a form bug.
ANTI_AI = "__ATSFORM_ANTI_AI_ATTESTATION__"

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


# React-commit fallback: set a controlled input's value via the element's NATIVE setter
# (bypassing React's overridden `.value`) + dispatch input/change so React's onChange picks
# it up. Some ATSes (Monzo) have inputs whose onChange resets a plain /type value-set so it
# reads back EMPTY; this is the commit path that sticks. __SEL__/__VAL__ are _js()-quoted.
_REACT_SET = r"""
(() => {
  const el = document.querySelector(__SEL__);
  if (!el) return 'NO_EL';
  const proto = el.tagName === 'TEXTAREA' ? window.HTMLTextAreaElement.prototype
                                          : window.HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, __VAL__);
  el.focus();
  el.dispatchEvent(new Event('input', {bubbles:true}));
  el.dispatchEvent(new Event('change', {bubbles:true}));
  return 'SET';
})()
"""


def fill(label, value, quiet_notfound=False):
    # A non-str config value (e.g. a JSON number like a notice period) would crash the
    # `.startswith("@")` check below with an AttributeError — and _run/main() only catch
    # cfx.CfxError, so it would escape as a raw traceback and abort the whole batch fill.
    # Coerce first, exactly as the checkbox/default paths already do.
    if not isinstance(value, str):
        value = str(value)
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
    # A CSS selector may be passed instead of a label — `combobox_pick` has always accepted
    # one, and `fill_gaps_from_bank` needs it to address a SPECIFIC element when two fields
    # share a label (see the data-ats-gap note in _UNANSWERED).
    if re.match(r"^[#.\[]", label.strip()):
        sel = label.strip()
        try:
            if not cfx.evaluate(f"!!document.querySelector({_js(sel)})"):
                return NOTFOUND if quiet_notfound else 1
        except cfx.CfxError:
            return NOTFOUND if quiet_notfound else 1
    else:
        sel = _resolve(label)
    if not sel:
        if quiet_notfound:      # E.2: defaults path skips a missing field silently
            return NOTFOUND
        print(f"FAIL fill: no text field for label ~{label!r}")
        return 1
    _read = f"(()=>{{const e=document.querySelector({_js(sel)});return e?e.value:null;}})()"
    # ⛔ NUMBER-INPUT SANITISE (2026-08-15). Some employer forms render Phone as
    # `input[type=number]` (Accurx's Ashby form does). A number input silently REFUSES any
    # character it can't hold, and camofox's /type endpoint doesn't degrade — it returns
    # **HTTP 500**, which `fill` reported as `FAIL fill: … HTTP 500` and the orchestrator
    # escalated to `ABORT --submit`. So a `+44 …` phone number didn't just miss one optional
    # field, it blocked the whole application. Strip to what the widget can actually accept
    # (digits, with a leading `+` dropped since number inputs reject it) BEFORE typing; the
    # existing alnum() round-trip check then still validates what landed.
    try:
        _itype = cfx.evaluate(
            f"(()=>{{const e=document.querySelector({_js(sel)});return e?(e.type||''):'';}})()")
    except cfx.CfxError:
        _itype = ""
    if isinstance(_itype, str) and _itype.lower() == "number" and re.search(r"[^0-9.]", value):
        cleaned = re.sub(r"[^0-9]", "", value)
        if cleaned:
            print(f"NOTE fill {label!r}: input[type=number] cannot hold "
                  f"{value.strip()[:4]!r}… — typing digits only ({len(cleaned)} chars)")
            value = cleaned

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
        # ⛔ A 500 FROM /type IS NOT THE END OF THE ROAD (2026-08-16). This used to return 1
        # immediately — even though the native-value-setter fallback below (_REACT_SET) was
        # sitting right there, reachable only when /type SUCCEEDED but the value failed to
        # stick. So the engine gave up in exactly the case where it still had a working move.
        # SAP SuccessFactors exposed it: its field ids contain COLONS ("385:_txtFld"), and the
        # /type endpoint 500s on them, so six of nine fields failed and the whole GLA
        # application aborted at the CV step with everything blank. The setter path does not
        # care about the endpoint and filled them all. Try it before failing.
        print(f"  fill {label!r}: /type failed ({str(e)[:60]}) — trying the native setter")
        try:
            cfx.evaluate(_REACT_SET.replace("__SEL__", _js(sel)).replace("__VAL__", _js(value)))
            got0 = cfx.poll(_read, predicate=lambda r: isinstance(r, str) and (
                r.strip() == value.strip() or (bool(alnum(value)) and alnum(r) == alnum(value))),
                timeout=1.2, interval=0.1)
            if isinstance(got0, str) and (got0.strip() == value.strip()
                                          or (bool(alnum(value)) and alnum(got0) == alnum(value))):
                print(f"OK fill {label!r} via native setter ({len(value)} chars)")
                return 0
        except cfx.CfxError:
            pass
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
    if not ok:
        # /type didn't stick (controlled-React input, e.g. Monzo reads back empty) — commit
        # via the native value setter + input/change and re-read. This is what turned an
        # "OK but empty" MISMATCH into a real fill on Monzo's candidate-location/question_* fields.
        try:
            cfx.evaluate(_REACT_SET.replace("__SEL__", _js(sel)).replace("__VAL__", _js(value)))
            got2 = cfx.poll(_read, predicate=lambda r: isinstance(r, str) and (
                r.strip() == value.strip() or (bool(alnum(value)) and alnum(r) == alnum(value))),
                timeout=1.0, interval=0.1)
            if isinstance(got2, str):
                got_s = got2
                exact = got_s.strip() == value.strip()
                ok = exact or (bool(alnum(value)) and alnum(got_s) == alnum(value))
        except cfx.CfxError:
            pass
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
#
# ⛔ DO NOT FORK THIS ENGINE PER BOARD. If a board's react-select won't bind, EXTEND the ladder
# HERE — never grow a board-local combobox (find combobox input + iterate the option menu) in a
# sites/<board>/ file. That is the exact duplicate-infra drift AGENTS.md bans and that cost a
# re-solve on 2026-07-24 (the ashby `combobox_commit` fork, since collapsed to a delegation).
# Board adapters DELEGATE: `combobox_commit = ...combobox_pick`, `set_checkbox = atsform.set_checkbox`.
# Enforced by a guard test: tests/test_core.py::TestNoDivergentFormWidgets fails the build if the
# react-select PICK engine (combobox input + option-menu iteration) appears outside this module.
# ═══════════════════════════════════════════════════════════════════════════

# Printed on every combobox failure so the NEXT agent's nose points at the right file — extend
# the ladder above, don't reinvent it downstream.
_EXTEND_HINT = ("  → extend the ladder in atsform.combobox_pick; do NOT fork a per-board "
                "react-select engine (guard: tests/test_core.py::TestNoDivergentFormWidgets)")

_COMBO_READ_OPTS = r"""
(() => {
  const inp = document.querySelector('[data-ats-target]');
  if (!inp) return '[]';
  // SCOPE to THIS field's own listbox via aria-controls — never the first .select__menu or a
  // global [role=option] scan, which catches OTHER react-selects' still-rendered menus (e.g. a
  // country-dialing list bleeding into a sexual-orientation pick). Verified live 2026-07-21:
  // an opened Greenhouse combobox exposes aria-controls="react-select-<id>-listbox" populated
  // with exactly its own options; the global [role=option] pool is 25x larger and wrong.
  const ac = inp.getAttribute('aria-controls');
  const box = ac && document.getElementById(ac);
  let els = box ? [...box.querySelectorAll('[role=option],[class*="option"]')] : [];
  if (!els.length) { const m = inp.closest('[class*="control"]'); if (m) { const mm = m.querySelector('[class*="menu"]'); if (mm) els = [...mm.querySelectorAll('[class*="option"],[role=option]')]; } }
  if (!els.length) { const pm = inp.parentElement && inp.parentElement.querySelector('[class*="menu"]'); if (pm) els = [...pm.querySelectorAll('[class*="option"],[role=option]')]; }
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
  if (!inp) return 'NO_INPUT';
  // SCOPE to THIS field's own listbox (aria-controls) — never the global [role=option] pool,
  // which bleeds other react-selects' menus (e.g. country dialing) into the match.
  const ac = inp.getAttribute('aria-controls');
  const box = ac && document.getElementById(ac);
  let els = box ? [...box.querySelectorAll('[role=option],[class*="option"]')] : [];
  if (!els.length) { const m = inp.closest('[class*="control"]'); if (m) { const mm = m.querySelector('[class*="menu"]'); if (mm) els = [...mm.querySelectorAll('[class*="option"],[role=option]')]; } }
  if (!els.length) { const pm = inp.parentElement && inp.parentElement.querySelector('[class*="menu"]'); if (pm) els = [...pm.querySelectorAll('[class*="option"],[role=option]')]; }
  const norm = e => (e.textContent||'').replace(/\s+/g,' ').trim().toLowerCase();
  // exact first; else SCORE word-boundary matches (never mid-word, so "No" can't match
  // "Monaco") and pick the BEST: target at the start followed by a separator/end scores
  // highest — so "London" picks "London, UK", NOT "London Colney, Hertfordshire" — with
  // shorter options winning ties; the reverse scan breaks remaining ties toward a real
  // appended option over a prefixed country-list entry.
  const esc = t.replace(/[-/\\^$*+?.()|[\]{}]/g, '\\$&');
  const wb = new RegExp('(^|[^a-z0-9])' + esc + '([^a-z0-9]|$)');
  let o = els.find(e => norm(e) === t), best = -1, nmatch = 0;
  if (!o) for (let ix = els.length - 1; ix >= 0; ix--) {
    const s = norm(els[ix]); if (!wb.test(s)) continue;
    nmatch++;
    let sc = 0;
    if (s.startsWith(t)) sc += 4;
    const after = s.charAt(s.indexOf(t) + t.length);
    if (after === '' || /[,)\-–—|/]/.test(after)) sc += 3;   // target is the leading place / whole value
    sc += Math.max(0, 3 - Math.floor(s.length / 25));         // shorter is better
    // HOME-COUNTRY tiebreaker (applicant is UK/London-based — applicant-profile.md): when several
    // options share the city name ("London, UK" vs "London, Ontario, Canada"), strongly prefer the
    // UK one so a location autocomplete never lands the applicant in the wrong country.
    if (/(^|[^a-z])(uk|gb|united kingdom|great britain|england|scotland|wales|northern ireland)([^a-z]|$)/.test(s)) sc += 6;
    if (sc > best) { best = sc; o = els[ix]; }
  }
  // ⛔ DO NOT STRIP THE MARKER BEFORE THE FAILURE RETURN (2026-08-16). This cleanup used to sit
  // ABOVE the `if (!o)` line, so it ran on the failure path too. The free-text fallback in
  // _combo_open_and_pick runs ONLY after this returns NO_OPTION — i.e. only ever after the
  // marker had already been deleted — so _COMBO_FREETEXT_COMMIT never found its target and
  // fell through to an unscoped `querySelector('input[role=combobox]')`, writing the value
  // into whatever combobox happened to be FIRST in the document (typically the react-phone
  // country selector at the top of the form) and reporting OK. The intended field stayed
  // empty while an unrelated field carried a value the applicant never gave. Strip only on
  // the success path; the caller clears the marker on failure.
  if (!o) return 'NO_OPTION:'+els.map(e=>(e.textContent||'').replace(/\s+/g,' ').trim()).slice(0,10).join(' | ');
  // ⛔ STRICT MODE: A BROAD CATEGORY MUST NOT RESOLVE TO A NARROWER SIBLING (2026-08-16).
  // fill_eeo falls back to the LEADING TOKEN of the profile's value when the full phrasing
  // finds nothing ("Mixed or Multiple ethnic groups" -> "Mixed"). That is safe only when the
  // form lists the broad census category as ONE option. When the form instead lists the
  // sub-categories separately — "Mixed – White and Black Caribbean", "Mixed – White and
  // Asian", … — every one of them matches the token, and the scorer's shorter-is-better
  // bonus simply crowns the shortest. The applicant would be recorded as making a SPECIFIC
  // ancestry claim he never made. When more than one option matches and none matched
  // exactly, refuse: an unanswered EEO field bounces the submit and becomes a human
  // decision, which is the correct outcome for a demographic question.
  if (__STRICT__ && nmatch > 1) return 'AMBIGUOUS:'+els.filter(e=>wb.test(norm(e))).map(e=>(e.textContent||'').replace(/\s+/g,' ').trim()).slice(0,6).join(' | ');
  document.querySelectorAll('[data-ats-target]').forEach(e=>e.removeAttribute('data-ats-target'));
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
  // ⛔ RADIO-GROUP GUARD (2026-08-15) — see the Python-side note on combobox_pick.
  // The old bare `input` fallback matched input[type=radio]/[type=checkbox], so an Ashby
  // RADIO GROUP resolved as kind:'combo'; the ladder's trusted click on [data-ats-target]
  // then SELECTED THE FIRST OPTION and the free-text fallback reported OK. Result: false
  // demographic answers (Transgender=Yes, Orientation=Bi) on a real submission.
  // A radio/checkbox group is NOT a combobox — say so, and let the caller use set_radio.
  if (el.tagName === 'INPUT' && /^(radio|checkbox)$/i.test(el.type||''))
    return JSON.stringify({kind:'none', reason:'radio-group'});
  if (el.tagName !== 'INPUT') {
    const typed = el.querySelector('input[role=combobox],input[class*="select__input"]');
    // ⛔ A WRAPPER AROUND A NATIVE <select> IS A NATIVE SELECT (2026-08-16). The check above
    // tests only `el.tagName === 'SELECT'`, but _FIND_CONTROL's aria-labelledby branch
    // returns CONTAINERS, so a plain <select> wrapped in a div fell through to the combobox
    // ladder — and with no input inside, `inp = el` marked a DIV as the target. The ladder
    // then found no options and (before today's fix) free-texted the value elsewhere.
    if (!typed) { const ns = el.querySelector('select');
      if (ns) { ns.setAttribute('data-ats-native','1');
        const c = ns.options[ns.selectedIndex];
        return JSON.stringify({kind:'native', current:(c && c.value!=='')?[norm(c.text)]:[]}); } }
    // ⛔ THE RADIO-GROUP GUARD MUST NOT FAIL OPEN (2026-08-16). It used to require that the
    // container hold NO usable input (`!typed && !bare`) before declaring a radio group. But
    // `bare` accepts ANY non-choice input — so a radiogroup that also carries an
    // "Other (please specify)" free-text box, which is exactly how self-describe EEO
    // questions are rendered, satisfied `bare` and resolved as kind:'combo' with the marker
    // on that text box. The answer was then deposited into the free-text box (or, before
    // today's free-text fix, into an unrelated field) and reported OK, while the actual radio
    // group stayed unanswered. Presence of radios/checkboxes and no react-select input is
    // decisive on its own: it is a choice group, and set_radio is the right primitive.
    if (!typed && el.querySelector('input[type=radio],input[type=checkbox]'))
      return JSON.stringify({kind:'none', reason:'radio-group'});
    const bare = [...el.querySelectorAll('input')].find(
      i => !/^(radio|checkbox|file|hidden|submit|button|reset|image)$/i.test(i.type||''));
    inp = typed || bare || el;
  }
  if (inp.tagName === 'INPUT' && /^(radio|checkbox)$/i.test(inp.type||''))
    return JSON.stringify({kind:'none', reason:'radio-group'});
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


def _combo_clear_input():
    """Empty the focused combobox's search input before re-typing a shorter prefix.
    Without this the retry APPENDS to the existing text and filters even harder — the
    opposite of what the prefix retry is for. Uses the React native setter so react-select
    actually registers the change, then a Backspace as a belt-and-braces nudge."""
    try:
        cfx.evaluate("""
        (function(){
          var t=document.querySelector('[data-ats-target]');
          var cb=(t&&t.tagName==='INPUT')?t:(t?t.querySelector('input'):null);
          if(!cb) return 'NO_INPUT';
          cb.focus();
          var set=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
          set.call(cb,'');
          cb.dispatchEvent(new Event('input',{bubbles:true}));
          return 'CLEARED';
        })()""")
    except cfx.CfxError:
        pass
    time.sleep(0.25)


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


_COMBO_FREETEXT_COMMIT = r"""
(function(){
  var t=document.querySelector('[data-ats-target]');
  // ⛔ NO UNSCOPED FALLBACK (2026-08-16). This used to end with
  //   if(!cb) cb=document.querySelector('input[role=combobox],input[aria-autocomplete=list]');
  // i.e. "if I can't find the field I was asked to fill, fill the first combobox on the page."
  // That is never the right answer: a write into an unidentified field is how a location string
  // ends up in a phone-country selector, or a Right-to-Work select, and it returned OK so the
  // caller recorded the field as answered. Refuse instead — a NO_TARGET here surfaces as a
  // failed pick, which the run already knows how to handle.
  var cb=(t&&t.tagName==='INPUT')?t:(t?t.querySelector('input'):null);
  if(!cb) return t?'NO_INPUT':'NO_TARGET';
  cb.focus();
  var set=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
  set.call(cb, __VAL__);
  cb.dispatchEvent(new Event('input',{bubbles:true}));
  cb.dispatchEvent(new Event('change',{bubbles:true}));
  cb.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',keyCode:13,bubbles:true}));
  cb.dispatchEvent(new KeyboardEvent('keyup',{key:'Enter',keyCode:13,bubbles:true}));
  cb.dispatchEvent(new Event('blur',{bubbles:true}));
  return (cb.value||'').trim() ? 'OK:'+cb.value.slice(0,40) : 'EMPTY';
})()
"""


def _combo_clear_marker():
    """Drop the resolver's [data-ats-target] tag. _COMBO_CLICK strips it only when it actually
    clicked an option, so every path that gives up has to clear it here — otherwise a stale
    marker from a FAILED pick is still on the page when the next pick runs, and that next pick
    would resolve to the previous field."""
    try:
        cfx.evaluate("(()=>{document.querySelectorAll('[data-ats-target]')"
                     ".forEach(e=>e.removeAttribute('data-ats-target'));return 1})()")
    except Exception:  # noqa: BLE001 — best-effort cleanup; never fail a pick over it
        pass



def _combo_click_option(option):
    """Open the marked (input-less) control and click the matching [role=option].

    Returns the clicked option's text, or None. Exact match first, then whole-word — never a
    bare substring, because "male" is inside "Female" (the defect that put a false gender on a
    live diversity form earlier today)."""
    try:
        cfx.click_selector('[data-ats-target]', timeout=8)
    except Exception:  # noqa: BLE001
        cfx.evaluate("(()=>{const t=document.querySelector('[data-ats-target]');"
                     "if(t)t.click();return 1})()")
    time.sleep(1.6)
    hit = cfx.evaluate("""(()=>{const want=%s.toLowerCase();
      const norm=x=>(x.innerText||'').replace(/\\s+/g,' ').trim().toLowerCase();
      const os=[...document.querySelectorAll('[role=option]')];
      if(!os.length) return '';
      let o=os.find(x=>norm(x)===want);
      if(!o){const esc=want.replace(/[.*+?^${}()|[\\]\\\\]/g,'\\\\$&');
             const re=new RegExp('(^|[^a-z0-9])'+esc+'([^a-z0-9]|$)');
             o=os.find(x=>re.test(norm(x)));}
      if(!o) return '';
      o.setAttribute('data-ats-opt','1'); o.scrollIntoView({block:'center'});
      return (o.innerText||'').trim().slice(0,40);})()""" % _js(str(option)))
    if not hit:
        return None
    try:
        cfx.click_selector('[data-ats-opt]', timeout=8)
    except Exception:  # noqa: BLE001
        cfx.evaluate("(()=>{const o=document.querySelector('[data-ats-opt]');"
                     "if(o)o.click();return 1})()")
    time.sleep(0.7)
    cfx.evaluate("(()=>{document.querySelectorAll('[data-ats-opt]')"
                 ".forEach(e=>e.removeAttribute('data-ats-opt'));return 1})()")
    return hit


def _combo_open_and_pick(option, multi=False, strict=False, resolve_js=None):
    """Open the react-select marked [data-ats-target] via the interaction LADDER, read its
    options from several fallbacks, and commit the match. THE engine every combobox caller
    shares (see the block header). Returns 0 on success, 1 otherwise.

    `resolve_js` is the caller's own resolver script for THIS target. It is used only to
    re-mark the field if a React re-render drops the [data-ats-target] marker mid-ladder —
    never to pick a different field."""
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
        # 8s, not 2.5s (2026-08-15). Rungs 1-3 are LOCAL widgets whose options are already in
        # the DOM, so a short poll is right for them. This rung is the ASYNC path: the
        # keystrokes fire a server fetch (Greenhouse's School / Degree / Discipline education
        # typeaheads, Country, Location), and that round-trip routinely takes 4-6s. At 2.5s the
        # read landed on an empty list, combobox_pick reported `NO_OPTION:No options`, and the
        # field was written off as an unbindable widget — while typing the SAME text by hand
        # and waiting ~5s returned the option and picked it cleanly (verified live on
        # #school--0: 1 option, "University of the Arts", picked). So this was a race being
        # misread as a driver wall, on required fields that block the whole submit.
        # Only this fallback rung waits longer, so nothing that already worked gets slower.
        cfx.poll(_COMBO_READ_OPTS,
                 predicate=lambda r: isinstance(r, str) and r not in ("", "[]"), timeout=8.0)
        opts = _combo_options()
        # PREFIX RETRY (2026-08-15). _combo_type types the full desired string (up to 24
        # chars), which OVER-FILTERS whenever the real option label is SHORTER than what we
        # asked for. Concretely: wanting "University of the Arts London" types
        # "University of the Arts L", and the actual option is "University of the Arts" —
        # which does not contain that — so the list came back EMPTY and the field was
        # reported `NO_OPTION:No options`, i.e. a perfectly bindable typeahead looked like an
        # unbindable widget and blocked the submit (Greenhouse education: School, Discipline).
        # Retry with progressively shorter prefixes, which strictly widens the filter.
        if not opts:
            for n in (16, 10, 6):
                if n >= len(str(option)):
                    continue
                _combo_clear_input()
                _combo_type(str(option)[:n])
                cfx.poll(_COMBO_READ_OPTS,
                         predicate=lambda r: isinstance(r, str) and r not in ("", "[]"),
                         timeout=8.0)
                opts = _combo_options()
                if opts:
                    break
    # ⛔ INPUT-LESS DROPDOWNS: OPEN, THEN CLICK THE OPTION (2026-08-16). Every rung above
    # assumes the control owns an <input> — it focuses it, types into it, and reads the
    # filtered listbox. A growing number of widgets have NO input at all: the trigger is a
    # BUTTON and the options only exist once it is opened. On those, _COMBO_RESOLVE marks the
    # trigger, _combo_type has nothing to type into, the option list stays empty, and the
    # free-text commit reports NO_INPUT. That is exactly what blocked Dotmatics and IMC — the
    # same failure twice, so it is a shape this engine must handle, not a per-board quirk.
    # Proven on Workday's dropdowns earlier today: a trusted click on the trigger renders
    # real [role=option] nodes, and clicking the option binds where typing never could.
    if not opts:
        try:
            probe = cfx.evaluate("(()=>{const t=document.querySelector('[data-ats-target]');"
                                 "return t? (t.querySelector('input')?'has-input':'no-input') : 'no-target';})()")
        except Exception:  # noqa: BLE001
            probe = "no-target"
        if probe == "no-input":
            try:
                cfx.click_selector('[data-ats-target]', timeout=8)
            except Exception:  # noqa: BLE001
                cfx.evaluate("(()=>{const t=document.querySelector('[data-ats-target]');"
                             "if(t)t.click();return 1})()")
            time.sleep(1.6)
            hit = cfx.evaluate("""(()=>{const want=%s.toLowerCase();
              const norm=x=>(x.innerText||'').replace(/\\s+/g,' ').trim().toLowerCase();
              const os=[...document.querySelectorAll('[role=option]')];
              if(!os.length) return 'NO_OPTIONS';
              let o=os.find(x=>norm(x)===want);
              if(!o){const esc=want.replace(/[.*+?^${}()|[\\]\\\\]/g,'\\\\$&');
                     const re=new RegExp('(^|[^a-z0-9])'+esc+'([^a-z0-9]|$)');
                     o=os.find(x=>re.test(norm(x)));}
              if(!o) return 'NO_MATCH:'+os.slice(0,6).map(x=>norm(x)).join(' | ');
              o.setAttribute('data-ats-opt','1'); o.scrollIntoView({block:'center'});
              return 'FOUND:'+(o.innerText||'').trim().slice(0,40);})()""" % _js(str(option)))
            if isinstance(hit, str) and hit.startswith("FOUND:"):
                try:
                    cfx.click_selector('[data-ats-opt]', timeout=8)
                except Exception:  # noqa: BLE001
                    cfx.evaluate("(()=>{const o=document.querySelector('[data-ats-opt]');"
                                 "if(o)o.click();return 1})()")
                time.sleep(0.8)
                cfx.evaluate("(()=>{document.querySelectorAll('[data-ats-opt]')"
                             ".forEach(e=>e.removeAttribute('data-ats-opt'));return 1})()")
                _combo_clear_marker()
                print(f"OK=option-click:{hit[6:]}")
                return 0
            print(f"  input-less dropdown: {hit}")
    clicked = cfx.evaluate(_COMBO_CLICK.replace("__OPT__", _js(option))
                       .replace("__STRICT__", "true" if strict else "false"))
    if isinstance(clicked, str) and clicked.startswith("OK"):
        print(clicked)
        return 0
    # FREE-TEXT FALLBACK — ONLY when the list came back genuinely EMPTY. Some Ashby "Where are you
    # located?" comboboxes are async autocompletes whose suggestion source returns NOTHING in a
    # headless session (empty listbox), yet the field accepts the TYPED value on submit. Committing
    # the typed value (React native-setter so onChange fires, then Enter/blur) unblocks those. We do
    # NOT do this when options exist but none matched — that must still fail rather than guess a
    # wrong value — so the blast radius is only comboboxes that ALREADY fail with NO_OPTION.
    if not opts:
        ft = cfx.evaluate(_COMBO_FREETEXT_COMMIT.replace("__VAL__", _js(str(option))))
        if isinstance(ft, str) and ft.startswith("OK"):
            _combo_clear_marker()
            print(f"OK=freetext:{str(option)[:40]} (async suggestion list empty — committed typed value)")
            return 0
        if ft == "NO_INPUT":
            # ⛔ ALSO REACH THE OPTION-CLICK PATH FROM HERE (2026-08-16). The rung above only
            # fires when the option list came back EMPTY. An input-less dropdown whose options
            # ARE readable takes a different route: _COMBO_CLICK finds no match, the free-text
            # commit then reports NO_INPUT because the marked control owns no <input>, and the
            # pick fails — even though clicking the option would have worked. Same widget
            # shape, different entry point. Retry it here rather than duplicating the rung.
            again = _combo_click_option(option)
            if again:
                _combo_clear_marker()
                print(f"OK=option-click:{again}")
                return 0
        if ft == "NO_TARGET":
            # ⛔ RE-RESOLVE, DON'T GIVE UP (2026-08-17). `NO_TARGET` means the `data-ats-target`
            # marker is gone from the DOM — but that is almost never "the field vanished". A
            # React form re-renders while the ladder types and clicks, REPLACING the marked node
            # with an identical fresh one that carries no attribute. The field is still right
            # there; only our bookmark is stale.
            #
            # This was the single most expensive failure of the night. Every one of five 700s
            # timeouts ended on exactly this line — the full ladder (open, ArrowDown, trusted
            # click, 8s option poll, type-to-filter, input-less probe) runs per label, and
            # fill_eeo plus the bank-gap pass call it ~20 times a form, so one posting could
            # exhaust the whole timeout without ever reaching Submit.
            #
            # Re-running the SAME resolver on the SAME target is not guessing — it is the
            # deterministic lookup that produced the marker in the first place, so the
            # "never fall back to the first combobox on the page" guarantee is untouched.
            info2 = {"kind": "none"}
            if resolve_js:
                try:
                    info2 = json.loads(cfx.evaluate(resolve_js))
                except (ValueError, TypeError):
                    info2 = {"kind": "none"}
            if info2.get("kind") not in (None, "none"):
                ft2 = cfx.evaluate(_COMBO_FREETEXT_COMMIT.replace("__VAL__", _js(str(option))))
                if isinstance(ft2, str) and ft2.startswith("OK"):
                    _combo_clear_marker()
                    print(f"OK=freetext:{str(option)[:40]} (marker re-resolved after re-render)")
                    return 0
                again2 = _combo_click_option(option)
                if again2:
                    _combo_clear_marker()
                    print(f"OK=option-click:{again2} (marker re-resolved after re-render)")
                    return 0
            print("FAIL: free-text commit had no resolved target — refusing to guess a field")
    _combo_clear_marker()
    print(clicked if isinstance(clicked, str) else "FAIL")
    print(_EXTEND_HINT)
    return 1


def combobox_pick(target, option, multi=False, clear_first=False, quiet_notfound=False,
                  allow_attestation=False, strict=False):
    """THE universal dropdown/combobox primitive — native <select> AND every react-select
    variant, driven by the interaction ladder (see block header). `target` = a CSS/#id
    selector OR a substring of the field's visible label. `multi` = mark-all-that-apply
    (adds, doesn't replace); `clear_first` removes existing chips first (to REPLACE a wrong
    multi-select answer). Returns 0 / 1 / NOTFOUND (the last only with quiet_notfound when
    no such field exists — the defaults path uses it to skip a missing field cleanly),
    or ANTI_AI when it refuses to sign an anti-AI oath (see below).

    ⛔ ANTI-AI OATH GUARD (2026-08-14). `checkboxes_from_profile` has always default-denied the
    "I confirm this application is entirely my own words / AI-generated content will disqualify
    me" oath — but that guard lived in the CHECKBOX path only, i.e. it was widget-shaped rather
    than meaning-shaped. Canonical's Greenhouse forms ask the IDENTICAL oath as a **required
    react-select** ("During this application process I agree to use only my own words. I
    understand that plagiarism, the use of AI or other generated content will disqualify my
    application.*" → Yes/No), and every board config routes that through here — so an agent
    filling the form would silently answer "Yes" and sign a false attestation on the
    applicant's behalf. That is worse than a crash: it is a lie told in his name, on the
    record, that can disqualify a real application he cares about.
    Refusing is the correct behaviour, so the refusal lives in the ONE shared primitive every
    board delegates to (AGENTS.md §6) rather than in each caller.
    `allow_attestation=True` is the deliberate override for a HUMAN who wrote the answers
    themselves — never set it from an autonomous path.

    ⛔ RADIO GROUPS ARE NOT COMBOBOXES (2026-08-15, integrity bug — read before touching
    `_COMBO_RESOLVE`). The resolver's bare `input` fallback used to match ANY input under the
    label's container, including `input[type=radio]`. So an Ashby EEO radio group ("Do you
    identify as Transgender?" → Yes/No/Unsure/Prefer not to say) resolved as `kind:'combo'`,
    `data-ats-target` landed on the FIRST radio, and ladder rung 3 (`click_selector`) CLICKED
    it — selecting option index 0. No listbox ever appeared, so the free-text fallback then
    committed the typed value into nothing and printed `OK=freetext:No`. Net effect: a
    confident success message while the form actually said **Transgender=Yes, Orientation=Bi**
    — false demographic answers about the applicant, on a real submission, in his name.
    This had been hand-corrected at least once before (tracker, Accurx 2026-07-26: "fixed
    driver-default wrong EEO (trans=Yes, orient=Bi) to real answers before submit") without
    ever being fixed at the root, so it kept recurring. `_COMBO_RESOLVE` now returns
    `kind:'none', reason:'radio-group'` for a radio/checkbox control, which makes
    `fill_eeo` fall through to `set_radio` — the primitive that actually matches option TEXT.
    Guard test: `tests/test_core.py::TestComboboxRadioGuard`."""
    if not allow_attestation and _is_anti_ai_oath(target) and _is_affirmative(option):
        print(f"REFUSE combobox_pick {str(target)[:60]!r} -> {option!r}: anti-AI attestation. "
              "Not signing an 'own words / no AI' oath on the applicant's behalf.")
        print("  → this posting needs the applicant's own answers: hand it to the human queue "
              "(scripts/human_queue.py), or re-run with allow_attestation=True once THEY have "
              "written the free-text answers themselves.")
        return ANTI_AI
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
        print(_EXTEND_HINT)
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
    rc = _combo_open_and_pick(option, multi=multi or bool(info.get("isMulti")),
                              resolve_js=resolve_js,
                              strict=strict)
    # ⛔ SYNONYM RETRY FOR COMBOBOXES TOO (2026-08-16). set_radio has had this since
    # 2026-08-15: the profile records ONE canonical wording per fact, employers word the same
    # option differently, and a truthful KNOWN answer that simply is not spelled the way this
    # form spells it left a required field empty. combobox_pick never got it, so the identical
    # miss on a DROPDOWN still blocked the submit — live example: the bank holds "Native or
    # bilingual" for English proficiency while Parloa's form offers only a CEFR scale
    # (none/A1/…/C2), so the closed-set guard correctly refused and the posting stalled on a
    # question whose answer is not in doubt. These are exact synonyms of the SAME claim (never
    # a broadening — see _OPTION_SYNONYMS), so retrying changes only the wording.
    if rc != 0 and not strict:
        tried = {str(option).strip().lower()}
        for alt in _OPTION_SYNONYMS.get(str(option).strip().lower(), []):
            if alt.strip().lower() in tried:
                continue
            tried.add(alt.strip().lower())
            if _combo_open_and_pick(alt, multi=multi or bool(info.get("isMulti")),
                                    resolve_js=resolve_js) == 0:
                print(f"  (matched {option!r} via synonym {alt!r})")
                return 0
    return rc


def select(label, option, quiet_notfound=False, strict=False):
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
    return _combo_open_and_pick(option, strict=strict)


# EXACT synonyms of the SAME answer — different employer wording, identical claim. Used only
# as a retry when the profile's canonical wording finds no option (see set_radio). Keep these
# strictly equivalent: anything that would BROADEN or change the answer does not belong here.
_OPTION_SYNONYMS = {
    # GLA/SuccessFactors spells the mixed-ethnicity bucket "Mixed/Multiple ethnic groups -
    # Any other Mixed/Multiple ethnic background"; the census wording in apply-defaults is
    # "Mixed or Multiple ethnic groups". Without this pair fill_eeo fell back to committing
    # free text, which is not a selectable option and never persists (2026-08-16).
    "mixed or multiple ethnic groups": [
        "Mixed/Multiple ethnic groups - Any other Mixed/Multiple ethnic background",
        "Mixed/Multiple ethnic groups", "Any other Mixed/Multiple ethnic background"],

    # A country select spells the applicant's country any of ~six ways. Verified live
    # 2026-08-17 on Stripe's "Please select the country you are currently located in."
    # (options: …, 'UK', 'US', 'Other') — the truthful answer "United Kingdom" matched no
    # option, so a required field the applicant CAN answer came back UNANSWERED_REQUIRED and
    # the posting was not driven at all. Same class as the ethnicity-wording miss below:
    # the claim is identical, only the vocabulary differs.
    "united kingdom": ["UK", "U.K.", "Great Britain", "GB",
                       "United Kingdom of Great Britain and Northern Ireland",
                       "United Kingdom (UK)", "England"],
    "uk": ["United Kingdom", "U.K.", "Great Britain", "GB", "United Kingdom (UK)"],
    "british": ["British Citizen", "British or Irish Citizen", "UK national",
                "British / Irish", "United Kingdom"],

    "heterosexual": ["Straight", "Heterosexual/Straight"],
    "straight": ["Heterosexual", "Heterosexual/Straight"],
    "male": ["Man"],
    "man": ["Male"],
    "female": ["Woman"],
    "woman": ["Female"],
    "prefer not to say": ["I don't wish to answer", "I do not wish to answer",
                          "Decline to self identify", "Prefer not to disclose"],
    "yes": ["True"],
    "no": ["False"],
    # CEFR vs plain-English language scales are the same claim in different vocabularies
    # (2026-08-16). The bank holds "Native or bilingual"; Parloa's form offers only
    # none/A1/A2/B1/B2/C1/C2, so the closed-set guard correctly refused to answer and the
    # posting blocked on a question whose truthful answer is not in doubt — he is a British
    # citizen and native English speaker who did content design inside the GOV.UK Design
    # System. C2 is the CEFR label for that same proficiency, not an upgrade of the claim.
    "native or bilingual": ["C2: Proficient", "C2", "Native", "Fluent", "Native speaker"],
    "c2: proficient": ["Native or bilingual", "Native", "Fluent"],
    "fluent": ["C2: Proficient", "Native or bilingual", "Native"],
    # "How did you hear about us?" option sets describe the SAME sourcing channel in
    # different words (2026-08-16). The bank holds "Company careers site" — truthful, these
    # postings come off the employer's own Greenhouse board — but Dotmatics' only matching
    # option is "Job board, careers website, or LinkedIn". No word-boundary overlap, so the
    # pick failed and a required field blocked the submit on a question whose answer is not
    # in doubt. These are all the same claim; none names an affiliation (university, alumni,
    # referral), which is the thing pick_option deliberately refuses.
    "company careers site": ["Job board, careers website, or LinkedIn", "Careers website",
                             "Company website", "Job board", "Careers site", "Company site"],
    "job board": ["Job board, careers website, or LinkedIn", "Careers website",
                  "Company website", "Careers site"],
}


def set_radio(question, option, quiet_notfound=False, _tried=None, strict=False):
    # ⛔ MATCH PRECEDENCE, NOT FIRST-SUBSTRING (2026-08-15 — a real wrong answer).
    # This used to take the FIRST radio whose label merely CONTAINED the wanted option, in DOM
    # order. Asking for gender "Man" therefore matched **"Woman"** ("woman".includes("man")),
    # which is the option listed first on Paddle's Ashby form — so a real submission stated the
    # applicant's gender as Woman. The same trap is one character away everywhere else in EEO
    # ("male" inside "female", "Asian" inside "Caucasian", "No" inside "Not applicable").
    # Fix: score every candidate in the matching group and pick the BEST, in strict order —
    # exact match → whole-word match → substring — instead of whichever appeared first.
    # `_COMBO_NATIVE_SET` already used the word-boundary regex; set_radio simply never did.
    res = cfx.evaluate(f"""
    (() => {{
      const norm = s => (s||'').replace(/\\s+/g,' ').trim().toLowerCase();
      const wq = norm({_js(question)}), wo = norm({_js(option)});
      const esc = wo.replace(/[-/\\\\^$*+?.()|[\\]{{}}]/g, '\\\\$&');
      const wb = new RegExp('(^|[^a-z0-9])' + esc + '([^a-z0-9]|$)');
      // QUESTION RESOLUTION (2026-08-15). The old fallback when a group had no
      // <fieldset>/<legend> was `r.name` — which on Ashby/Greenhouse is a random UUID, so the
      // question could NEVER match and every such group returned NOT_FOUND. Live on
      // Freetrade's form the right-to-work group is a bare div, so both set_radio AND the
      // screener bank silently failed on a required field. Climb to the nearest ancestor
      // carrying real text (the same walk _UNANSWERED uses) before giving up.
      const qtext = r => {{
        const fs = r.closest('fieldset');
        const leg = fs ? fs.querySelector('legend,label') : null;
        if (leg && norm(leg.innerText)) return leg.innerText;
        // ⛔ CLIMB PAST THE OPTIONS CONTAINER (2026-08-16). This used to return the first
        // ancestor with more than 8 characters of text — but for a fieldset-less group that
        // ancestor is almost always the div WRAPPING THE OPTIONS, whose text is just
        // "Yes No Prefer not to say". That is >8 chars, so the walk stopped there and the
        // caller's question never matched: `norm(q).includes(wq)` failed and the group came
        // back NOT_FOUND. The symptom is a required radio left blank and a submit that
        // bounces — the group is unanswerable, so the application is simply lost. Strip the
        // group's OWN option labels out of each ancestor before judging it: the options
        // container reduces to nothing and the walk continues up to the real question.
        let b = r;
        for (let k = 0; k < 8 && b; k++) {{
          b = b.parentElement; if (!b) break;
          let t = norm(b.innerText); if (!t) continue;
          for (const rr of b.querySelectorAll('input[type=radio]')) {{
            const l = norm((rr.labels && rr.labels[0]) ? rr.labels[0].innerText : (rr.value||''));
            if (l) t = t.split(l).join(' ');
          }}
          if (norm(t).length > 8) return b.innerText;
        }}
        return r.name || '';
      }};
      let best = null, bestRank = 99, nbest = 0;
      for (const r of document.querySelectorAll('input[type=radio]')) {{
        const q = qtext(r);
        const lbl = norm((r.labels && r.labels[0]) ? r.labels[0].innerText : (r.value||''));
        if (!norm(q).includes(wq)) continue;
        const rank = (lbl === wo) ? 0 : (wb.test(lbl) ? 1 : (lbl.includes(wo) ? 2 : 99));
        if (rank < bestRank) {{ bestRank = rank; best = r; nbest = 1;
          if (rank === 0) break; }}
        else if (rank === bestRank && rank < 99) nbest++;
      }}
      if (!best) return 'NOT_FOUND';
      // Same broadening guard as _COMBO_CLICK: under STRICT (the fill_eeo leading-token
      // fallback) an inexact match that fits several options is a coin-flip between
      // demographic sub-categories, so refuse instead of picking one.
      if ({'true' if strict else 'false'} && bestRank > 0 && nbest > 1) return 'AMBIGUOUS';
      const lbl = ((best.labels && best.labels[0]) ? best.labels[0].innerText : (best.value||'')).trim();
      if (!best.checked) best.click();
      return best.checked ? ('OK:'+lbl.slice(0,40)) : 'CLICK_FAILED';
    }})()
    """)
    if isinstance(res, str) and res.startswith("OK"):
        print(res)
        return 0
    # SYNONYM RETRY (2026-08-15). The profile records ONE canonical wording per fact, but
    # employer forms word the same option differently — Paddle's Ashby form offers "Straight"
    # where apply-defaults.json says "Heterosexual", so a truthful, known answer resolved to
    # NOT_FOUND and left a required EEO radio blank, aborting the submit. These are exact
    # synonyms of the SAME answer (never a broadening: "Bi"→"Queer" is deliberately absent),
    # so retrying with them changes only the wording, never the claim.
    # `_tried` is load-bearing, not defensive: the synonym map is deliberately SYMMETRIC
    # ("heterosexual"->"Straight" and "straight"->"Heterosexual"), so an unguarded retry
    # recurses mutually forever — which it did, surfacing as a RecursionError deep inside
    # urllib's email parser rather than anywhere near this function.
    if res == "NOT_FOUND":
        tried = _tried if _tried is not None else {option.strip().lower()}
        for alt in _OPTION_SYNONYMS.get(option.strip().lower(), []):
            if alt.strip().lower() in tried:
                continue
            tried.add(alt.strip().lower())
            if set_radio(question, alt, quiet_notfound=True, _tried=tried, strict=strict) == 0:
                print(f"  (matched {option!r} via synonym {alt!r})")
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
    # ⛔ MATCH PRECEDENCE, NOT FIRST-SUBSTRING (2026-08-16) — the SAME defect set_radio was
    # fixed for on 2026-08-15, never carried across to checkboxes. Taking the first label that
    # merely CONTAINS the wanted text, in DOM order, ticks the wrong box whenever one option's
    # text is a substring of another's: asking for "Man" ticks "Woman"; asking for consent to
    # "contact me about this role" ticks "contact me about this role and future roles and
    # partner offers" (a broader consent than was given); "No" ticks "Not applicable".
    # Score every candidate and take the BEST: exact → whole-word → substring.
    res = cfx.evaluate(f"""
    (() => {{
      const norm = s => (s||'').replace(/\\s+/g,' ').trim().toLowerCase();
      const w = norm({_js(label)});
      const esc = w.replace(/[-/\\\\^$*+?.()|[\\]{{}}]/g, '\\\\$&');
      const wb = new RegExp('(^|[^a-z0-9])' + esc + '([^a-z0-9]|$)');
      let best = null, bestRank = 99;
      for (const c of document.querySelectorAll('input[type=checkbox]')) {{
        const lbl = norm((c.labels && c.labels[0]) ? c.labels[0].innerText : '');
        const rank = (lbl === w) ? 0 : (wb.test(lbl) ? 1 : (lbl.includes(w) ? 2 : 99));
        if (rank < bestRank) {{ bestRank = rank; best = c; if (rank === 0) break; }}
      }}
      if (!best) return 'NOT_FOUND';
      if (best.checked !== {str(want).lower()}) best.click();
      return best.checked === {str(want).lower()} ? ('OK checked='+best.checked) : 'CLICK_FAILED';
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
  // label[for=id] is an UNAMBIGUOUS association — match its text LOOSELY (no length cap), so a
  // verbose consent label ("Keeping your data safe is really important to us. Please…") still
  // resolves to its input (the length cap on `match` above excludes full-sentence labels).
  const lab=[...document.querySelectorAll('label[for]')].find(
    e=>norm(e.textContent).includes(w) && document.getElementById(e.htmlFor));
  if(lab){const e=document.getElementById(lab.htmlFor); if(e)return e;}
  const h=[...document.querySelectorAll('label,legend,h3,h4,span,div,p')].find(match);
  if(h){const sc=h.closest('fieldset,div,section')||h.parentElement;
        if(sc){const c2=sc.querySelector('input:not([type=hidden]),select,textarea,[role=radiogroup],[role=combobox]');
               if(c2) return c2;}}
  // FIELD-ANCHORED fallback — Ashby (+ similar) render a location/typeahead as
  // <input role=combobox placeholder="Start typing..."> with NO label[for] and NO
  // aria-label; the question text ("Where are you located?") sits in a SIBLING div, so the
  // scans above miss it (h.closest('div') resolves to the label div itself, which holds no
  // control → the documented `no select/combobox for 'located'` FAIL). Anchor on each
  // control and test ITS OWN field-group text (walking up a few ancestors) against the
  // question — mirrors select()'s inp.closest(...).innerText route. Last resort, so it can
  // only ever convert a FAIL into a hit.
  //   DISAMBIGUATION (2026-07-24): prefer a control whose OWN label EXACTLY equals or
  //   STARTS WITH the keyword (so "Location" -> the Location field, NOT the work-auth
  //   field "authorized to work in this location?"), then fall back to substring-ancestor
  //   only if no exact/leading match exists. This stops "location" from resolving to the
  //   wrong combobox when several fields mention the word in their body text.
  const CTRLS='[role=combobox],input[aria-autocomplete=list],select,textarea,'+
              'input:not([type=hidden]):not([type=checkbox]):not([radio]):not([type=submit]):not([type=button])';
  function ownLabel(ctl){
    let p=ctl.parentElement;
    for(let i=0;i<3 && p;i++){
      const t=norm(p.textContent);
      if(t) return t;
      p=p.parentElement;
    }
    return '';
  }
  // pass 1: exact or leading-label match (tightest)
  for (const ctl of [...document.querySelectorAll(CTRLS)]){
    const n=ownLabel(ctl).replace(/[^a-z]/g,'');
    if(n===w || n.indexOf(w)===0) return ctl;
  }
  // pass 2: substring anywhere in the field-group (looser, last resort).
  // ⛔ MEASURE THE QUESTION, NOT THE OPTION LIST (2026-08-15). `textContent` of a container
  // holding a <select> includes EVERY option label — Palantir's "Which university…" select
  // carries a few thousand universities, so `gt.length` was enormous and the
  // `< w.length+90` tightness guard could never pass. A required, perfectly ordinary native
  // <select> was therefore unresolvable by label and combobox_pick returned NOTFOUND.
  // groupText() walks text nodes and skips anything inside a SELECT/DATALIST, so the guard
  // sees the question text alone, which is what it was written to measure.
  const groupText=g=>{
    let out='';
    const tw=document.createTreeWalker(g, NodeFilter.SHOW_TEXT, {acceptNode(n){
      for(let p=n.parentElement;p&&p!==g;p=p.parentElement){
        const tag=p.tagName;
        if(tag==='SELECT'||tag==='OPTION'||tag==='DATALIST') return NodeFilter.FILTER_REJECT;
      }
      return NodeFilter.FILTER_ACCEPT;
    }});
    while(tw.nextNode()){ out+=' '+tw.currentNode.nodeValue; if(out.length>600) break; }
    return norm(out);
  };
  for (const ctl of [...document.querySelectorAll(CTRLS)]){
    let g=ctl.parentElement;
    for(let i=0;i<4 && g;i++,g=g.parentElement){
      const gt=groupText(g);
      // The tightness guard exists to stop a whole-form container matching. `w.length+90`
      // alone is too strict for a question that carries instructions — Palantir's is
      // "Which university are you currently attending or did you last attend? Please select
      // \"Other\"…" at 142 chars, which a short query could never clear. An absolute floor
      // admits one verbose question while still excluding a form-sized blob.
      if(gt.includes(w) && gt.length < Math.max(w.length+90, 240)) return ctl;
    }
  }
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


# ── Truthful checkbox auto-fill ─────────────────────────────────────────────────────────────
# The SAFE alternative to a blanket "tick every unchecked box before submit" — that would assert
# untrue things (veteran/disability self-ID, eligibility, consents, the anti-AI oath) as the
# applicant's answers. This enumerates each checkbox, classifies its label, and ticks ONLY boxes
# whose statement is affirmatively TRUE for the applicant. DEFAULT-DENY: anything it can't
# positively verify — an unknown label, a false eligibility fact, a marketing opt-in, the anti-AI
# oath — is LEFT UNCHECKED and reported, never guessed.
_ENUM_CHECKBOXES = r"""
(() => {
  const cbs = [...document.querySelectorAll('input[type=checkbox]')];
  const lab = c => {
    if (c.labels && c.labels[0]) return c.labels[0].innerText;
    if (c.id){ const l=document.querySelector('label[for="'+c.id+'"]'); if(l) return l.innerText; }
    const p = c.closest('label'); if (p) return p.innerText;
    let a=c.parentElement; for(let k=0;k<3&&a;k++,a=a.parentElement){ const t=(a.innerText||'').trim(); if(t && t.length<300) return t; }
    return c.getAttribute('aria-label') || c.name || '';
  };
  cbs.forEach((c,i)=>c.setAttribute('data-ats-cb', i));
  return JSON.stringify(cbs.map((c,i)=>({i, checked: c.checked,
    label: (lab(c)||'').replace(/\s+/g,' ').trim()})));
})()
"""

_TICK_CB_BY_INDEX = r"""
(() => {
  const want = new Set(__IDXS__); let n=0;
  for (const c of document.querySelectorAll('input[type=checkbox][data-ats-cb]')) {
    if (want.has(parseInt(c.getAttribute('data-ats-cb'),10)) && !c.checked) { c.click(); n++; }
  }
  return n;
})()
"""

# (category, regex). ORDER MATTERS: anti-AI and marketing are matched FIRST so a box that also
# reads like a generic "consent" can't be mis-ticked. A label matching NO rule is UNKNOWN.
_CB_RULES = [
    # ⛔ WIDENED 2026-08-16 — Twilio's oath matched NOTHING here. Its wording is
    #   "…the guidelines outlined in the Candidate AI Responsible Use Policy. I affirm that all
    #    the information and materials I submit … will reflect my own work and experience."
    # No "own words", no "no AI", no "AI-generated", and "AI Responsible Use Policy" is not
    # "use of ai" — so this rule missed it and `gen_gh_config` cleared the posting as fully
    # answerable. Only checkbox DEFAULT-DENY (an unmatched label => left_unknown) stopped the
    # box being ticked, i.e. the safety net held for the wrong reason and reported the field as
    # a mystery rather than as an oath. "AI use policy" acknowledgements are now common and
    # rarely use the old phrasings, so match the FAMILY two ways:
    #   (a) explicit spellings, incl. "responsible use of AI" / "AI … use policy"; and
    #   (b) the PAIR — the label mentions AI *and* asks the applicant to affirm the work is
    #       their own. The pair branch is zero-width (two lookaheads scanning the whole label),
    #       so re.S is set on the compile: labels arrive with newlines in them, and the flag
    #       must be a COMPILE flag, not an inline `(?s)` mid-pattern — Python 3.8 only warns
    #       about a non-leading inline flag, but 3.11+ raises re.error and would break import.
    ("anti_ai", re.compile(r"only my own words|\bno ai\b|without (the use of )?ai|ai[- ]?generated|"
                           r"use of ai|responsible use of ai|\bai\b[^.]{0,40}use polic|"
                           # ⛔ FOURTH MISS OF THIS FAMILY (2026-08-16). MHCLG/Applied phrase it as
                           # PLAGIARISM: "if evidence of plagiarism is found in my application it
                           # may be rejected. Examples … include presenting the ideas and
                           # experience of others, OR GENERATED BY ARTIFICIAL INTELLIGENCE, as
                           # your own." Accepting that attests the application is not AI-written —
                           # the same oath, and refusing is offered as "I am not eligible to
                           # apply". It matched nothing: the consequence word was "rejected" (not
                           # in the disqualify list) and the possessive was "as YOUR own", while
                           # the pair branch only knew "my own". Both gaps are closed below.
                           r"artificial intelligence.{0,40}(disqualif|prohibit|not permitted|"
                           r"not allowed|reject|withdraw|dismiss)|"
                           r"plagiar[a-z]*[\s\S]{0,200}?(?:\bai\b|artificial intelligence)|"
                           r"(?:\bai\b|artificial intelligence)[\s\S]{0,200}?plagiar|"
                           r"(?=.*(?:\bai\b|\ba\.i\.\b|artificial intelligence))"
                           r"(?=.*\b(?:my|your|their) own (?:work|words|effort|writing|"
                           r"experience)?)", re.I | re.S)),
    ("marketing", re.compile(r"marketing|newsletter|promotional|keep me (updated|informed|posted)|"
                             r"future (roles|jobs|opportunities|vacancies)|talent (community|network|pool)|"
                             r"subscribe|contact me about (other|future)", re.I)),
    ("right_to_work_uk", re.compile(r"right to work in the uk|eligible to work in the uk|"
                                    r"authori[sz]ed to work in the uk|permission to work in the uk", re.I)),
    ("needs_visa", re.compile(r"(require|need)\w*.{0,25}(visa|sponsor)|would need sponsorship", re.I)),
    ("veteran", re.compile(r"\bveteran\b|armed forces|ex[- ]?forces|military service", re.I)),
    ("disability", re.compile(r"have a disabilit|long[- ]term (health )?condition|consider yourself.{0,15}disab", re.I)),
    ("over_18", re.compile(r"18 (years|or older|or over)|over 18|at least 18|of legal (working )?age", re.I)),
    ("accuracy", re.compile(r"information.{0,30}(true|accurate|correct|complete)|"
                            r"declare.{0,20}(true|accurate|correct)|certify.{0,20}(accurate|correct|true)|"
                            r"to the best of my knowledge", re.I)),
    # NOTE the ordering contract above: `marketing` is matched BEFORE this rule, so a
    # "retain my data for FUTURE opportunities" talent-pool box still lands in marketing and
    # stays unticked even though it also talks about storing data. That ordering is what makes
    # it safe for this pattern to mention store/process at all.
    # 2026-08-14: added the "I agree to allow <Company> to store and process my data ..."
    # phrasing (Cognism/Greenhouse). It is a REQUIRED, procedurally-true consent — you cannot
    # apply without it — but it matched no rule, so it fell through to `left_unknown` and was
    # left unticked, and the submit bounced with a validation error that named no field. The
    # applicant genuinely does consent to his application being processed by the employer he
    # is applying to; that is the whole act of applying.
    ("consent", re.compile(r"privacy (policy|notice)|terms (and|&) conditions|terms of (use|service)|"
                           r"data (protection|processing) (policy|notice|statement)|read and (agree|accept|understood)|"
                           r"consent to.{0,40}(process|store|use).{0,25}(data|application|personal)|\bgdpr\b|"
                           r"i (agree|consent).{0,50}(stor|process|collect).{0,60}"
                           r"(data|personal|information|demographic|survey|responses)|"
                           r"i (agree|accept).{0,25}(privacy|terms|processing of)", re.I)),
]
# eligibility categories → apply-defaults.json 'checkbox_truths' key (config-routed, gitignored)
_CB_FACT = {"right_to_work_uk": "right_to_work_uk", "needs_visa": "needs_visa_sponsorship",
            "veteran": "veteran", "disability": "disability", "over_18": "over_18"}


def _is_anti_ai_oath(label):
    """Does this field's label carry the 'only my own words / no AI-generated content' oath?

    Reuses the SAME `_CB_RULES` anti_ai pattern the checkbox path uses, so the two can never
    drift apart — the whole point of the 2026-08-14 fix is that this judgement is about the
    question's MEANING, not about which widget happens to render it (checkbox vs react-select
    vs radio). Pure + browser-free so it is unit-testable."""
    rx = next((r for c, r in _CB_RULES if c == "anti_ai"), None)
    return bool(rx and rx.search(str(label or "")))


# PUBLIC alias. `scripts/gen_gh_config.py` kept its OWN narrower copy of the anti-AI regex
# (2026-08-16) — missing `without the use of ai` and the artificial-intelligence/prohibited
# clause — so the GATE cleared oaths the FILLER would have refused. The docstring above claimed
# the two "can never drift apart"; that only ever held INSIDE this module. Every other module
# must import this function, never re-spell the pattern. Guard: tests/test_core.py
# ::TestNoDivergentAntiAiOath turns red if a second anti-AI regex literal appears anywhere else.
is_anti_ai_oath = _is_anti_ai_oath


# Affirmative answers to an oath-shaped question. "Acknowledge/Confirm" is Canonical's literal
# option text; agree/accept/consent/tick cover the other boards' phrasings.
_AFFIRMATIVE_RX = re.compile(
    r"^\s*(yes|y|true|agree[d]?|i agree|accept(ed)?|i accept|confirm(ed)?|i confirm|"
    r"acknowledge|acknowledge/confirm|consent|i consent|on|checked|tick(ed)?)\b", re.I)


def _is_affirmative(option):
    """Is this option value an affirmative answer? Used only to decide whether an anti-AI oath
    is being SIGNED — answering such a question "No" is perfectly honest and stays allowed, so
    the guard must not block it."""
    return bool(_AFFIRMATIVE_RX.match(str(option or "").strip()))


def _cb_action(label, truths):
    """Pure per-label decision (unit-testable, no browser): returns (action, category) where
    action is 'tick' | 'left_antiai' | 'left_marketing' | 'left_unknown' | 'left_false'.
    DEFAULT-DENY: only 'tick' when the box is affirmatively true (procedural accuracy/consent,
    or an eligibility fact that checkbox_truths marks True)."""
    cat = next((c for c, rx in _CB_RULES if rx.search(label or "")), None)
    if cat == "anti_ai":
        return ("left_antiai", cat)
    if cat == "marketing":
        return ("left_marketing", cat)
    if cat in ("accuracy", "consent"):
        return ("tick", cat)
    if cat is None:
        return ("left_unknown", None)
    return ("tick", cat) if truths.get(_CB_FACT[cat]) is True else ("left_false", cat)


def checkboxes_from_profile(config=None, do_tick=True):
    """Tick ONLY checkboxes whose statement is affirmatively true for the applicant; leave
    unknown / false / marketing / anti-AI boxes unchecked (and report them). The truthful
    replacement for a blanket tick-all. Applicant eligibility facts come from apply-defaults.json
    'checkbox_truths' (gitignored); procedural accuracy/consent boxes are true by virtue of
    applying; marketing opt-ins and the anti-AI oath are never auto-selected. Returns a report."""
    try:
        truths = (config or _load_defaults(True) or {}).get("checkbox_truths", {}) or {}
    except Exception:  # noqa: BLE001
        truths = {}
    try:
        items = json.loads(cfx.evaluate(_ENUM_CHECKBOXES) or "[]")
    except (ValueError, TypeError):
        items = []
    rep = {"ticked": [], "left_false": [], "left_unknown": [], "left_marketing": [], "left_antiai": []}
    tick_idx = []
    for it in items:
        if it.get("checked"):
            continue
        short = (it.get("label") or "").strip()[:70]
        action, cat = _cb_action(it.get("label") or "", truths)
        if action == "tick":
            tick_idx.append(it["i"]); rep["ticked"].append(short)
        elif action == "left_false":
            rep["left_false"].append(f"{short} [{cat}={truths.get(_CB_FACT[cat])!r}]")
        else:
            rep[action].append(short)
    if do_tick and tick_idx:
        cfx.evaluate(_TICK_CB_BY_INDEX.replace("__IDXS__", json.dumps(tick_idx)))
    return rep


def fill_eeo(config=None):
    """Fill OPTIONAL EEO/diversity fields from apply-defaults.json -> `applicant`. THE one
    EEO filler for every ATS (promoted from gh_apply._fill_eeo 2026-07-24; Greenhouse delegates
    here and Ashby now uses it too — do NOT re-roll a per-board EEO answerer).

    WHY IT'S SHARED. `ashby.py` had no EEO capability, so a bespoke board script grew one that
    answered "I don't wish to answer" to gender / LGBTQ+ / sexual orientation / ethnicity —
    the exact OPPOSITE of the applicant's standing instruction (applicant-profile.md
    §Demographics, 2026-07-19: DISCLOSE these; only age stays "prefer not to say"). A second
    copy didn't just duplicate logic, it inverted the policy. One implementation, reading the
    profile, is the fix.

    WIDGET-AGNOSTIC: each field is tried as a react-select combobox FIRST (Greenhouse renders
    these as multi-selects) and then as a radio group (Ashby's usual rendering), so one plan
    covers both. A field absent from this form returns NOTFOUND and is skipped — EEO is
    optional and must never block a submit. Honours `disclose_demographics`: a value starting
    with "no" skips the whole pass. Returns [(field, value, result)]."""
    try:
        defaults = config if isinstance(config, dict) else (_load_defaults(True) or {})
    except Exception:  # noqa: BLE001
        defaults = {}
    a = defaults.get("applicant", {}) or {}
    if str(a.get("disclose_demographics", "")).strip().lower().startswith("no"):
        return [("(disclose_demographics=No)", "", "SKIP")]
    # (label alternates, value, mark-all-that-apply). Gender phrasings are SPECIFIC so they
    # can't collide with "is your gender identity the same as sex assigned at birth?" (a Yes/No
    # question) — matching that would put "Man" on the wrong field.
    plan = [
        (["how would you describe your gender", "which gender do you identify",
          "best describes your gender", "i identify my gender as", "gender identity"],
         a.get("gender_identity") or a.get("gender"), True),
        (["sexual orientation", "lgbtq"], a.get("sexual_orientation"), True),
        # ETHNICITY (re-enabled 2026-08-15). It used to be skipped entirely because some
        # employer forms render a "race/ethnicity" combobox whose option list is actually a
        # COUNTRY DIALLING-CODE list, and pushing an ethnicity into that is wrong. But
        # skipping is not free: Greenhouse marks these EEO selects REQUIRED (Graphcore's
        # "What is your ethnicity?*"), so an empty one bounces the submit with a bare
        # "This field is required." and the whole application fails over a question the
        # profile answers. The original worry is already handled by the primitive: both
        # combobox_pick and set_radio only ever select an option that MATCHES the value, so
        # against a dialling-code list "Mixed or Multiple ethnic groups" simply finds nothing
        # and the field stays empty — exactly the old behaviour, without failing the forms
        # that ask the question properly. (Closed-set validation, same rule as
        # fill_gaps_from_bank.) Religion remains untouched — it is a separate field.
        (["what is your ethnicity", "your ethnicity", "ethnic group", "ethnicity"],
         a.get("ethnicity"), True),
        (["transgender"], a.get("transgender"), False),
        (["disability", "chronic condition", "consider yourself disabled"], a.get("disability"), False),
        (["veteran"], a.get("veteran"), False),
    ]
    done = []
    for labels, val, multi in plan:
        if not val:
            continue
        # The profile stores ONE canonical wording; employers use their own. Census-style
        # options are the worst case: the profile says "Mixed or Multiple ethnic groups"
        # while Greenhouse offers "Mixed (White and Black Caribbean, White and Black African,
        # White and Asian, Any other mixed or multiple ethnic background)" — no substring of
        # the profile's phrasing appears in it, so an exact-first match fails on a REQUIRED
        # field. Falling back to the leading token ("Mixed") matches the employer's own
        # category without broadening the claim: both name the same census group. Only ever a
        # FALLBACK, so a form using the full phrasing still binds exactly.
        candidates = [val]
        head = str(val).split()[0].strip(",;/") if str(val).split() else ""
        if head and len(head) >= 4 and head.lower() != str(val).strip().lower():
            candidates.append(head)
        rc = "NO_FIELD"
        for lab in labels:
            hit = False
            for cand in candidates:
                # STRICT for the leading-token fallback only. `val` is the applicant's own
                # canonical wording, so matching it is always faithful; `head` is a BROADENED
                # stand-in, and broadening is only sound if the form offers exactly one option
                # under that token. Strict mode makes an ambiguous head match refuse rather
                # than let the scorer pick the shortest sub-category (see _COMBO_CLICK).
                strict = cand != val
                r = combobox_pick(lab, cand, multi=multi, clear_first=multi, quiet_notfound=True,
                                  strict=strict)
                if r == NOTFOUND:
                    r = set_radio(lab, cand, quiet_notfound=True,  # Ashby-style radio rendering
                                  strict=strict)
                    if r == NOTFOUND:
                        break                                 # not on this form — next phrasing
                hit = True
                if r == 0:
                    rc = "OK"
                    break
                rc = "FAIL"
            if hit:
                break
        done.append((labels[0], val, rc))
    pronoun = (defaults.get("select") or {}).get("Pronouns")
    if pronoun:
        try:
            combobox_pick("pronoun", pronoun, quiet_notfound=True)
        except Exception:  # noqa: BLE001
            pass
    return done


# Label ALIASES for the defaults pass (2026-08-15). `_resolve` matches a field whose visible
# label CONTAINS the target string, which is directionally wrong for short labels: the default
# key "Full name" cannot match a field simply labelled "Name", so Linear's Ashby form left the
# required Name field EMPTY and the orchestrator aborted the submit over it. Each entry maps a
# defaults key to shorter/alternate labels to try when the primary misses. Ordered
# most-specific-first, and only consulted on NOTFOUND, so a form that does have the precise
# label is unaffected.
_LABEL_ALIASES = {
    "full name": ["name", "legal name", "full legal name"],
    # ⛔ ALIASES FROM A REAL BLOCK LIST (2026-08-16). drain23 left 68 of 74 postings at
    # needs_human, and a chunk of the blocking fields were ones the config ALREADY answers —
    # they just carry a different wording. "Preferred Last Name/Surname" and "Zip Code/Postal
    # Code" were among the most frequent blockers in that run, while apply-defaults holds
    # "Last name" and "Postal". Nothing is invented here: the alias only changes which LABEL
    # the existing, config-supplied value binds to (config-routing model, AGENTS.md §PII).
    "first name": ["preferred first name", "given name", "forename", "legal first name"],
    "last name": ["preferred last name", "surname", "family name", "legal last name",
                  "preferred last name/surname"],
    "postal": ["postcode", "postal code", "zip code", "zip code/postal code", "zip"],
    "linkedin": ["linkedin profile", "linkedin url", "your linkedin url", "linkedin.com"],
    "portfolio": ["website/portfolio", "portfolio url", "website"],
    "website": ["website/portfolio", "personal website"],
    "phone": ["phone number", "mobile", "telephone"],
    "city": ["location", "where are you located", "current location", "town", "town/city",
             "city/town"],
    "location": ["city", "where are you located", "current location"],
    # "Legal Address" blocked iFIT's submit as a required field while apply-defaults held the
    # value the whole time under "Address line 1" (2026-08-17). Same class as the
    # preferred-surname and zip-code misses above: the config answers it, the label differs.
    "address line 1": ["legal address", "address", "street address", "address 1",
                       "home address", "address line one"],
    "postal": ["postcode", "postal code", "zip code", "zip code/postal code", "zip"],
}


def _fill_with_aliases(label, value, quiet_notfound=True):
    """fill() the default `label`, falling back to its known aliases on NOTFOUND.
    Returns the primitive's rc (NOTFOUND only if no alias matched either).

    Signature-compatible with `fill` — the `_run_defaults` helpers in atsform.apply() and
    ashby.apply() call every primitive as `fn(label, value, quiet_notfound=True)`, so this
    must accept that kwarg to be a drop-in. (It is always a quiet lookup in practice: a
    default that isn't on this form is expected, not an error.)"""
    rc = fill(label, value, quiet_notfound=True)
    if rc != NOTFOUND:
        return rc
    for alt in _LABEL_ALIASES.get(label.strip().lower(), []):
        rc = fill(alt, value, quiet_notfound=True)
        if rc != NOTFOUND:
            print(f"  (matched {label!r} via alias {alt!r})")
            return rc
    return NOTFOUND


# Enumerate every UNANSWERED field with its FULL question text. Deliberately separate from
# ashby.check(), which truncates labels to 30-45 chars for human display — a truncated question
# is useless for a screener-bank lookup ("What is your current right-to-work stat…").
_UNANSWERED = r"""
(() => {
  const clean = s => (s||'').replace(/\s+/g,' ').trim();
  const out = {texts: [], radios: [], combos: []};
  // ⛔ CLEAR LAST PASS'S TAGS FIRST (2026-08-16). Indices are assigned fresh on every call
  // (0,1,2… in DOM order) but the attribute was never removed, and a field ANSWERED by the
  // previous pass is skipped here (`i.value` is set) so it never gets re-tagged — it just
  // keeps its stale tag. Two elements then carry data-ats-gap="0", and the filler's
  // querySelector('[data-ats-gap="0"]') takes the FIRST in DOM order: the already-answered
  // one. A second gap-fill pass therefore OVERWRITES a correctly-answered field with the
  // answer belonging to a different question. gh_apply and lever both run this pass more
  // than once per form (before the review screenshot, and again after a re-render).
  document.querySelectorAll('[data-ats-gap]').forEach(e => e.removeAttribute('data-ats-gap'));
  document.querySelectorAll('[data-ats-combo]').forEach(e => e.removeAttribute('data-ats-combo'));
  for (const i of document.querySelectorAll(
      'input[type=text],input[type=email],input[type=tel],input[type=number],input[type=url],textarea')) {
    if (i.name === 'g-recaptcha-response' || i.value) continue;
    // ⛔ A COMBOBOX'S INPUT IS NOT A TEXT FIELD (2026-08-16). react-select renders its
    // control as <input type="text" role="combobox">, so every dropdown on the form also
    // showed up in `texts`. That was harmless while the text branch just tried a fill, but
    // once the branch started honouring the bank row's `kind` it began REFUSING them —
    // "banked answer is kind='radio', not free text" — on Right to Work, Source of Right to
    // Work and Self-Identification of Gender, leaving required fields empty and blocking the
    // submit (seen live on Twilio). The `combos` list below already owns these controls and
    // routes them through combobox_pick, which is the primitive that can actually commit a
    // selection. Claim them there, not here.
    if (i.getAttribute('role') === 'combobox' ||
        i.getAttribute('aria-autocomplete') === 'list' ||
        i.closest('[class*="select__control"],[class*="-control"]')) continue;
    let lbl = clean(i.labels && i.labels[0] ? i.labels[0].innerText : '');
    // ⛔ CAP THE ANCESTOR BLOB (2026-08-16). Uncapped, the first ancestor with ANY text is
    // often a section wrapper holding SEVERAL questions, so `lbl` became a blob containing a
    // NEIGHBOUR's question text. screener.lookup then matched the neighbour's pattern and its
    // answer was typed into THIS field. The combobox branch below already caps at 220; the
    // text branch never did. Keep climbing past over-long ancestors instead of taking them.
    if (!lbl) { let b = i; for (let k = 0; k < 4 && b; k++) { b = b.parentElement;
      if (b) { const t = clean(b.innerText);
               if (t && t.length <= 220) { lbl = t; break; } } } }
    // ⛔ TAG THE ELEMENT, don't just report its label (2026-08-15). fill_gaps_from_bank used
    // to call fill(label), which re-resolves by label and returns the FIRST match — so on a
    // form carrying the SAME label twice (Lever posts a "Full Name" input AND a separate
    // required "Full Name" card textarea) the gap-filler kept re-resolving to the input it
    // had already filled and the required textarea stayed empty forever, aborting the submit.
    // Marking each unanswered element gives the filler an exact address for THIS field.
    if (lbl) { i.setAttribute('data-ats-gap', String(out.texts.length));
               out.texts.push(lbl.slice(0, 220)); }
  }
  // UNANSWERED COMBOBOXES (2026-08-15). react-select renders its chosen value as a
  // `singleValue`/`multi-value` node inside the control; an empty one shows only the
  // placeholder. These were invisible to this pass, so a banked answer for e.g. Greenhouse's
  // "Location (City)" or "Do you require visa sponsorship" was applied as a TEXT fill — which
  // writes into the search box without ever committing a selection, so the field still
  // reported "Please enter your location" and bounced the submit.
  const seenCombo = new Set();
  for (const ctrl of document.querySelectorAll('[class*="select__control"],[class*="-control"]')) {
    if (ctrl.querySelector('[class*="singleValue"],[class*="multi-value"],[class*="multiValue"]')) continue;
    // ⛔ CLIMB PAST THE CONTROL'S OWN TEXT (2026-08-16). An EMPTY react-select renders the
    // placeholder "Select...", so the first ancestor with text is the control itself and this
    // walk returned q = "Select..." for every unanswered dropdown. screener.lookup("select...")
    // matches nothing, so the bank reported "0 answered, N unknown" on a form where it held
    // every answer — measured live on Dotmatics: 7 unknown, all 7 banked. The bank has
    // therefore never been able to answer a Greenhouse dropdown whose label sits above the
    // control, which is most of them. Same defect set_radio (qtext) and the text branch were
    // each fixed for; the combo branch was missed both times. Subtract the control's own text
    // before judging an ancestor, exactly as those do.
    const own = clean(ctrl.innerText);
    let box = ctrl, q = '';
    for (let k = 0; k < 6 && box; k++) { box = box.parentElement;
      if (!box) break;
      let t = clean(box.innerText);
      if (!t || t.length >= 220) continue;
      if (own) { const stripped = t.split(own).join(' ').replace(/\s+/g, ' ').trim();
                 if (stripped.length < 3) continue; t = stripped; }
      q = t; break; }
    if (!q) continue;
    // ⛔ TAG THE CONTROL, AND DO NOT DEDUPE BY LABEL (2026-08-16). Two fields can share a
    // label: Dotmatics' Greenhouse form has TWO marked "Country*" — the phone dialling-code
    // selector (already "+44") and the application's own Country question (empty, required).
    // Reporting only the question TEXT meant the filler called combobox_pick("Country"),
    // which resolves to the FIRST match — the phone one — so the required field stayed empty
    // and the submit bounced on "This field is required." with no indication which field.
    // `seenCombo` made it worse by dropping the second one from the list entirely.
    // Text fields were given per-element addressing (data-ats-gap) for exactly this reason;
    // comboboxes never were. Same fix: mark the control and let the filler address IT.
    ctrl.setAttribute('data-ats-combo', String(out.combos.length));
    out.combos.push({q: q.slice(0, 220), sel: '[data-ats-combo="' + out.combos.length + '"]'});
  }
  const groups = {};
  for (const r of document.querySelectorAll('input[type=radio]')) (groups[r.name] ||= []).push(r);
  for (const rs of Object.values(groups)) {
    if (rs.some(r => r.checked)) continue;
    const opts = rs.map(r => clean(r.labels && r.labels[0] ? r.labels[0].innerText
                                  : (r.nextElementSibling ? r.nextElementSibling.innerText : r.value)));
    // Same walk-past-the-options-container fix as set_radio's qtext (2026-08-16): the first
    // ancestor with >8 chars is usually the div wrapping the CHOICES ("Yes No Prefer not to
    // say"), so `q` became the option list instead of the question. screener.lookup("yes no")
    // matches nothing, so the group was reported with a useless question and never answered.
    // Subtract this group's own option labels before judging an ancestor.
    let box = rs[0];
    for (let k = 0; k < 8 && box; k++) { box = box.parentElement;
      if (!box) break;
      let t = clean(box.innerText); if (!t) continue;
      for (const o of opts) if (o) t = t.split(o).join(' ');
      if (clean(t).length > 8) break; }
    const q = clean(box ? box.innerText : '');
    if (q) out.radios.push({q: q.slice(0, 220), opts: opts.filter(Boolean).slice(0, 12)});
  }
  return JSON.stringify(out);
})()
"""


def fill_gaps_from_bank():
    """Answer every still-unanswered field from the SHARED screener bank (screener.py).

    WHY THIS EXISTS (2026-08-15). screener.py's own docstring said "apply_ea.py had a
    hardcoded LinkedIn-only KNOWN map; **atsform had nothing**" — and that was still literally
    true: neither atsform.apply() nor ashby.apply() ever imported it, so the persistent,
    learnable answer bank only helped LinkedIn Easy Apply, the one lane SKILL.md forbids
    logging. Every hard-board form therefore re-hit the SAME handful of gating questions
    (salary expectation, right-to-work, sponsorship, notice, time zone) with no answer, and
    the orchestrator aborted the submit over questions already answered in the CSV.
    Measured on one Ashby drain: 6 of 6 postings aborted, and salary-expectation alone
    accounted for 4 of them — while `screener-answers.csv` had held the answer since July.

    Runs AFTER config + defaults (so an explicit answer always wins) and BEFORE the pre-submit
    check. Only fills what is still EMPTY, and only where the bank has a match — an unknown
    question stays unanswered and still blocks the submit, which is the correct behaviour.
    Returns (filled, skipped)."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import screener  # noqa: PLC0415 — optional dependency of this one pass
    except ImportError:
        return (0, 0)
    try:
        data = json.loads(cfx.evaluate(_UNANSWERED))
    except (ValueError, TypeError, cfx.CfxError):
        return (0, 0)
    filled = skipped = 0
    for idx, label in enumerate(data.get("texts", [])):
        hit = screener.lookup(label)
        if not hit:
            skipped += 1
            continue
        # ⛔ A RADIO ANSWER IS NOT FREE TEXT (2026-08-16). The bank stores a `kind` per row and
        # this branch ignored it, so a row banked for a yes/no CHOICE ("right to work" ->
        # "Yes") would be TYPED into a free-text box whose question merely contains the same
        # phrase — e.g. "Describe your right to work status" receives the literal string
        # "Yes". That is a nonsense answer a human reviewer reads, not a blocked field.
        # Choice-kind answers only belong in the radio/combo branches below.
        if (hit.get("kind") or "text").strip().lower() in ("radio", "select", "checkbox"):
            print(f"  bank SKIP {label[:46]!r}: banked answer is kind="
                  f"{hit.get('kind')!r} (a choice), not free text — left unanswered")
            skipped += 1
            continue
        # Address THIS element (see the data-ats-gap note in _UNANSWERED) rather than
        # re-resolving by label, which returns the first match and re-fills a done field.
        rc = fill(f'[data-ats-gap="{idx}"]', hit["answer"], quiet_notfound=True)
        if rc != 0:
            rc = fill(label, hit["answer"], quiet_notfound=True)   # legacy path, just in case
        if rc == 0:
            print(f"  bank: {label[:52]!r} <- {hit['answer'][:40]!r} ({hit['source']})")
            filled += 1
        else:
            skipped += 1
    for entry in data.get("combos", []):
        # entry is {q, sel} since 2026-08-16 (per-element addressing); tolerate the old
        # bare-string shape so a stale cached payload cannot crash a live run.
        q = entry.get("q") if isinstance(entry, dict) else entry
        sel = entry.get("sel") if isinstance(entry, dict) else None
        hit = screener.lookup(q)
        if not hit:
            skipped += 1
            continue
        # combobox_pick only ever selects an option that MATCHES, so a banked value that is
        # wrong for this widget simply finds nothing and the field stays empty (closed-set
        # rule) — never a guessed selection.
        # Address the marked CONTROL, not the label — two fields can share a label and
        # label-resolution returns the first, which may be a different (already-answered)
        # field. Fall back to the label only if the marker is somehow gone.
        rc_combo = combobox_pick(sel, hit["answer"], quiet_notfound=True) if sel else NOTFOUND
        if rc_combo != 0:
            rc_combo = combobox_pick(q, hit["answer"], quiet_notfound=True)
        if rc_combo == 0:
            print(f"  bank combo: {q[:52]!r} <- {hit['answer'][:40]!r} ({hit['source']})")
            filled += 1
        else:
            skipped += 1
    for grp in data.get("radios", []):
        q, opts = grp.get("q", ""), grp.get("opts") or []
        hit = screener.lookup(q)
        if not hit:
            skipped += 1
            continue
        ans = hit["answer"]
        # ⛔ THE BANK ANSWER MUST BE ONE OF THIS FORM'S OPTIONS (2026-08-15).
        # screener.py matches patterns by SUBSTRING, which is fine for the yes/no gating
        # questions it was built for but dangerous once every hard board consults it: the row
        # `bachelor,radio,Yes` (meant for "do you have a bachelor's degree?") also matches
        # "What was your bachelor's university degree RESULT, or equivalent?" — a question
        # whose honest answer is a classification, not "Yes". Caught live on a Greenhouse form,
        # where this pass had already pushed "Yes" into it.
        # A radio's options are a CLOSED SET, so validate against them: answer only when the
        # bank value maps to a real option (exact, then whole-word/containment). If nothing
        # maps, leave it EMPTY — an unanswered required field blocks the submit and asks for a
        # human, which is the correct outcome; a confidently wrong answer is not.
        low = ans.strip().lower()
        # ⛔ AN EMPTY BANKED ANSWER IS NOT A MATCH (2026-08-16). With `low` empty the
        # word-boundary regex below degenerates to `(^|[^a-z0-9])([^a-z0-9]|$)`, which matches
        # any option containing a space or punctuation — so a blank/whitespace bank cell
        # sailed past this closed-set guard and SELECTED THE FIRST PUNCTUATED OPTION. The
        # guard exists precisely to stop confident wrong answers; an empty answer is the least
        # justified of all.
        if not low:
            skipped += 1
            continue
        # ⛔ NEVER SIGN AN ANTI-AI OATH FROM THE BANK (2026-08-16). combobox_pick refuses these
        # (see _is_anti_ai_oath) but set_radio had no such guard, and this branch calls
        # set_radio directly — so an "I confirm this application is entirely my own words / not
        # AI-generated" question rendered as RADIOS was answered "Yes" by whatever generic
        # affirmative row the bank matched. SKILL.md: attestations are the applicant's to sign.
        # Same country-scope guard as the config gate: the bank's right-to-work answers are
        # UK-scoped, and asserting them about another country is a false eligibility claim.
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from precheck import foreign_work_authorisation  # noqa: PLC0415
            _foreign = foreign_work_authorisation(q)
        except Exception:  # noqa: BLE001
            _foreign = None
        if _foreign:
            print(f"  bank REFUSE {q[:56]!r}: asks about work authorisation for "
                  f"{_foreign}, not the UK — the banked answer would be false")
            skipped += 1
            continue
        if _is_anti_ai_oath(q) and _is_affirmative(ans):
            print(f"  bank REFUSE {q[:60]!r}: anti-AI attestation — not signing an "
                  f"'own words / no AI' oath on the applicant's behalf")
            skipped += 1
            continue
        match = next((o for o in opts if o.strip().lower() == low), None) \
            or next((o for o in opts if re.search(
                r"(^|[^a-z0-9])" + re.escape(low) + r"([^a-z0-9]|$)", o.strip().lower())), None)
        if not match:
            if opts:
                print(f"  bank SKIP {q[:46]!r}: banked {ans[:20]!r} is not one of this "
                      f"form's options {opts[:4]} — left unanswered on purpose")
            skipped += 1
            continue
        if set_radio(q, match, quiet_notfound=True) == 0:
            print(f"  bank: {q[:52]!r} <- {match[:40]!r} ({hit['source']})")
            filled += 1
        else:
            skipped += 1
    if filled or skipped:
        print(f"screener bank: {filled} answered, {skipped} unknown "
              f"(teach one with: screener.py learn)")
    return (filled, skipped)


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

    # DEDUP GUARD (the ONE gate for every ATS driven through this generic orchestrator —
    # lever/recruitee/smartrecruiters/hibob/workable/talentlink/… — none of which have a
    # board-specific driver that guards). apply() runs on an already-navigated form that bypassed
    # the sourcing precheck, so re-check the live tracker before filling/submitting a role already
    # Applied. Matches the current URL's canonical id, then the config's Company+Role. Only
    # "Applied"/"Applied?" skips (Blocked/Saved stay re-drivable); `"force": true` re-drives.
    if not cfg.get("force"):
        try:
            cur_url = cfx.current_url()
        except Exception:  # noqa: BLE001
            cur_url = ""
        hit = precheck.already_applied(url=cur_url or cfg.get("url"),
                                       company=cfg.get("company"), role=cfg.get("role"))
        if hit and precheck.is_applied(hit[0]):
            print(f"SKIP_ALREADY_APPLIED {cfg.get('company')} | {cfg.get('role')} — "
                  f"tracker={hit[0]} (matched {hit[1]}). Pass \"force\": true to re-drive.")
        # ⛔ NOT rc=0 (2026-08-16). Returning the SUCCESS code for a posting we did not
        # apply to made apply_queue tally it under `applied`: drain23 reported
        # "applied: 1" with ZERO real submissions, the count coming entirely from one
        # already-applied Saviynt row. That is the count-integrity failure SKILL.md
        # warns about, arriving through the tally instead of the tracker. rc=6 =
        # "skipped, already applied": not a success, not a failure.
            return 10

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
    # Alias-aware: the "Full name" default must still bind a field labelled just "Name".
    _run_defaults("fill", "fill", _fill_with_aliases)
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

    # Truthful checkbox auto-fill — tick ONLY affirmatively-true boxes; leave marketing / anti-AI
    # / unknown / false ones unticked (and report them). This REPLACES the old blanket tick-all,
    # which was both an integrity regression (it ticked anti-AI/marketing/false boxes) AND dead
    # code (its JS had a misplaced `return` -> SyntaxError, silently swallowed here). The truthful
    # engine already lives in this module — call it, don't re-roll a click-every-box loop.
    try:
        rep = checkboxes_from_profile()
        if rep.get("ticked"):
            print(f"OK  truthfully ticked {len(rep['ticked'])} checkbox(es)")
        for cat in ("left_false", "left_unknown", "left_marketing", "left_antiai"):
            if rep.get(cat):
                print(f"  left unticked [{cat[5:]}]: {', '.join(rep[cat])[:120]}")
    except Exception as e:  # noqa: BLE001 — truthful auto-fill is best-effort, never blocks apply
        print(f"  checkbox auto-fill note: {str(e)[:80]}")

    # LAST fill pass: answer anything still empty from the shared, learnable screener bank.
    # After config + defaults (explicit always wins), before the review.
    try:
        fill_gaps_from_bank()
    except Exception as e:  # noqa: BLE001 — a bank miss must never block an otherwise-good form
        print(f"  screener-bank note: {str(e)[:80]}")

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

    # ⛔ HONOUR do_submit (2026-08-15). This block used to run whenever the fill was clean,
    # ignoring the parameter entirely — so `apply(cfg, do_submit=False)` SUBMITTED. gh_apply
    # calls exactly that to batch-fill before its own EEO/combo/screener passes, and a config
    # carrying `"no_submit": true` (the read-only probe path) went the same way. A caller that
    # explicitly asks not to submit must never submit: that is the difference between a dry
    # inspection pass and an irreversible application sent with half the form filled.
    if not do_submit or cfg.get("no_submit"):
        print("--- filled; NOT submitting (do_submit=False / no_submit) ---")
        return 0
    # Submit automatically when everything is clean (user authorised auto-submit).
    sub = cfg.get("submit")
    sub = sub or {}
    print("--- auto-submitting ---")
    return submit(sub.get("button", "Submit"),
                  sub.get("success") or
                  "successfully submitted|application (received|sent)|thank you|we're rooting")


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
