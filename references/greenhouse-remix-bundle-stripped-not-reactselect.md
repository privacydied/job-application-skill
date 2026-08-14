# Greenhouse "react-select renders zero options headless" is a STRIPPED JS BUNDLE, not a widget wall

Captured 2026-08-14 (Claude Code, live probe against the shared camofox backend).

**This supersedes the root-cause analysis in
`references/combobox-config-silent-fail.md` §"2026-07-24 addendum — HEADLESS REACT-SELECT
WALL".** The *symptoms* recorded there are all accurate. The *cause* is not: the option list
does not render because **no JavaScript from the page ever runs in the camofox session**, so
there is no react-select at all — only inert server-rendered HTML wearing react-select's
class names.

Everything downstream of that misdiagnosis was wasted: config `fill`-vs-`combo` audits,
`combobox_pick` retries, the free-text fallback, and the proposed "inject into react-select's
controlled state via its `onChange` signature" fix. **None of them can ever work**, because
there is no React instance, no `onChange`, and no component state to inject into.

## Evidence (live, `job-boards.greenhouse.io/canonical/jobs/7043028`)

In the camofox tab:
```
scanned 1562 elements → __reactFiber$/__reactProps$ found on ZERO
window.React            undefined
window.__remixContext   undefined
script[type=module]     0
option nodes            0
form.method             "get"      ← no native POST fallback
named form fields       0          ← the entire form is JS-driven
```
Scripts that DID load are third-party only: reCAPTCHA, gapi, Google GSI, Dropbox dropins.
The Remix application bundle is absent.

The same URL fetched with `curl` (same Firefox UA) returns **116,763 bytes containing all of
it**:
```
<script type="module" async>          ← present in raw HTML, absent in DOM
job-boards.cdn.greenhouse.io/assets/entry.client-CYCVgZkQ.js
job-boards.cdn.greenhouse.io/assets/root-CJMIV731.js
job-boards.cdn.greenhouse.io/assets/vendor-T2hK1jFo.js
job-boards.cdn.greenhouse.io/assets/manifest-e0fb7ce9.js
__remixContext                        ← present in raw HTML, undefined in DOM
```

The CDN is **not** blocked — fetched from inside the page context it returns
`{ok: true, status: 200, len: 159795}`. `'noModule' in script` is `true`, so module support
is enabled. The `<script type="module">` tags are simply **not in the DOM**. Reproducible
across a fresh `goto` + 6s settle.

## Conclusion

Something in the camofox/camoufox layer strips `<script type="module">` (and the
`__remixContext` inline bootstrap) from the served HTML before parse. The page then renders
as SSR markup with no hydration:

- react-select menus render **0 options** (nothing to render them)
- typed text never commits (`singleValue=NONE` while `input.value="Yes"`)
- submit bounces `This field is required` on fields that "look" filled
- → previously logged as `CODE_MISSING` / "genuine driver wall"

**This is infrastructure, not a driver bug.** It explains why every attempted driver-side fix
failed and got written up as structural. Any SSR framework that ships its client bundle as a
module script is affected — this is not Greenhouse-specific.

## Blast radius

Every posting in the documented "headless react-select wall" class: Canonical ×4 (UX Design
systems / Developer experience / Infrastructure, Visual Designer), Monzo Lead + Staff Product
Designer, Cleo, and any other `job-boards.greenhouse.io` form. All currently logged `Blocked`
with a cause that is now known to be wrong — re-triage them with
`scripts/triage_blocked.py --ats greenhouse` once the bundle loads.

## Next step (NOT yet done — do not assume this is fixed)

Find why module scripts are stripped, in this order:
1. camoufox launch config / prefs in the browser container
   (`javascript.options.*`, any content-blocking or script-filtering rule)
2. any request-interception or HTML-rewriting middleware in the camofox backend
   (`/volume1/docker/…`) — a rewriter that drops `<script>` by attribute is the prime suspect
3. camoufox's own anti-fingerprinting patches (upstream behaviour)

**Verification that the fix worked** — reload any Greenhouse form and confirm:
```js
document.querySelectorAll('script[type=module]').length   // > 0
typeof window.__remixContext                              // "object"
// then open a required combobox → option nodes > 0
```
Only after that is a "Greenhouse react-select" `Blocked` row worth re-driving.

## Rule

Do NOT log a Greenhouse combobox failure as a driver/config wall until the hydration check
above passes. `no fibers + no module tags + 0 options` is the **stripped-bundle** signature,
and no amount of `combobox_pick`, config re-splitting, or `onChange` injection will move it.
