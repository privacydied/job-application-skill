/**
 * dom_checks.js — run atsform's INJECTED JavaScript against real DOMs in a real browser.
 *
 * WHY THIS EXISTS (2026-08-16). The Python suite can only assert that the injected JS is
 * *present* and *parses*; it cannot tell you what the JS DOES. But every integrity bug the
 * 2026-08-16 audit found lived precisely there — in a selector or a scoring loop that
 * silently picked the wrong element and reported OK. Those are invisible to unit tests and
 * only surface as a wrong answer in a submitted application, which is the one place we can
 * never take it back.
 *
 * Each check below is paired with the defect it pins, and every one of them was verified to
 * FAIL against the pre-fix code (commit 90149ff) and PASS after — otherwise it proves nothing.
 * That before/after step is the point of this file; keep it when adding a check.
 *
 * USAGE:
 *   python3 tests/extract_js.py > /tmp/atsform-js.json      # dump the JS blobs
 *   node tests/dom_checks.js /tmp/atsform-js.json
 *
 * Requires the Playwright container from ~/.claude/CLAUDE.md (ws://localhost:3006/, client
 * pinned to the server's version). Not part of `pytest` — it needs that container, so it is
 * an explicit pre-push check for changes to atsform's JS, not a per-commit gate.
 */
// playwright-core is NOT vendored into this repo — it must match the Playwright server's
// version exactly (a mismatch fails with "428 Precondition Required"), so it is installed
// out-of-tree per ~/.claude/CLAUDE.md. Resolve it from there, or from $PLAYWRIGHT_CORE.
// Node resolves bare requires relative to THIS file, not the cwd, so an explicit path is
// required even when you run the harness from the install directory.
const PW = process.env.PLAYWRIGHT_CORE || '/tmp/pw-work/node_modules/playwright-core';
let chromium;
try {
  ({ chromium } = require(PW));
} catch (e) {
  console.error(`Cannot load playwright-core from ${PW}.\n` +
    'Install it pinned to the server version (see ~/.claude/CLAUDE.md):\n' +
    '  mkdir -p /tmp/pw-work && cd /tmp/pw-work && npm init -y\n' +
    '  npm install playwright-core@1.58.0 --no-save\n' +
    'or point $PLAYWRIGHT_CORE at an existing install.');
  process.exit(2);
}

const jsPath = process.argv[2] || '/tmp/atsform-js.json';
const js = require(jsPath);
const sub = (s, o = {}) => {
  const all = { __OPT__: '"x"', __VAL__: '"x"', __STRICT__: 'false', ...o };
  for (const [k, v] of Object.entries(all)) s = s.split(k).join(v);
  return s;
};
const finder = id => `(function(t){return document.getElementById(${JSON.stringify(id)})})`;

// ── DOM shapes, each reproducing the exact structure named in the audit finding ──────────
const CHECKBOX_HTML = `
  <label><input type="checkbox" id="woman"> Woman</label>
  <label><input type="checkbox" id="man"> Man</label>`;

const RADIOGROUP_OTHER_HTML = `
  <div id="grp" role="radiogroup" aria-labelledby="lbl">
    <span id="lbl">Do you identify as transgender?</span>
    <label><input type="radio" name="tg" value="Yes"> Yes</label>
    <label><input type="radio" name="tg" value="No"> No</label>
    <input type="text" id="other" placeholder="Other, please specify">
  </div>`;

const SELECT_WRAPPER_HTML = `
  <div id="wrap"><select id="s">
    <option value="">Pick</option><option>Yes</option><option>No</option>
  </select></div>`;

const GAP_HTML = `
  <div><label for="a">Why do you want to work here?</label><input type="text" id="a"></div>
  <div><label for="b">Describe a project you are proud of</label><input type="text" id="b"></div>`;


const COMBO_INPUT_HTML = `
  <div><label for="essay">Why do you want to work here?</label>
       <textarea id="essay"></textarea></div>
  <div class="select__control">
    <label for="rtw">Are you legally authorized to work in the country?</label>
    <input type="text" id="rtw" role="combobox" aria-autocomplete="list">
  </div>`;

