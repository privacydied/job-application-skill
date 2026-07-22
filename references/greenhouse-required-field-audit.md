# Greenhouse required-field audit (and the silent combobox-fill trap)

## The trap (2026-07-22)
`atsform.fill` and `gh_apply`'s batch `apply` / `FILL_TOPUP` on a **react-select combobox**
(input class `select__input` inside `.select__control`) report `OK (N chars)` — but they only
type into the search box. They do NOT open the menu or commit an option. So a Greenhouse form can
report every field `OK` while the selects are actually EMPTY, and `atsform.submit` then blocks with
`This field is required` on fields you "already filled". This wasted a whole submit loop on the
CSJ AISI posting (2005465): `gh_apply` said `FILLED_ONLY` with all fields OK, but 3 EEO selects +
right-to-work + declaration + location were empty comboboxes.

**Rule: after `gh_apply` fills a Greenhouse form, never trust the `OK` lines for comboboxes.
Run the audit below and re-drive every empty `aria-required` combobox with `combobox_pick`
(exact text) or `fill_csj_eeo.py` — never `fill`.**

## 1. Audit — list every required field and its filled state
Paste into `cfx.sh eval` (or `python3 -c "import cfx; print(cfx.evaluate(<expr>))"`). Returns a
flat `id => filled|empty` string list — DO NOT return structured objects (the shell wrapper 500s
on object/array literals; see SKILL.md camofox section).

```js
(() => {
  var out = [];
  var els = [].slice.call(document.querySelectorAll('input,textarea,select'))
    .filter(function(e){ return e.required || e.getAttribute('aria-required') === 'true'; });
  els.forEach(function(e){
    var id = e.id || e.name || '(noname)';
    var filled = null;
    if (e.closest && e.closest('.select__control')) {
      var c = e.closest('.select__control');
      var v = c.querySelector('.select__single-value');
      var p = c.querySelector('.select__placeholder');
      filled = v ? v.textContent.trim() : (p ? p.textContent.trim() : '(empty)');
    } else {
      filled = (e.value || '').trim();
    }
    if (!filled || filled === 'Select...') out.push(id + '=>EMPTY');
    else out.push(id + '=>' + filled);
  });
  return out.join(' | ');
})()
```

Any `=>EMPTY` with `aria-required` is a submit blocker. Text inputs/essays that are empty are the
usual suspects; comboboxes must be re-driven (see below).

## 2. Drive an aria-required combobox reliably
`combobox_pick` sometimes races the async menu on heavy Greenhouse pages. The robust sequence
(open → poll for menu → exact click) works every time. Use `bash sites/_common/scripts/cfx.sh eval`
(preferable to `cfx.evaluate`, which 500s on heavy ATS pages).

```js
(async () => {
  var id = "<FIELD_ID>";                 // e.g. 'question_9288858101'
  var target = "<EXACT OPTION TEXT>";    // e.g. 'Yes' / 'No' / 'London, England, United Kingdom'
  var e = document.getElementById(id);
  if (!e) return 'NOEL';
  e.closest('.select__control').scrollIntoView({block:'center'});
  var ctrl = e.closest('.select__control');
  ['mousedown','mouseup','click'].forEach(function(t){
    ctrl.dispatchEvent(new MouseEvent(t,{bubbles:true,view:window}));
  });
  // poll for the async menu to mount (react-select mounts it after mousedown)
  var tries = 0, menu = null;
  while (tries < 40) {
    menu = document.querySelector('.select__menu');
    if (menu && menu.querySelectorAll('.select__option').length) break;
    await new Promise(r => setTimeout(r, 50)); tries++;
  }
  if (!menu) return 'NOMENU';
  var opts = [].slice.call(menu.querySelectorAll('.select__option'));
  // normalize curly apostrophes so "I don't wish to answer" matches the option text
  var t = opts.find(function(o){
    return o.textContent.replace(/[\u2018\u2019]/g, "'").trim().toLowerCase()
            .indexOf(target.replace(/[\u2018\u2019]/g, "'").trim().toLowerCase()) >= 0;
  });
  if (!t) return 'NOOPT';
  t.scrollIntoView({block:'center'});
  ['mousedown','mouseup','click'].forEach(function(ev){
    t.dispatchEvent(new MouseEvent(ev,{bubbles:true,view:window}));
  });
  await new Promise(r => setTimeout(r, 200));
  var v = e.closest('.select__control').querySelector('.select__single-value');
  return 'BOUND:' + (v ? v.textContent.trim() : '(empty)');
})()
```

### Pitfalls found here (why the obvious approaches failed)
- **ArrowDown-counting drifts.** `combobox_pick`'s keyboard path opens the menu with the
  *previously-set value* highlighted (not index 0), so "2x ArrowDown then Enter" landed on the wrong
  option (e.g. selected `40-44` when aiming for `30-34`; selected `Don't know` when aiming for
  `I don't wish to answer`). Prefer the **exact-click** find above. If you must keyboard, first
  press `ArrowUp` ~20x to reset to top, THEN count down — but exact-click is safer.
- **Menu closes between `evaluate` calls.** Opening in one `cfx.sh eval` and reading options in a
  second call returns `NOMENU` — the menu auto-closes on blur/timeout. Do open + read + click in a
  SINGLE async `evaluate` (the snippet above does this). Sleeping between two separate calls does
  NOT keep the menu open.
- **Scroll-into-view matters.** `4011721101` (age group) refused to open until its control was
  scrolled into the viewport first (`scrollIntoView` before mousedown). If `NOMENU` persists, add
  the scroll step.
- **Curly vs straight apostrophe.** The option text is `I don't wish to answer` (U+2019), but a
  straight-apostrophe target string fails `===`. Match case-insensitively after normalizing
  `[\u2018\u2019]` to `'` (done in the snippet).
- **Location combobox matches the wrong city.** "Location (City)" is a type-to-filter combobox;
  `combobox_pick("London")` matched `London, Ontario, Canada`. The exact option here is
  `London, England, United Kingdom` — search the menu for the exact string first.

## 3. Diversity "I don't wish to answer" fast path
For the "Civil Service UK Diversity Questions" selects where the real answer is unknown, drive
each to `I don't wish to answer` with the snippet above (normalized match), or just run
`python3 scripts/fill_csj_eeo.py` (default fills all to that value; `--set <id>:<value>` for real
answers). The EEO selects are `aria-required` and gate submit, so they MUST be set even though
they're monitoring fields.

## 4. Re-verify, then submit (in place)
After driving the empties, re-run the audit (#1). When it returns zero `=>EMPTY`, submit on the
SAME page load (never `cfx.goto` between fill and submit — it reloads the form blank and you're
back to `First Name is required`). `atsform.submit("Submit application", "<success re>")`.
Greenhouse may then gate behind an emailed 8-char security code — `gh_apply` handles that
(`fetch_verification_code` + type char-by-char); if you're driving manually, poll the mailbox and
type it, then Submit again. On success the URL becomes `.../confirmation` and the body reads
"Thank you for applying". Capture `confirmation.png`/`.txt` and log `Applied --proof`.
