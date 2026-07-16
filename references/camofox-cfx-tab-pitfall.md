# camofox CFX_TAB multi-tab pitfall (2026-07-14)

## Symptom
You open a fresh tab for board B (`cfx.open_tab()` / `cfx.sh open-tab`),
drive board B, then run a `cfx.sh shot` / `cfx.evaluate` / `cfx.screenshot`
call — and get a screenshot of the WRONG page (e.g. the OTHER tab's
CSJ home, not the MoJ form you meant to capture).

## Root cause
`cfx.sh shot|eval|screenshot` READ `CFX_TAB` from the ENV, not a
hardcoded tab. If you re-`source .runtab` in a later terminal call, the
persisted `CFX_TAB` may point at a DIFFERENT live tab than the one you
just navigated (the browser-tool `browser_navigate` and a separate terminal
`open_tab()` can land on different ids; `.runtab` only holds one).

So: the tab you navigated (ba1c87eb, holding the live MoJ form) was
NOT the tab `CFX_TAB` pointed at (fa332509, which had been
redirected to CSJ home). Screenshotting "the tab" silently captured the
dead one.

## Fix / discipline
- BEFORE any `cfx.sh shot|eval|screenshot`, `export CFX_TAB=<the exact
  tab id you just navigated>`, THEN run the call. Don't assume the
  sourced env still matches the tab you drove via browser_navigate.
- When two tabs both look "live" (engine healthy, /health ok), a
  `cfx.evaluate("document.title")` on each disambiguates which holds
  the page you want — do this before a screenshot you'll rely on.
- The MoJ form state is per-TAB (SPA). A re-`open_tab()` + re-navigate
  starts the wizard fresh (account still exists; steps restart). The CSJ/TAL
  session is a separate concern (cookies in profile).

## Seen as
HMCTS SBA (2004059) debug: spent a screenshot+vision round on a CSJ
home screenshot because CFX_TAB pointed at the wrong tab. Re-pointing
`export CFX_TAB=ba1c87eb-...` then `cfx.sh shot` captured the real
MoJ General form.

## Concurrent-tab wedge wedges the whole engine (2026-07-14)

Symptom: you launch several sourcing processes at once, each opening its own
tab (one per board), and mid-run every new `POST /tabs` returns
`{"error":"Internal server error"}` / `open_tab: tab not created (last
response {})`, while existing tabs start 500/410-ing. The engine has wedged
and the whole sourcing pass returns 0.

Root cause: camofox's live-tab ceiling is **~8 tabs** (matches the SKILL.md
"~8-tab cap where open-tab starts failing"). Opening ~5 tabs in parallel
(one per board / sourcing script) blows past it and the engine destabilises —
it can drop ALL in-flight work, not just one tab. (A bare `curl -X DELETE
/tabs/<id>` to clean up SILENTLY FAILS too, because it omits `?userId=` — so
the tabs stay and the wedge persists.)

Fix / discipline:
- **Source boards SERIALLY on ONE reused tab.** Re-navigate the same tab per
  board; never open N tabs for N boards in parallel. Reuse `cfx.list_tabs()[0]`
  between boards.
- **Recover from a wedge:** close stray tabs with `cfx.close_tab(tab_id)`
  (this sends the required `?userId=`, unlike a raw `curl DELETE`). Get back
  under ~3 tabs, then `ensure-tab` / open one fresh tab and continue.
- A 410 `browser was restarted` on a per-posting call = the tab died, NOT a
  permanent backend death; reopen ONE tab and continue (session/cookies live
  in the profile). Don't restart the engine for a single dead tab.

Seen as: 2026-07-14 the first sourcing pass opened 5 parallel tabs → engine
wedged, all bundles reported 0, a full pass wasted. A single-serial-tab re-run
returned the real counts (CSJ 433, Hackney 15, LI alt 18/25/25/25/8, ID alt
8/16/16/16/5).
