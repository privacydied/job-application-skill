#!/usr/bin/env python3
"""diagnose.py — the FIRST thing to run when an applicationtrack.com (VacancyFiller)
eform "won't submit" / the Submit button is missing / a field "seems unreachable".

⛔ THE ANTI-RABBIT-HOLE TOOL. A whole agent session (Hermes, GCHQ 3780, 2026-07-17)
burned *five firings* concluding a hidden field (`datafield_17712`, display:none) was a
"provably unreachable VacancyFiller form bug" and declared the application unsubmittable.
It was wrong on every count: the Equal Opportunities section that field lives in was
COMPLETE, and the real blockers were three OTHER sections each missing one plain
eligibility answer. The submit unblocked in minutes once the section tracker was read.

The lesson, enforced here as code so no future run can skip it:

  A `display:none` field is NEVER the blocker. VacancyFiller hides fields whose reveal
  condition doesn't apply; a hidden field is not required *in the current state*, and no
  human could fill it either. The blocker is ALWAYS a whole SECTION whose tracker parent
  class is `tracker_stat_incomplete`. The `a.eform-jump-to-field` anchors inside that
  section's problem banner NAME the exact culprit fields (`href="#datafield_…"`).

This script reads the truth directly and prints it:
  1. Per-section status from `a.jump-to-page` → `parentElement.className`.
  2. For each INCOMPLETE section: navigate to it and list the culprit fields the site
     itself flags (`a.eform-jump-to-field`), plus each culprit's type/options so you can
     answer it from the applicant profile.
  3. Whether `submit_button` currently renders.

It NEVER fills anything — pure read-only diagnosis. Fill the named culprits (radios via
native `.click()`, selects via value+change, text via the prototype value-setter +
input/change/blur), Save-and-continue each page, then re-run this to confirm every
section is complete and Submit has appeared.

Usage:
    CFX_KEY=... CFX_TAB=<eform tab> python3 diagnose.py
        [--eform-base <https://…/candidate/eform/<ID>>]   # else uses current tab URL
        [--no-visit]   # only print section statuses; don't visit incomplete pages

Exit code 0 always (diagnostic). Prints a JSON summary on the last line for scripting.
"""
import json
import os
import re
import sys
import time

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_here, "..", "..", "_common", "scripts"))
import cfx  # noqa: E402

# --- read-only JS probes -----------------------------------------------------

# Per-section status: the tracker link's PARENT class is the source of truth (the icon
# innerHTML is empty, which is why naive scans call it "unreliable").
SECTIONS_JS = r"""JSON.stringify([...document.querySelectorAll('a.jump-to-page')].map(function(a){
  var cls = a.parentElement ? a.parentElement.className : '';
  return {
    section: a.innerText.trim(),
    href: a.getAttribute('href'),
    complete: /tracker_stat_(?:complete|mandatory_complete)/.test(cls),
    incomplete: /tracker_stat_incomplete/.test(cls),
    raw: cls.replace('page-submitted','').replace('page-not-submitted','').replace('current_page','').trim()
  };
}))"""

# The culprit fields the SITE ITSELF flags in the "There is a problem" banner. Each anchor
# names the exact field via href="#datafield_…" — infinitely more reliable than guessing.
CULPRITS_JS = r"""JSON.stringify([...document.querySelectorAll('a.eform-jump-to-field')].map(function(a){
  var href = a.getAttribute('href') || '';
  var name = href.replace(/^#/, '');
  var el = name ? document.querySelector("[name='" + name + "']") : null;
  var info = { question: a.innerText.replace(/\s+/g,' ').trim().slice(0,160), field: name };
  if (el) {
    info.tag = el.tagName; info.type = el.type;
    if (el.tagName === 'SELECT') {
      info.options = [...el.querySelectorAll('option')].map(function(o){ return o.value + '=' + o.text.trim(); });
    } else if (el.type === 'radio') {
      info.options = [...document.querySelectorAll("[name='" + name + "']")].map(function(r){
        return r.value + '=' + (r.labels && r.labels[0] ? r.labels[0].innerText.trim() : '?');
      });
    } else if (el.type === 'checkbox') {
      info.checkbox = true; info.checked = el.checked;
    }
    // Is the culprit itself hidden? If so, this is the TRAP — the fix is elsewhere
    // (a parent select whose value should reveal it, or the field isn't needed at all).
    var hidden = false, n = el;
    for (var i = 0; i < 6 && n; i++) { if (getComputedStyle(n).display === 'none') { hidden = true; break; } n = n.parentElement; }
    info.hidden = hidden;
  } else {
    info.note = 'no element for this name on the page (may be a cross-section anchor)';
  }
  return info;
}))"""

SUBMIT_JS = "!!document.querySelector('button[name=submit_button],input[name=submit_button]')"


def _eval(js, tries=3):
    """Small-payload read with a retry — cfx.evaluate on VF pages flakes to None/500
    on the first call after a nav; never conclude 'dead' on a single None."""
    for _ in range(tries):
        try:
            v = cfx.evaluate(js)
            if v is not None:
                return v
        except cfx.CfxError:
            pass
        time.sleep(1.5)
    return None


