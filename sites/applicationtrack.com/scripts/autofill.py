#!/usr/bin/env python3
"""autofill.py — tracker-driven auto-filler for applicationtrack.com (VacancyFiller) eforms.

The STRUCTURAL fix for the GCHQ-3780 class of failure. Where a hand-driving agent can
rabbit-hole on a hidden field and loop forever, this driver makes that impossible BY
CONSTRUCTION:

  1. It walks the SECTION TRACKER, never a field list — the incomplete sections are the
     work-list, read fresh each pass (same probes as diagnose.py).
  2. It fills only the culprit fields the SITE names (`a.eform-jump-to-field`), resolving
     each answer from a profile ruleset (references/applicant-profile.md).
  3. It SKIPS hidden (`display:none`) fields by construction — never sets, never forces
     visible, never "fights the render loop". A hidden field is recorded and ignored.
  4. It CANNOT LOOP: a per-pass progress guard aborts the moment a full pass fails to
     reduce the incomplete-section set AND fills nothing new. Plus a hard pass cap.
  5. It NEVER submits and NEVER fabricates: unmatched culprits, and the user-only final
     page (memorable word / hint / declaration), are reported as `needs_human` — the run
     stops and hands them to the user, it does not guess.

Usage:
    CFX_KEY=... CFX_TAB=<eform tab> python3 sites/applicationtrack.com/scripts/autofill.py
        [--dry]        # classify + report what WOULD be filled; change nothing
        [--once]       # a single pass (no loop) — useful for inspection
        [--selftest]   # prove the guarantees against a mock DOM + pure functions (no live app)

Exit codes: 0 = all content sections complete (ready for the user's final page);
            1 = stopped with unresolved `needs_human` culprits (reported); 2 = setup error.

The ruleset covers high-confidence factual eligibility/screener gates (citizenship, age, UK
residency, apprenticeship, jobshare, bankruptcy, willingness to be vetted) PLUS config-routed
APPLICANT birth/nationality values (Country / County / Town of birth, nationality at birth,
dual nationality) read from the gitignored apply-defaults.json `applicant` block — the
applicant's OWN Personal-Details fields ONLY. A hard family-field guard NEVER fills a
Father's/Mother's/parent field with the applicant's value (the vetting-form correctness
invariant), and family free-text + the final page stay `needs_human`. Everything else is
`needs_human` — never fabricated. Extend RULES/VALUE_RULES only with verifiably-true facts;
add new applicant values to the config `applicant` block (+ the .example), never to the driver.
"""
import json
import os
import re
import sys
import time

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_here, "..", "..", "_common", "scripts"))
import cfx  # noqa: E402

# Reuse the exact section/culprit probes the diagnostic ships — one detector, no drift.
import importlib.util  # noqa: E402
_spec = importlib.util.spec_from_file_location("at_diagnose", os.path.join(_here, "diagnose.py"))
_diagnose = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_diagnose)  # importing does not run main() (guarded by __main__)
SECTIONS_JS = _diagnose.SECTIONS_JS
CULPRITS_JS = _diagnose.CULPRITS_JS

# --- Answer ruleset (grounded in references/applicant-profile.md — the applicant) --------
# (question-text regex, answer token). Tokens: 'Yes' / 'No' / 'agree'. Order matters —
# first match wins. Keep this to FACTS THAT ARE TRUE; anything not matched is needs_human.
RULES = [
    (r"british citizen|are you a british|hold british citizenship", "Yes"),
    (r"\bover (16|17|18)\b|are you over|(16|17|18) years of age|aged 18 or over", "Yes"),
    (r"lived in the uk|resided in the uk|residenc|7 (of|out of) the last 10|uk for \d+ of", "Yes"),
    (r"free to (remain|take up employment)|free to remain and take", "Yes"),
    # ONLY the "different?" phrasing -> "No". The old rule also matched "...the same?" and still
    # answered "No", which INVERTS it (correspondence IS the applicant's home address), so a
    # "same as your home address?" question falsely said "different". That phrasing now falls
    # through to needs_human rather than auto-answering wrong on a vetting form.
    (r"correspondence address.*different|is your correspondence address different", "No"),
    (r"agree to the terms|security vetting.*(agree|terms)|i agree to (the|these)", "agree"),
    (r"undischarged bankrupt|are you bankrupt", "No"),
    (r"completed an apprenticeship|since 2010.*apprenticeship|apprenticeship\?", "No"),
    (r"jobshare|job share|applying as a job", "No"),
]