(async () => {
  const browser = await chromium.connect('ws://localhost:3006/', { timeout: 15000 });
  const page = await browser.newPage();
  const results = [];
  const t = (name, pass, detail) => results.push({ name, pass, detail });

  // 1. set_checkbox took the FIRST label containing the text, so "Man" ticked "Woman" —
  //    the same first-substring defect set_radio was fixed for on 2026-08-15.
  await page.setContent(CHECKBOX_HTML);
  await page.evaluate(sub(js.CHECKBOX_MAN));
  const woman = await page.$eval('#woman', e => e.checked);
  const man = await page.$eval('#man', e => e.checked);
  t('set_checkbox("Man") ticks Man, not Woman', man === true && woman === false,
    `man=${man} woman=${woman}`);

  // 2. The radio-group guard failed open when the group also held a free-text input, so a
  //    self-describe EEO question resolved as a combobox aimed at the "Other" box.
  await page.setContent(RADIOGROUP_OTHER_HTML);
  const r1 = JSON.parse(await page.evaluate(
    sub(js.COMBO_RESOLVE, { __TARGET__: '"grp"', __FIND__: finder('grp') })));
  const otherMarked = await page.$eval('#other', e => e.hasAttribute('data-ats-target'));
  t('radiogroup + "Other, please specify" resolves as radio-group',
    r1.reason === 'radio-group' && otherMarked === false,
    `kind=${r1.kind} reason=${r1.reason} otherMarked=${otherMarked}`);

  // 3. Only `el.tagName === 'SELECT'` was tested, so a wrapper div around a native select
  //    went down the react-select ladder with the marker on a DIV.
  await page.setContent(SELECT_WRAPPER_HTML);
  const r2 = JSON.parse(await page.evaluate(
    sub(js.COMBO_RESOLVE, { __TARGET__: '"wrap"', __FIND__: finder('wrap') })));
  const selectTagged = await page.$eval('#s', e => e.hasAttribute('data-ats-native'));
  const divMarked = await page.$eval('#wrap', e => e.hasAttribute('data-ats-target'));
  t('wrapper around a native <select> resolves native',
    r2.kind === 'native' && selectTagged === true && divMarked === false,
    `kind=${r2.kind} selectTagged=${selectTagged} divMarked=${divMarked}`);

  // 4. data-ats-gap indices are reassigned every pass but were never cleared, so an
  //    already-answered field kept a stale tag and two elements shared index 0 — the
  //    filler then wrote the next answer into the field it had already answered.
  await page.setContent(GAP_HTML);
  await page.evaluate(js.UNANSWERED);
  await page.$eval('#a', e => { e.value = 'answered'; });   // pass 1 fills #a
  await page.evaluate(js.UNANSWERED);                        // pass 2
  const tags = await page.evaluate(() =>
    [...document.querySelectorAll('[data-ats-gap]')]
      .map(e => e.id + '=' + e.getAttribute('data-ats-gap')));
  t('_UNANSWERED clears stale gap tags (no duplicate index 0)',
    tags.length === 1 && tags[0] === 'b=0', `tags=${JSON.stringify(tags)}`);


  // 5. A react-select input is <input type=text role=combobox>, so it used to appear in
  //    `texts` as well as `combos`. Once the text branch started honouring the bank row's
  //    `kind`, that made it REFUSE every dropdown ("kind='radio', not free text") and leave
  //    required fields empty — a regression introduced by the kind guard itself.
  await page.setContent(COMBO_INPUT_HTML);
  const un = JSON.parse(await page.evaluate(js.UNANSWERED));
  const textsHaveCombo = un.texts.some(t => /authorized to work/i.test(t));
  const textsHaveEssay = un.texts.some(t => /want to work here/i.test(t));
  t('_UNANSWERED keeps combobox inputs out of texts (essay still listed)',
    textsHaveCombo === false && textsHaveEssay === true,
    `texts=${JSON.stringify(un.texts)}`);

  await browser.close();

  let failed = 0;
  for (const r of results) {
    if (!r.pass) failed++;
    console.log(`${r.pass ? 'PASS' : 'FAIL'}  ${r.name}\n        ${r.detail}`);
  }
  console.log(failed ? `\n${failed} FAILED` : `\nall ${results.length} DOM checks passed`);
  process.exit(failed ? 1 : 0);
})().catch(e => { console.error('ERROR', e.message); process.exit(2); });