def selftest():
    """`diagnose.py --selftest` — prove the detection logic against a synthetic
    VacancyFiller DOM (incomplete section + a hidden trap field) without needing a real
    application open. Injects a mock, runs the SHIPPED probes, asserts on the result.
    This is what turns "verified by construction" into "actually ran green"."""
    import json as _json
    tab = cfx.open_tab("about:blank")
    cfx.set_tab(tab)
    time.sleep(1)
    html = (
        "<div class='tracker_stat_complete'><a class='jump-to-page' href='#p1'>Personal Details</a></div>"
        "<div class='tracker_stat_incomplete'><a class='jump-to-page' href='#p2'>Minimum Eligibility</a></div>"
        "<div class='tracker_stat_complete'><a class='jump-to-page' href='#p3'>Equal Opportunities</a></div>"
        "<a class='eform-jump-to-field' href='#datafield_388025_1_1'>Are you a British Citizen? - This field is required</a>"
        "<select name='datafield_388025_1_1'><option value=''>Select</option>"
        "<option value='1'>Yes</option><option value='2'>No</option></select>"
        "<div style='display:none'><input name='datafield_17712_1_1' type='text'></div>"
        "<a class='eform-jump-to-field' href='#datafield_17712_1_1'>Religion details</a>"
    )
    inject = ("(function(){document.body.innerHTML=" + _json.dumps(html) +
              "; return document.querySelectorAll('a.jump-to-page').length;})()")
    try:
        cfx.evaluate(inject)
        time.sleep(0.3)
        secs = _json.loads(cfx.evaluate(SECTIONS_JS))
        culs = _json.loads(cfx.evaluate(CULPRITS_JS))
        inc = [s["section"] for s in secs if s["incomplete"]]
        hidden = [c["field"] for c in culs if c.get("hidden")]
        visible = [c["field"] for c in culs if not c.get("hidden")]
        assert inc == ["Minimum Eligibility"], f"incomplete-section detection: {inc}"
        assert "datafield_17712_1_1" in hidden, f"hidden trap not flagged: {culs}"
        assert "datafield_388025_1_1" in visible, f"visible culprit missed: {culs}"
        print("SELFTEST PASS")
        print("  incomplete section identified :", inc)
        print("  hidden field flagged as trap  :", hidden)
        print("  visible culprit (fill this)   :", visible)
        return 0
    except AssertionError as e:
        print("SELFTEST FAIL:", e, file=sys.stderr)
        return 1
    finally:
        try:
            cfx.close_tab(tab)
        except Exception:
            pass


def main():
    args = sys.argv[1:]
    if "--selftest" in args:
        return selftest()
    eform_base = None
    no_visit = "--no-visit" in args
    if "--eform-base" in args:
        eform_base = args[args.index("--eform-base") + 1].rstrip("/")

    cur = cfx.current_url()
    if not eform_base:
        m = re.search(r"(.*/candidate/eform/\d+)", cur or "")
        if not m:
            print("ERROR: not on an eform tab and no --eform-base given. Open the "
                  "application's eform (…/candidate/eform/<ID>/page/N) first.", file=sys.stderr)
            return 2
        eform_base = m.group(1)

    print(f"# applicationtrack diagnose — {eform_base}", file=sys.stderr)

    sections = _eval(SECTIONS_JS)
    if not sections:
        print("ERROR: could not read the section tracker (a.jump-to-page). Are you on a "
              "logged-in eform page? (session may have dropped — re-auth per NOTES.)", file=sys.stderr)
        return 2
    sections = json.loads(sections)

    incomplete = [s for s in sections if s["incomplete"]]
    print("\n=== SECTION STATUS (source of truth: tracker parentElement.className) ===")
    for s in sections:
        mark = ">>> INCOMPLETE" if s["incomplete"] else "    ok        "
        print(f"  {mark}  {s['section']}")

    submit_ready = _eval(SUBMIT_JS)
    summary = {"eform_base": eform_base, "incomplete_sections": [], "submit_button_present": bool(submit_ready)}

    if not incomplete:
        print("\nAll sections complete. submit_button present:", bool(submit_ready))
        print("If Submit is present, fill the USER-ONLY final page (memorable word + hint + "
              "declaration) and click submit_button. Nothing else is blocking.")
        print("\nSUMMARY " + json.dumps(summary))
        return 0

    print("\n=== CULPRIT FIELDS per incomplete section (named by the site itself) ===")
    print("Fill these from the applicant profile. A `hidden:true` culprit is the KNOWN TRAP "
          "— do NOT try to force it visible; either a parent select's value reveals it, or "
          "it isn't actually needed. Re-scan after setting a section's selects.\n")

    for s in incomplete:
        entry = {"section": s["section"], "href": s["href"], "culprits": []}
        if not no_visit and s.get("href"):
            try:
                cfx.navigate(s["href"])
                time.sleep(3)
            except cfx.CfxError as e:
                print(f"  ! could not open {s['section']}: {e}", file=sys.stderr)
        culprits = _eval(CULPRITS_JS) if not no_visit else None
        culprits = json.loads(culprits) if culprits else []
        entry["culprits"] = culprits
        print(f"--- {s['section']} ---")
        if not culprits:
            print("    (no eform-jump-to-field anchors found — the section may complete on a "
                  "plain Save-and-continue, or a conditional field appears after you set a select)")
        for c in culprits:
            flag = "  ⚠ HIDDEN(trap)" if c.get("hidden") else ""
            print(f"    • [{c.get('field','?')}] {c.get('question','')}{flag}")
            if c.get("options"):
                print(f"        options: {c['options']}")
        summary["incomplete_sections"].append(entry)

    print("\nNEXT: fill each named culprit truthfully from references/applicant-profile.md, "
          "Save-and-continue (button name=continue_button) each page, then re-run diagnose.py "
          "until every section is ok and submit_button is present. NEVER spend a second pass "
          "on a display:none field — it is not the blocker.")
    print("\nSUMMARY " + json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