# --- Config-routed APPLICANT values (birth/nationality Personal-Details fields) -----------
# The applicant's OWN birth/nationality facts live in the gitignored apply-defaults.json
# `applicant` block (AGENTS.md config-routing — the tracked driver holds NO personal values).
# VALUE_RULES map a culprit question to an `applicant`-block KEY; an absent value ⇒ needs_human
# (never fabricated). ⛔ A hard family-field guard means a Father's/Mother's/parent field is
# NEVER filled with the APPLICANT's value (the vetting-form correctness invariant).
_FAMILY_Q = re.compile(r"father|mother|parent|spouse|partner|guardian|next of kin|sibling|"
                       r"child|dependant|dependent", re.I)
VALUE_RULES = [
    (r"country (where|in which) you (were|was) born|country of birth", "country_of_birth"),
    (r"county (in which )?you (were|was) born|county of birth", "county_of_birth"),
    (r"town.*(where|in which) you (were|was) born|town/?\s*city of birth", "town_of_birth"),
    (r"nationality at birth", "nationality_at_birth"),
    (r"do you (currently )?(have|hold) british nationality", "holds_british_nationality"),
    (r"do you hold dual nationality|any other nationality or citizenship( other)?", "dual_nationality"),
    (r"please give\b.*dual nationality|which.*dual national", "other_nationality"),
    (r"resided outside.*uk.*(10|ten)|lived outside the uk.*(10|ten)|outside of the uk over the past 10", "resided_outside_uk_10yrs"),
]


def _applicant():
    """The gitignored applicant config block (birth/nationality/demographics), or {}."""
    try:
        cfg = os.path.join(_here, "..", "..", "_common", "apply-defaults.json")
        return json.load(open(cfg, encoding="utf-8")).get("applicant", {}) or {}
    except Exception:  # noqa: BLE001
        return {}


def resolve_value(question):
    """Config-routed VALUE for the applicant's OWN birth/nationality Personal-Details fields.
    Returns the config value string, or None (⇒ needs_human) when the question is a FAMILY
    field, is user-only free-text, is unmatched, or the value is absent from the config.
    Never fabricates; never fills a parent's field with the applicant's data."""
    q = (question or "").strip()
    if not q or _FAMILY_Q.search(q) or USER_ONLY.search(q):
        return None
    app = _applicant()
    for pat, key in VALUE_RULES:
        if re.search(pat, q, re.I):
            v = str(app.get(key) or "").strip()
            return v or None
    return None

# Guardrails: questions we must NEVER auto-answer (personal secret / legal declaration /
# free-text competency). These are user-only even if a rule pattern grazes them.
USER_ONLY = re.compile(
    r"memorable word|declaration|declare|true and complete|personal statement|"
    r"please (specify|describe|provide details|give details)|hint|why (do|are) you",
    re.I,
)


def resolve_answer(question):
    """Pure: map a culprit question to an answer token, or None if we won't answer it.
    None => needs_human (never guessed). USER_ONLY always => None."""
    q = (question or "").strip()
    # _FAMILY_Q guard too (not just USER_ONLY): every RULE below is about the APPLICANT, but
    # `_resolve = resolve_answer() or resolve_value()` short-circuits, so without this a family
    # question ("Is your partner a British citizen?", "Has your father lived in the UK?") matches
    # an applicant RULE and fills a FAMILY member's vetting field with the applicant's answer —
    # bypassing the family-field invariant that resolve_value() enforces. Family Qs => needs_human.
    if not q or USER_ONLY.search(q) or _FAMILY_Q.search(q):
        return None
    for pat, token in RULES:
        if re.search(pat, q, re.I):
            return token
    return None


