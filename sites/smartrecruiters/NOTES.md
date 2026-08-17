# SmartRecruiters (`jobs.smartrecruiters.com`) — reachable, readable, NOT yet fillable (shadow DOM)

Verified live 2026-08-17 on Entain "Motion Designer - Ladbrokes & Coral"
(`jobs.smartrecruiters.com/entain/744000142593084`).

## Route to the form (works, no account)

1. `cfx.goto("https://jobs.smartrecruiters.com/<slug>/<jobId>")` — renders fine, no wall.
2. The apply control is labelled **"I'm interested"** (not "Apply"), and there are several
   copies of it on the page; clicking any one works.
3. It navigates to `jobs.smartrecruiters.com/oneclick-ui/company/<Company>/publication/<uuid>`,
   titled **"Easy apply - <role> - <company>"**.

## ⚠️ "Easy Apply" here is NOT the forbidden LinkedIn/Reed class

SKILL.md's Easy-Apply ban targets **LinkedIn Easy Apply** and **reed-easyapply** — aggregator
one-clicks that fire the stored profile with no tailoring. SmartRecruiters' `oneclick-ui` is
the **employer's own ATS form**, and it asks for real content:

    Personal information · Experience · Education · Your Profiles
    Resume *  (required)  ·  Message to the Hiring Team

That is the same substance as a Greenhouse application. Judge by the form, not the branding —
but say so explicitly when reporting, because the page does say "Easy Apply".

## ⛔ The blocker: the form is inside SHADOW DOM

`document.querySelectorAll('input')` returns **0** on the apply page, while
`[...document.querySelectorAll('*')].filter(e => e.shadowRoot).length` returns **33**. The
whole form is web components, so:

- `atsform.py`'s `_RESOLVE` enumerates `document.querySelectorAll(kinds)` and finds nothing.
- Worse, `_RESOLVE` returns a **CSS selector** (`[name=…]` / `[id=…]`) that callers hand to a
  plain `document.querySelector`. Even a shadow-aware *enumeration* would return a selector
  that cannot be re-found from the document root. Supporting this properly means changing how
  every primitive ADDRESSES a control, not just how it finds one.

**Do not fork a SmartRecruiters-only filler** (AGENTS.md §6, guard test
`tests/test_core.py::TestNoDivergentFormWidgets`). The fix belongs in the shared engine.

### The fields are right there — verified probe

Piercing shadow roots reaches a clean, well-named field set:

```js
(() => {
  const out = [];
  const walk = (root, d) => {
    if (d > 6) return;
    root.querySelectorAll('*').forEach(e => {
      if (e.matches('input,textarea,select')) {
        const lab = (e.getAttribute('aria-label') || e.placeholder || e.name || e.id || '').trim();
        out.push((e.type || e.tagName) + '~' + lab.slice(0, 30));
      }
      if (e.shadowRoot) walk(e.shadowRoot, d + 1);
    });
  };
  walk(document, 0);
  return out.slice(0, 20).join(' | ');
})()
```

returns:

    file~file-input | text~first-name-input | text~last-name-input | email~email-input |
    email~confirm-email-input | text~spl-form-element_10 | text~Search by country/region |
    tel~Phone number | text~linkedin-input | text~facebook-input | text~twitter-input |
    text~website-input | file~file-input | textarea~hiring-manager-message-input

So this is a **shipping-engine gap, not a wall**: every value the config already holds has a
field waiting for it.

### Shape of the fix (not yet built)

Add shadow-piercing to `atsform` as a fallback used ONLY when the light DOM yields no
candidates, and change addressing from "return a selector string" to "mark the element and
address the mark":

1. a `deepQueryAll(sel)` JS helper that walks `shadowRoot`s (depth-capped);
2. on a shadow hit, set `data-ats-target` on the element itself (the pattern
   `combobox_pick` already uses) and have primitives resolve `[data-ats-target]` **through
   the same deep walk** rather than `document.querySelector`;
3. keep the light-DOM path first and unchanged, so no currently-working board can regress.

This is worth doing: SmartRecruiters is **41 companies / 1,986 jobs** in the ats-direct
registry, and web-component forms are spreading to other ATSes.

## On-lane inventory found this pass (all London, all untracked)

| company | role | url |
|---|---|---|
| Entain | Motion Designer - Ladbrokes & Coral | `/entain/744000142593084` |
| Entain | Motion Designer | `/entain/744000142594832` |
| ASOS | Platform Engineer – Data Science & AI Platform | `/asos/744000143391739` |
