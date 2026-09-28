# icims.com (iCIMS ATS) — site notes

Reached via Publicis Groupe's careers.publicisgroupe.com portal (Digitas UK Content
Designer, job 137624) but the platform is generic (`<company>.icims.com` pattern
elsewhere). First live encounter: 2026-09-28, genuinely capability-gapped this session.

## ⛔ Double-nested iframe embed — unreachable via standard DOM/frame tooling this session
The "Enter Your Information" (email) login/apply page visually renders correctly, but:
- Top-level `document.querySelectorAll('input')` → 0. `document.querySelectorAll('iframe')`
  → 1, whose `src` is the SAME URL as the current page plus `&in_iframe=1` appended.
- Stepping INTO that iframe's URL directly (top-level `cfx.goto()` navigate to the
  `in_iframe=1` URL) does not render at all — `innerText_len: 0`, likely the endpoint
  checks it's genuinely embedded (referrer/frame-ancestors) and refuses a bare top-level
  load.
- Staying on the outer page and inspecting again: still 0 inputs at top level, but now a
  SECOND, differently-scoped iframe count of 1 appears when queried after settling — this
  looks like the form is nested two iframes deep (outer wrapper → `in_iframe=1` page →
  itself possibly embeds a further iCIMS widget iframe).
- `cfx.sh eval-frame <idx> ...` and `cfx.sh click-frame <idx> ...` (the documented
  cross-frame primitives) both returned bare `{"error":"Internal server error"}` for every
  frame index tried (0 and 1) — did not resolve to a working way to read/click the inner
  form.
- No shadow DOM involved (`[...document.querySelectorAll('*')].filter(e=>e.shadowRoot).length` → 0 throughout) — ruling out the shadow-root class of gap.

**Not yet root-caused or fixed.** Candidates for a future session: (1) the correct
`eval-frame`/`click-frame` index may not be a simple 0/1 ordinal — enumerate actual frame
handles via a snapshot first rather than guessing; (2) the inner iCIMS widget may itself
be a same-origin-policy-protected cross-origin frame requiring a different automation
approach entirely (e.g. Playwright's native `frame_locator` chained through camofox, if
exposed); (3) check whether iCIMS also offers a plain non-JS/non-iframe apply URL variant
(some ATSs have a `?mode=basic` or similar fallback) before concluding this is a hard
block. **Workaround for now:** log `Blocked`, do not sink further time past ~15-20 min on
a single double-iframe iCIMS posting — this is a genuine, reproducible capability gap, not
a one-off fluke.