# --- Fill primitives (IIFE expression form — camofox /evaluate needs an expression) ------

def _fill_radio(name, token):
    js = (
        "(function(){var els=[...document.querySelectorAll(\"input[name='%s']\")];"
        "if(!els.length)return 'NO_FIELD';"
        "var tok=%s.toLowerCase();"
        "function lab(r){return (r.labels&&r.labels[0]?r.labels[0].innerText:'').toLowerCase();}"
        "var want=els.find(function(r){var l=lab(r);"
        "  if(tok==='yes')return /^\\s*yes\\b/.test(l);"
        "  if(tok==='no')return /^\\s*no\\b/.test(l);"
        "  if(tok==='agree')return l.indexOf('agree')>-1 && l.indexOf('not agree')<0 && l.indexOf('do not')<0;"
        "  return l.indexOf(tok)>-1;});"
        "if(!want)return 'NO_OPTION';want.click();return want.checked?'OK':'CLICK_NOEFFECT';})()"
    ) % (name, json.dumps(token))
    return cfx.evaluate(js)


def _fill_select(name, token):
    js = (
        "(function(){var s=document.querySelector(\"select[name='%s']\");if(!s)return 'NO_FIELD';"
        "var tok=%s.toLowerCase();"
        "var opt=[...s.options].find(function(o){var t=o.text.trim().toLowerCase();"
        "  if(tok==='yes')return t==='yes';if(tok==='no')return t==='no';"
        "  if(tok==='agree')return t.indexOf('agree')>-1 && t.indexOf('not agree')<0;"
        "  return t.indexOf(tok)>-1;});"
        "if(!opt)return 'NO_OPTION';s.value=opt.value;"
        "s.dispatchEvent(new Event('change',{bubbles:true}));"
        "return s.value===opt.value?'OK':'SET_NOEFFECT';})()"
    ) % (name, json.dumps(token))
    return cfx.evaluate(js)


def _fill_text(name, value):
    """Set a text INPUT via the native value-setter (VacancyFiller reads the model on change).
    Used ONLY for config-resolved structured fields (e.g. town of birth) — never arbitrary
    free-text. Returns 'OK' / 'SET_NOEFFECT' / 'NO_FIELD'."""
    js = (
        "(function(){var e=document.querySelector(\"input[name='%s']\");if(!e)return 'NO_FIELD';"
        "var set=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;"
        "set.call(e,%s);e.dispatchEvent(new Event('input',{bubbles:true}));"
        "e.dispatchEvent(new Event('change',{bubbles:true}));"
        "return e.value===%s?'OK':'SET_NOEFFECT';})()"
    ) % (name, json.dumps(value), json.dumps(value))
    return cfx.evaluate(js)


def _resolve(question):
    """Unified answer resolution: an eligibility-gate token (Yes/No/agree) OR a config-routed
    APPLICANT birth/nationality value, or None (⇒ needs_human). Gates take precedence."""
    return resolve_answer(question) or resolve_value(question)


def _save_and_continue():
    js = (
        "(function(){var b=[...document.querySelectorAll('input[type=submit],button[type=submit],button')]"
        ".find(function(e){var t=(e.value||e.innerText||'').trim().toLowerCase();"
        "return e.name==='continue_button'||t==='save and continue'||t==='continue';});"
        "if(!b)return 'NO_BTN';b.click();return 'CLICKED';})()"
    )
    try:
        return cfx.evaluate(js)
    except cfx.CfxError:
        return "EVAL_ERR"


def _read(js, tries=3):
    for _ in range(tries):
        try:
            v = cfx.evaluate(js)
            if v is not None:
                return v
        except cfx.CfxError:
            pass
        time.sleep(1.2)
    return None


def _sections():
    raw = _read(SECTIONS_JS)
    return json.loads(raw) if raw else []


def _culprits():
    raw = _read(CULPRITS_JS)
    return json.loads(raw) if raw else []


