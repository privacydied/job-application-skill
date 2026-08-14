# `cfx.evaluate` runs in an ISOLATED WORLD — probing `window.*` manufactures fake structural walls

Captured 2026-08-14 (Claude Code). **This doc replaces an earlier same-day version of itself
that claimed the page's JS bundle was stripped and that page JavaScript did not execute. That
claim was WRONG.** It is preserved here as the worked example because the *method* that
produced it is the single most productive source of false "structural wall" reports in this
repo — including, most likely, several already written up as permanent.

## The finding

Greenhouse react-select menus **work**. Verified live on
`job-boards.greenhouse.io/canonical/jobs/7043028`:

```
before real click:   options 0   menus 0
cfx.click_selector('#question_58264615')  → ok
after  real click:   options 2   menus 3   aria-expanded "true"
```

Options render, the menu opens, the widget is alive. What it needs is a **real trusted click**
through camofox (`click_selector` / `click_ref`) — not a synthetic `dispatchEvent`, and not
`atsform.fill` typing into the input.

## How the false wall gets manufactured

`cfx.evaluate` executes in an **isolated world**. Isolated worlds share the **DOM** but NOT:

- page JS globals — `window.ENV`, `window.grecaptcha`, `window.gapi`, `window.__remixContext`
- **DOM expando properties set by page JS** — including React's `__reactFiber$…` /
  `__reactProps$…` keys

So on a perfectly healthy, fully-hydrated page, an agent probing from `evaluate` sees:

```
window.ENV .................... undefined      ← looks like "inline scripts never ran"
grecaptcha / gapi / Dropbox ... undefined      ← looks like "external scripts never ran"
__reactFiber$ on 1562 els ..... zero           ← looks like "React never hydrated"
injected inline <script> ...... does not run   ← sets the PAGE's window; you read the isolated one
```

Every one of those readings is **expected and meaningless**. Chained together they build a
confident, evidence-rich, completely false conclusion: *"no JS executes → no React → the
widget cannot be driven → structural wall, log Blocked."* That is exactly the reasoning that
produced this doc's first version, plus a bogus `js_health.py` that would have told the loop
to stop driving a healthy browser.

Two more traps that reinforce it:
- **`option` nodes are 0 until the menu is OPENED.** react-select renders options on open.
  Counting them on a closed select and concluding "renders zero options headless" is circular.
- **`script[type=module]` counts vary between loads** (observed 0 and 1 on the same URL,
  minutes apart). Tag presence is a timing artifact, not a signal. Do not build a diagnosis on it.

## Rule

**Never diagnose page health from `window.*` or DOM expandos via `evaluate`.** They are
invisible by construction. Diagnose only from signals that live in the shared DOM, and drive
with real trusted clicks:

| ❌ Don't conclude from            | ✅ Do this instead                                      |
|-----------------------------------|--------------------------------------------------------|
| `typeof window.X === 'undefined'` | read DOM text/attributes (`aria-expanded`, node counts) |
| no `__reactFiber$` on elements    | click the control and observe the DOM change            |
| `options.length === 0` (closed)   | `cfx.click_selector(<combobox>)`, wait, re-count        |
| injected `<script>` didn't set a global | check its DOM side-effect, not its global         |

**Before logging ANY "widget won't bind / renders nothing / not drivable" wall:** open the
control with a real click and re-read the DOM. If nodes appear, the widget is fine and the
driver's event synthesis is the bug.

## What this means for the Greenhouse "wall"

The whole documented class — "headless react-select renders zero options", Canonical ×4,
Monzo Lead + Staff PD, Cleo, and the `CODE_MISSING` submit-bounce signature — needs re-testing
with real clicks before any of it is believed. `references/combobox-config-silent-fail.md`
§2026-07-24 addendum concluded "GENUINE driver wall, do not loop"; that conclusion rests on
menu-never-renders observations that this doc shows are how a *closed* select behaves.

Likely real fix: make `combobox_pick` open the menu via `click_selector` (trusted) rather than
synthetic events, then click the option node by exact text. **UNVERIFIED end-to-end** — the
menu-opens result above is solid; committing a value and passing submit validation was not
tested (see below).

## The one genuinely hard part on Canonical (not a driver issue)

Canonical's required field `question_58264615` is an attestation:

> *"During this application process I agree to use only my own words. I understand that
> plagiarism, the use of AI or other generative tools…"* — options `Yes` / `No`.

It gates submit. Ticking `Yes` on an agent-driven application is a false declaration to the
employer, so these specific roles are **not** automatable end-to-end regardless of how good
the combobox driver gets. That is a truthfulness limit, not a wall to engineer around — hand
Canonical roles to the user, or skip them.