def _submit_ready():
    return bool(_read("!!document.querySelector('button[name=submit_button],input[name=submit_button]')"))


# Settle between intra-section fill rounds: lets a DEPENDENT select's options populate after
# its parent is set (e.g. County only lists options once Country is chosen), and lets a
# reverted value re-surface as a culprit so the next round re-fills it.
_SETTLE = 1.5


# --- One section: classify + (optionally) fill its named culprits ------------------------

def process_section(section, dry=False, rounds=3):
    """Navigate to a section, fill the resolvable non-hidden culprits, and return a report.
    Records — filled / skipped_hidden / needs_human — but never touches a hidden field and
    never fabricates an answer.

    PER-SECTION VERIFY + DEPENDENT-SELECT HARDENING (2026-07-18): instead of filling each
    culprit ONCE and advancing, it re-reads the SITE's culprit list up to `rounds` times,
    re-filling any resolvable culprit the site still flags. This fixes two real MI5/GCHQ
    stalls: (a) a DEPENDENT select (County depends on Country) whose options aren't populated
    until its parent is set — round 1 sets Country, the settle lets County populate, round 2
    sets County; and (b) a value that reverts on the framework's re-render — it re-appears as
    a culprit and gets re-filled. A field that DROPS OFF the culprit list is confirmed
    committed (the site's own completeness check), so we advance only when no resolvable
    culprit remains. An intra-section no-progress guard (same pending set two rounds running)
    prevents any loop, in addition to the outer pass cap."""
    rep = {"section": section["section"], "filled": [], "skipped_hidden": [], "needs_human": []}
    if section.get("href"):
        try:
            cfx.navigate(section["href"])
            time.sleep(3)
        except cfx.CfxError as e:
            rep["needs_human"].append({"field": "?", "why": f"could not open section: {e}"})
            return rep

    filled_fields, recorded_hidden, last_fail = set(), set(), {}
    prev_pending = None
    for rnd in range(max(1, rounds)):
        pending = []
        for c in _culprits():
            field = c.get("field", "?")
            if c.get("hidden"):
                # Skip-by-construction: a display:none field is never the blocker.
                if field not in recorded_hidden:
                    rep["skipped_hidden"].append({"field": field, "question": c.get("question", "")})
                    recorded_hidden.add(field)
                continue
            if _resolve(c.get("question", "")) is None:
                continue  # unresolvable → needs_human, handled after the rounds
            pending.append(c)          # site STILL flags it as incomplete this round
        pend_fields = sorted(c.get("field") for c in pending)
        if not pending:
            break                       # every resolvable culprit is committed
        if rnd > 0 and pend_fields == prev_pending:
            break                       # intra-section no-progress guard — stop retrying
        prev_pending = pend_fields
        for c in pending:
            field, typ, q = c.get("field"), c.get("type"), c.get("question", "")
            token = _resolve(q)
            if dry:
                if field not in filled_fields:
                    rep["filled"].append({"field": field, "answer": token, "type": typ, "dry": True})
                    filled_fields.add(field)
                continue
            if typ == "radio":
                r = _fill_radio(field, token)
            elif c.get("tag") == "SELECT" or typ in ("select-one", "select"):
                r = _fill_select(field, token)
            elif typ == "text" and resolve_value(q) is not None and resolve_answer(q) is None:
                # A config-resolved STRUCTURED text field (e.g. town of birth) — never an
                # arbitrary free-text culprit (those stay user-only below).
                r = _fill_text(field, token)
            else:
                r = "NON_RADIO_SELECT"   # free-text / textarea / checkbox — user-only
            if r == "OK":
                if field not in filled_fields:
                    rep["filled"].append({"field": field, "answer": token, "type": typ})
                    filled_fields.add(field)
            else:
                last_fail[field] = r     # NO_OPTION on a select ⇒ likely dependent; retry next round
        if dry:
            break
        time.sleep(_SETTLE)              # dependent selects populate / reverts re-surface

    # After the rounds, anything the site STILL flags (visible) is unresolved → needs_human,
    # with a hint when it looks like a dependent-select ordering problem.
    for c in _culprits():
        field = c.get("field", "?")
        if c.get("hidden") or field in filled_fields:
            continue
        q, typ = c.get("question", ""), c.get("type")
        if _resolve(q) is None:
            rep["needs_human"].append({"field": field, "question": q, "type": typ})
        else:
            lf = last_fail.get(field, "?")
            why = f"fill={lf}"
            if lf == "NO_OPTION":
                why += " — dependent select? set its PARENT first (e.g. Country before County), let its options populate, then retry"
            rep["needs_human"].append({"field": field, "question": q, "type": typ, "why": why})

    if not dry and rep["filled"]:
        _save_and_continue()
        time.sleep(4)
    return rep


# --- Main tracker-driven loop with the anti-loop progress guard --------------------------

def run(dry=False, once=False):
    secs = _sections()
    if not secs:
        print("ERROR: no section tracker on this tab — open the eform (…/candidate/eform/<ID>) "
              "and ensure you're logged in.", file=sys.stderr)
        return 2

    max_passes = len(secs) + 3          # hard cap; belt-and-braces beyond the progress guard
    prev_incomplete = None
    all_needs_human, all_hidden, all_filled = [], [], []

    for p in range(1, max_passes + 1):
        secs = _sections()
        incomplete = [s for s in secs if s["incomplete"]]
        inc_names = sorted(s["section"] for s in incomplete)
        print(f"[pass {p}] incomplete sections: {inc_names or 'none'}")

        if not incomplete:
            break

        filled_this_pass = 0
        needs_this_pass = []
        for s in incomplete:
            rep = process_section(s, dry=dry)
            filled_this_pass += len(rep["filled"])
            all_filled += [dict(section=s["section"], **f) for f in rep["filled"]]
            all_hidden += [dict(section=s["section"], **h) for h in rep["skipped_hidden"]]
            needs_this_pass += [dict(section=s["section"], **n) for n in rep["needs_human"]]

        # PROGRESS GUARD — the "literally cannot loop" guarantee.
        # If a full pass changed nothing (same incomplete set) AND filled nothing new, we
        # are provably stuck on unresolvable culprits. Stop and report; never re-loop.
        if inc_names == prev_incomplete and filled_this_pass == 0:
            all_needs_human = needs_this_pass
            print(f"[stop] no progress on pass {p} (filled 0, same incomplete set) — "
                  f"remaining culprits are unresolvable by ruleset; handing to user.")
            break
        prev_incomplete = inc_names
        all_needs_human = needs_this_pass

        if once:
            break
    else:
        print(f"[stop] hit hard pass cap ({max_passes}) — bailing to avoid any loop.")

    # De-dupe reports
    def _uniq(rows):
        seen, out = set(), []
        for r in rows:
            k = (r.get("section"), r.get("field"))
            if k not in seen:
                seen.add(k); out.append(r)
        return out

    all_filled, all_hidden, all_needs_human = _uniq(all_filled), _uniq(all_hidden), _uniq(all_needs_human)
    secs = _sections()
    remaining = sorted(s["section"] for s in secs if s["incomplete"])
    ready = _submit_ready()

    print("\n==== AUTOFILL REPORT ====")
    print(f"filled ({len(all_filled)}):")
    for f in all_filled:
        print(f"    [{f['section']}] {f['field']} = {f['answer']}" + (" (dry)" if f.get('dry') else ""))
    print(f"skipped hidden — NOT the blocker, ignored by design ({len(all_hidden)}):")
    for h in all_hidden:
        print(f"    [{h['section']}] {h['field']} :: {h.get('question','')[:60]}")
    print(f"needs_human — user must handle, NOT guessed ({len(all_needs_human)}):")
    for n in all_needs_human:
        print(f"    [{n['section']}] {n['field']} :: {n.get('question','')[:70]} {n.get('why','')}")
    print(f"\nincomplete sections remaining: {remaining or 'none'}")
    print(f"submit_button present: {ready}")
    if not remaining:
        print("→ All content sections complete. The USER-ONLY final page (memorable word + hint "
              "+ declaration + Submit) remains — hand to the applicant; this driver never submits.")
        return 0
    print("→ Stopped with unresolved sections above — fill the needs_human items (from the "
          "applicant, truthfully) or extend RULES only with verifiably-true facts.")
    return 1


# --- Self-test: prove the guarantees without a live application --------------------------

def selftest():
    import json as _json
    fails = []

    # (A) Pure answer-resolution: facts resolve; personal/unknown do NOT.
    cases = [
        ("Are you a British Citizen?", "Yes"),
        ("Are you over 17 years?", "Yes"),
        ("Have you lived in the UK for 7 of the last 10 years?", "Yes"),
        ("I agree to the terms in the above statement", "agree"),
        ("Are you an undischarged bankrupt?", "No"),
        ("Since 2010, have you successfully completed an apprenticeship?", "No"),
        ("Are you applying as a Jobshare?", "No"),
        ("Please provide a memorable word", None),         # user-only
        ("Please specify your religion", None),            # user-only free-text
        ("What is your favourite colour?", None),          # no rule → needs_human
    ]
    for q, want in cases:
        got = resolve_answer(q)
        if got != want:
            fails.append(f"resolve_answer({q!r}) = {got!r}, want {want!r}")

    # (B) Live fill + hidden-skip against a mock DOM.
    tab = cfx.open_tab("about:blank")
    cfx.set_tab(tab)
    time.sleep(1)
    html = (
        "<a class='eform-jump-to-field' href='#datafield_1_1_1'>Are you a British Citizen? - This field is required</a>"
        "<input type='radio' name='datafield_1_1_1' id='c_y'><label for='c_y'>Yes</label>"
        "<input type='radio' name='datafield_1_1_1' id='c_n'><label for='c_n'>No</label>"
        "<div style='display:none'>"
        "  <a class='eform-jump-to-field' href='#datafield_2_1_1'>Religion details</a>"
        "  <input type='text' name='datafield_2_1_1'>"
        "</div>"
        "<a class='eform-jump-to-field' href='#datafield_3_1_1'>What is your favourite colour?</a>"
        "<select name='datafield_3_1_1'><option value=''>Select</option><option value='7'>Blue</option></select>"
    )
    cfx.evaluate("(function(){document.body.innerHTML=" + _json.dumps(html) + ";return 1;})()")
    time.sleep(0.3)
    try:
        culs = _culprits()
        by = {c["field"]: c for c in culs}
        # citizen: visible + resolvable → fill sets it checked
        if resolve_answer(by["datafield_1_1_1"]["question"]) != "Yes":
            fails.append("mock citizen question did not resolve to Yes")
        r = _fill_radio("datafield_1_1_1", "Yes")
        if r != "OK":
            fails.append(f"citizen radio fill returned {r!r}, want OK")
        # hidden religion field: must be flagged hidden AND we must never fill it
        if not by.get("datafield_2_1_1", {}).get("hidden"):
            fails.append("hidden religion field not flagged hidden (skip-by-construction broken)")
        # unmatched colour select: resolves to None → needs_human
        if resolve_answer(by["datafield_3_1_1"]["question"]) is not None:
            fails.append("unknown colour question wrongly resolved (should be needs_human)")
    except Exception as e:  # noqa: BLE001
        fails.append(f"mock fill raised: {e}")
    finally:
        try:
            cfx.close_tab(tab)
        except Exception:  # noqa: BLE001
            pass

    # (D) DEPENDENT SELECT: County only lists options once Country is set. Proves the
    # round-retry hardening — fill Country, settle (its onchange populates County), then County.
    tab2 = cfx.open_tab("about:blank")
    cfx.set_tab(tab2)
    time.sleep(1)
    dep_html = (
        "<select name='ctry'><option value=''>Select</option>"
        "<option value='uk'>United Kingdom</option></select>"
        "<select name='cnty'><option value=''>Select</option></select>"
    )
    cfx.evaluate(
        "(function(){document.body.innerHTML=" + _json.dumps(dep_html) + ";"
        "document.querySelector(\"select[name='ctry']\").addEventListener('change',function(){"
        "var c=document.querySelector(\"select[name='cnty']\");"
        "if(this.value==='uk'&&c.options.length<2){var o=document.createElement('option');"
        "o.value='gl';o.text='Greater London';c.add(o);}});return 1;})()")
    time.sleep(0.3)
    try:
        if _fill_select("cnty", "greater london") != "NO_OPTION":
            fails.append("dependent County should be NO_OPTION before Country is set")
        if _fill_select("ctry", "united kingdom") != "OK":
            fails.append("Country select did not set OK")
        time.sleep(0.4)   # settle: Country's onchange populates County's options
        if _fill_select("cnty", "greater london") != "OK":
            fails.append("dependent County did not set OK after Country populated it (round-retry broken)")
    except Exception as e:  # noqa: BLE001
        fails.append(f"dependent-select mock raised: {e}")
    finally:
        try:
            cfx.close_tab(tab2)
        except Exception:  # noqa: BLE001
            pass

    # (E) Config-routed APPLICANT values + the ⛔ FAMILY-FIELD GUARD (pure). The vetting-form
    # correctness invariant: a Father's/Mother's/parent field is NEVER filled with the
    # applicant's own value, and user-only free-text never auto-resolves.
    if resolve_value("Father's Nationality at Birth") is not None:
        fails.append("FAMILY GUARD BROKEN — a Father's field resolved to an applicant value")
    if resolve_value("Mother's Place of Birth (Town and Country)") is not None:
        fails.append("FAMILY GUARD BROKEN — a Mother's field resolved to an applicant value")
    # …and the SAME guard must hold for resolve_answer (the RULES path) — a family question that
    # grazes an applicant RULE (british citizen / lived in the UK) must NOT be auto-answered.
    if resolve_answer("Is your partner a British citizen?") is not None:
        fails.append("FAMILY GUARD BROKEN — partner citizenship auto-answered via RULES")
    if resolve_answer("Has your father ever lived in the UK?") is not None:
        fails.append("FAMILY GUARD BROKEN — father residency auto-answered via RULES")
    if resolve_value("Please provide a memorable word") is not None:
        fails.append("user-only guard broken — memorable word resolved to a value")
    if resolve_value("What is your favourite colour?") is not None:
        fails.append("unrelated question wrongly resolved to a config value")
    _app = _applicant()
    if _app.get("country_of_birth") and \
            resolve_value("Country where you were born") != str(_app["country_of_birth"]).strip():
        fails.append("applicant country-of-birth did not resolve from the config")

    # (C) Progress guard is a pure decision: identical incomplete set + 0 filled ⇒ STOP.
    def would_stop(inc_names, prev, filled_this_pass):
        return inc_names == prev and filled_this_pass == 0
    if not would_stop(["Security Vetting"], ["Security Vetting"], 0):
        fails.append("progress guard failed to STOP on a no-progress pass")
    if would_stop(["Security Vetting"], ["Personal Details"], 0):
        fails.append("progress guard STOPPED despite the incomplete set changing")
    if would_stop(["Security Vetting"], ["Security Vetting"], 2):
        fails.append("progress guard STOPPED despite filling 2 fields this pass")

    if fails:
        print("SELFTEST FAIL")
        for f in fails:
            print("  -", f)
        return 1
    print("SELFTEST PASS")
    print("  answer resolution: 10/10 (facts resolve, personal+unknown -> needs_human)")
    print("  hidden field: flagged + never filled (skip-by-construction)")
    print("  visible resolvable field: filled OK")
    print("  dependent select: NO_OPTION before parent set, OK after parent populates it")
    print("  config values: applicant birth fields resolve; FAMILY/parent fields never do")
    print("  progress guard: stops on no-progress, continues on progress")
    return 0


def main():
    args = sys.argv[1:]
    if "--selftest" in args:
        return selftest()
    return run(dry="--dry" in args, once="--once" in args)


if __name__ == "__main__":
    sys.exit(main())
