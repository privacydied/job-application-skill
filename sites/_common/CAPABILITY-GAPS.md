# Known capability gaps in the camofox REST backend

Cross-cutting limitations of the camofox REST API (`sites/_common/scripts/cfx.sh`)
that affect automation on ANY site, not one site's quirk. Check here before
assuming a stuck flow is a site-specific bug — it might be something this
backend genuinely cannot do yet.

## Agent-agnostic by design: always use `cfx.sh`/`cfx.py`, never the native `browser_*` tools
Both Claude Code and Hermes run every action through `sites/_common/scripts/cfx.sh` /
`cfx.py` via a shell/terminal tool — this is the ONE interface, same capability on
both paths. **Never use Hermes's built-in `browser_navigate`/`browser_click`/etc.**
(`~/.hermes/hermes-agent/tools/browser_camofox.py`) — it's a thin, incomplete subset
(no JS eval, no tab listing, no coordinate/iframe clicks, no file upload at all) that
has caused real misdiagnoses. `cfx.sh`/`cfx.py` give the full backend surface on
either agent, since both have a real shell (`terminal_tool` on Hermes, `Bash` on
Claude Code).

**Clicking something that might open a new tab or do nothing** (external-ATS "Apply"
buttons): use `python3 cfx.py click-follow <ref>` (or `--selector <css>`), not a plain
click. One call, returns `{"outcome": "new_tab"|"same_tab_nav"|"no_change", ...}` —
handles the click endpoint's own hang/500 on dead-click buttons internally. See its
docstring in `cfx.py` for the full mechanics.

## File upload — `POST /tabs/{tabId}/upload` (resolved, was previously a hard gap)

Calls Playwright's `elementHandle.setInputFiles()`. Host dir `job-application/uploads/`
is bind-mounted into the container at `/uploads` — only files placed there are visible.
1. Stage the file in `uploads/` (`chmod 644`).
2. `POST /tabs/{tabId}/upload {"userId":"nasirjones","ref":"e6","path":"resume.pdf"}`
   (or `"selector"` instead of `ref`) — path is relative to `/uploads`.
3. **Verify it attached** — don't trust `{"ok":true}` alone; `evaluate`:
   `document.querySelector('input[type=file]').files[0].name` should show the real name.
4. Clean up scratch files from `uploads/` after use — shared staging, not storage.

## Cloudflare Turnstile can reject camoufox's fingerprint entirely — even a genuine human click via noVNC

Confirmed on FE Fundinfo's Workable application (`apply.workable.com`): scripted click →
no-op (expected, Turnstile blocks synthetic events). A live human click via noVNC
registered but returned "verification failed" — including after a hard reload for a
fresh token, and across three clean attempts confirmed NOT to be a popup-tab visibility
issue (`find-popup`/`list-tabs` showed nothing; the widget was confirmed inline via
direct visual inspection). Because noVNC drives the same underlying camoufox browser,
a human clicking through it doesn't bypass this — **the browser's spoofed fingerprint
itself is what Cloudflare's risk model is distrusting**, not the click. No click
strategy fixes this from inside the current camofox instance.

**Playbook:** run `cfx.sh find-popup` first (a Turnstile widget can genuinely open as a
separate tab — real, still worth checking). If empty and the widget is inline, don't
keep cycling reload→retry — log `Blocked` after one genuine human-via-VNC click has
failed, citing this file. Needs a genuinely different browser environment to pass, not
more attempts.

## Direct navigate sends no Referer + `Sec-Fetch-Site: none` — fixed

A bare `page.goto(url)` (any `cfx.sh nav`) carries no `Referer` and `sec-fetch-site:
none` (confirmed against a header-echo endpoint) — on a deep job-posting URL that's a
tell no real click-through would produce. **Fix:** `/navigate` accepts an optional
`referer` (Firefox derives the right `Sec-Fetch-Site`); the skill layer auto-derives a
plausible one with no operator friction. See `ENDPOINT-CAPABILITIES.md`'s navigate row
for precedence rules and the `CFX_NO_REFERER`/`CAMOFOX_NO_REFERER` escape hatch.

## `/click` can reach cross-origin iframes and coordinates — fixed (server.js)

> ⚠️ **Capability record, not a default workflow.** The cross-origin `/click` + `click-xy`
> fix is what *enables* the reCAPTCHA v2 auto-solve — it must NOT be used to script around
> **non-sanctioned** CAPTCHAs (Turnstile/hCaptcha stay a hard stop, per SKILL.md). The
> sanctioned auto-solve is `recaptcha.py` for **all reCAPTCHA v2 forms** (checkbox /
> invisible badge / image-grid), pre-authorized by standing user directive — never for
> Turnstile/hCaptcha. (The only other sanctioned CAPTCHA auto-solve is ALTCHA on
> civilservicejobs.service.gov.uk — a deterministic proof-of-work checkbox handled by
> `sites/civilservicejobs/scripts/feed.py`, user-sanctioned 2026-07-13; ALTCHA on any
> other site is still a hard stop.)

`/click` originally only resolved `ref`/`selector` on the main frame, so a reCAPTCHA v2
anchor checkbox (inside cross-origin `iframe[src*="recaptcha/api2/anchor"]`) was
unclickable, and there was no coordinate click for canvas-only widgets. **This was an
endpoint gap, not a Playwright limit** — `frameLocator` pierces cross-origin iframes
natively because it drives the browser's automation protocol (Juggler/CDP), not page
JS (which a same-origin policy does correctly wall off — confirmed `iframe.contentDocument
→ NULL` via `/evaluate`, while `frameLocator` reached the checkbox and the click landed).
Fixed in `server.js`'s `/click`:
- **`frameSelector`** (+ `selector`) → `page.frameLocator(frameSelector).locator(selector)`.
  Skill helper: `cfx.sh click-frame 'iframe[src*="recaptcha/api2/anchor"]' '#recaptcha-anchor'`.
  The image-challenge tiles live in a second frame `iframe[src*="api2/bframe"]` — same
  approach, `.locator('table td').nth(i)`.
- **`x`/`y`** → trusted `mouse.move→down→hold→up` at page coordinates. Skill helper:
  `cfx.sh click-xy <x> <y>` — for canvas tiles, screenshot → VL model picks each tile's
  centre.

**Clicking ≠ passing.** reCAPTCHA v2 is lenient — a genuine trusted click often passes
outright or drops to a solvable image challenge, so this fix materially helps it.
**Cloudflare Turnstile is different** — per the fingerprint-level failure above, even a
perfect trusted click still fails; this click fix does not address Turnstile. Diagnose
by logo before spending time: reCAPTCHA (Google, "I'm not a robot") → worth trying;
Turnstile (Cloudflare, "Verify you are human") → still a hard `Blocked`.

**Verifying pass/fail: read the real state, don't infer it (2026-07-13).** `/eval-frame`
(mirrors `/click`'s `frameSelector`, but for reads — `page.$(frameSelector).contentFrame()`
+ `frame.evaluate(expression)`) lets a caller read `#recaptcha-anchor`'s actual
`aria-checked` from inside the anchor iframe directly, instead of inferring pass/fail
from the main-page `g-recaptcha-response` token or a screenshot. Both of those older
signals can go stale — a leftover `api2/bframe` iframe element can survive in the DOM
after the checkbox already passed, making a main-page-only check report a phantom
"challenge still open." Skill helpers: `cfx.sh eval-frame <frameSel> '<js>'` /
`cfx.py eval_frame(frame_selector, expression)`. `recaptcha.py` (see its docstring) was
rewritten to use this as ground truth, keeping the token as a secondary signal only.

**`recaptcha.py` also handles (2026-07-13):**
- **Invisible reCAPTCHA** (badge, no checkbox) — `detect`/`click` recognize the
  `.grecaptcha-badge` div (readable from the main page even though its own content is
  an iframe) and correctly report "nothing to click here" instead of trying to click a
  checkbox that doesn't exist. `wait-token` polls the main-page token until the real
  form action (e.g. Submit) triggers it.
- **Token expiry** — `recheck` (call right before Submit) re-clicks up to 2 times with
  a cooldown if `aria-checked` has flipped back to false since it was solved
  ("Verification expired" is a real, observed message), then halts — never retries
  beyond that bound.
- **Image-grid challenge — AUTO-SOLVED (2026-07-13, user pre-authorized).** `solve-grid`
  is a two-phase solver matching the skill's house style (the agent supplies
  vision-reported tile coordinates; the script does the trusted clicking):
  - **Phase A** `recaptcha.py solve-grid` — confirms a grid is actually open (ground
    truth via `_challenge_open`), runs `challenge-snapshot` (real instruction text from
    inside the bframe via `eval-frame` + a cropped screenshot), reads each tile's
    page-coordinate centre and the Verify button via `_bframe_geometry` (rects read
    inside the bframe, offset by the bframe's page position), persists everything to
    `captcha-solve-pending.json`, and emits **NEED_TILES (exit 4)** with the
    instruction + crop path + tile count.
  - **Phase B** `recaptcha.py solve-grid --tiles "0 4 7"` — clicks each named tile
    centre via trusted `click-xy`, clicks Verify (click-frame inside the bframe),
    waits, then re-checks. Passed → `GRID SOLVED`. A NEW round opened → loops back to
    Phase A (capped at `max_rounds`, default 3). The **VL model (the agent, reading the
    crop with native vision) decides which tiles match** — the script never guesses
    pixels. Every attempt is logged to `captcha-audit.csv` (`GRID_SOLVE_PASSED`,
    `GRID_SOLVE_FAILED_ROUNDS`, etc.). `challenge-snapshot` remains as a standalone if
    you ever want the crop without auto-solving.
- **The VL read AND the clicking are now one shipped solver (2026-08-26): `tilevision.py solve`.**
  The one explicitly unbuilt step — "the agent reads the crop" — is automated: it slices the
  persisted crop by the Phase-A tile rects (`tile_rects` in captcha-solve-pending.json)
  and classifies EACH TILE independently YES/NO. Whole-grid indexing ("reply with the
  tile numbers") was validated to FAIL on small open VLMs; per-tile binary classification
  was exact on a real grid including the sign-depicting-a-light trap case.
  `tilevision.py solve` is the END-TO-END grid solver: capture → per-tile classify →
  trusted click (recaptcha's `_click_xy`/`_click_verify`, imported — not re-rolled) →
  Verify → bounded rounds; `recaptcha.py solve-grid --auto` is a thin delegation into it.
  Provider chain NVIDIA→Nous→custom (`TILEVISION_*` env); no provider or all-fail ⇒
  falls back to the agent's own vision read of the same crop. One-home guard:
  `tests/test_core.py::TestTileVision::test_vision_call_has_one_home` fails any second
  script that grows its own vision endpoint.
- **Per-domain memory** — `captcha-type-memory.csv` (skill root, one row per domain,
  auto-updated by `detect`/`click`/`solve-grid`) records whether a domain has shown a
  v2-checkbox, invisible, or grid CAPTCHA — `check-type <domain>` lets a future run
  decide pre-emptively instead of re-discovering it mid-form.
- **Audit trail** — every `click`/`recheck` attempt (regardless of outcome) is appended
  to `captcha-audit.csv` (skill root): timestamp, domain, job ref, screenshot path,
  result — so every automated action this script takes is reviewable afterward.

## ALL mouse endpoints (click/click-xy/hover/scroll) 500 across every tab — a real, self-healing server fault (2026-07-13)

Confirmed live: `click`/`click-xy`/`hover`/`scroll` 500 on **every** element, **every**
tab (unrelated postings, search results, even a throwaway `example.com` tab), while
`press`/`evaluate` keep working and `/health` looks totally normal. **Diagnose fast:**
open a scratch tab, click anything on `example.com`; if that 500s too, it's this global
fault, not whatever button you were actually debugging. (Turned out to be a red herring
for the LinkedIn case below — a real, separate bug was hiding underneath it.)

**Fix:** `docker compose restart <service>`, not `up -d` — `up -d` is a no-op on an
already-running container whose bind-mounted file changed but whose tracked
config (image/env) didn't (verified: zero effect, tabs/memory unchanged).

**Diagnosis is automatic; restarting never is (2026-07-13 correction).** In `cfx.py`:
- `engine_click_healthy()` — injects a normal-sized (24×24px — a 1×1px target gave a
  false negative, small enough for the click endpoint's own position-jitter to miss even
  when healthy) invisible button into the current page, clicks it, confirms via a JS
  flag. Read-only, no side effects. No new tab needed (`POST /tabs` with a `data:` URL
  500s here — don't use that).
- `restart_engine()` — passwordless-sudo restart (below), polls `/health` up to ~90s
  (the restart CLI call itself can take 40–90s via subprocess despite looking instant
  interactively).
- **`click_and_follow(..., auto_heal=True)` (default) runs the diagnosis automatically**
  before ever reporting `no_change`: healthy → reported as-is; not healthy → returns
  `engine_broken_needs_restart` (a pure diagnosis) instead of `no_change`. **It does NOT
  call `restart_engine()` itself.** An earlier version did, and it killed a tab
  mid-navigation during a real live application (the click's own auto-heal fired
  unprompted, mid-flow, before any fields had been filled — no data was lost only by
  luck of timing). Restarting drops every open tab, including any in-progress form on
  the current one, so it must always be an explicit, deliberate call the agent makes
  after confirming nothing valuable is in flight (or after asking the user) — never
  something a diagnostic function does on its own.

**Passwordless restart:** `/etc/sudoers.d/camofox-restart` grants `<your-user>` NOPASSWD for
exactly `docker compose -f compose.yaml restart
camofox-browser` (+ `up -d`). Works identically on Hermes/Claude Code — both have a real
shell, nothing about Hermes's tool wrapper needed to change. **Drops all open tabs**
(cheap to re-source) but **does not log anyone out** — cookies live in the camoufox
profile, not the tab.

## `dismissConsentDialogs()` was auto-closing a real application modal, not just cookie banners — the actual LinkedIn "dead click" (2026-07-13, corrects a wrong prior conclusion)

LinkedIn's external "Apply on company website" button genuinely opens a real dialog —
**"Share your profile?"**, with a "Continue" link — before handing off to the destination
ATS. It was never a dead button. But `/tabs/:id/click` calls `refreshTabRefs` →
`waitForPageReady` → `dismissConsentDialogs` after **every** click, unconditionally — and
that function's selector list, despite being documented as cookie/privacy-only, included
several with zero cookie-specificity (`button[aria-label="Close"|"Dismiss"]`,
`[class*="modal"|"overlay"] button[class*="close"]`, generic `dialog button:has-text(...)`
patterns). LinkedIn's modal's close control matched one of these, so the SAME `/click`
request that opened the modal also closed it — before any snapshot/screenshot/JS hook
could ever see it. Every earlier "verified no window.open, no modal" finding was real,
just diagnosing the aftermath, not the actual event.

**Fixed:**
1. `server.js`'s `dismissConsentDialogs()` — removed the four generic entries + the
   generic `dialog button:has-text(...)` set; kept only genuinely cookie/consent/privacy/
   GDPR-scoped selectors. **Never add back a bare "any modal's close button" pattern.**
2. `cfx.py`'s `click_and_follow()` now runs `_click_through_confirmation_dialog()`
   automatically before reporting `no_change` — detects a dialog (main doc or shadow
   root) and clicks an unambiguous "Continue"/"Agree" control (never "Cancel"/"Close").
   No safe control found → returns `unhandled_dialog` (with dialog text) instead of
   guessing or reporting `no_change`.

**Verified end-to-end** on two previously-`Blocked` postings: `click-follow` now returns
`new_tab` with the real destination ATS (a real, loadable `jobs.micro1.ai` application
form). **Any posting logged `Blocked` for "dead click on external Apply" is not actually
stuck — retry it.**

## Greenhouse required react-selects rendering with NO options (broken employer form, 2026-07-20)

When driving `gh_apply.py` on a subset of LIVE greenhouse postings, several **required**
react-select fields open with an empty option list (`combobox_pick` → `NO_OPTION:No options`,
and `document.querySelectorAll('.select__option')` returns `[]` after clicking). Confirmed on
**Monzo** (`Please confirm your UK Right to Work status`), **GoCardless** (`Your privacy at
GoCardless`, `Pay range transparency`), and **Vercel** (`Your authorization to work in the
country where you will be based`) — three independent employers, so this is an employer-side
broken/async-loaded form, NOT a camofox/driver bug (camofox health was `ok:true`,
`consecutiveFailures:0`; the page titles + other fields loaded fine). `gh_apply.py` correctly
logs these `Blocked` (validation error at submit, no email code fires).

**Implication for the convertible pool:** a meaningful fraction of cached greenhouse candidates
have forms that are currently undrivable walls. Do NOT assume the `convertible_pool.py` count
of greenhouse candidates = submittable. Before crediting a greenhouse role as drivable, open the
form and confirm its required react-selects actually populate options. If a fresh re-source (after
the 12h cooldown) still shows empty options, it's a genuinely broken posting → `Blocked`, move on.
Do not burn the 2-attempt budget re-trying the same empty-option field.

## Claude Code and Hermes sharing the SAME persisted `.jobenv.run`/`.jobenv.persist` tab pointer causes silent cross-agent tab hijacking (observed live 2026-08-26)
Both agents write the same `CFX_TAB` into the same skill-directory env files. Mid-session,
while actively driving a SuccessFactors application on the pointer's tab, the tab's title/URL
was found to have changed out from under the running script to an unrelated WTTJ posting, and
later to a Canonical Greenhouse posting — with no error from the driver, just a page that was
no longer the one it thought it was on (this produced a real, confusing `NO_APPLY_BUTTON`
failure that looked like a form-driver bug but was actually the OTHER agent navigating the
shared tab away mid-run). `cfx.active_tabs()`/`claim_tab()` (the parallel-lanes registry) did
**not** protect against this — the registry was empty even while the hijack was happening,
meaning the other process either isn't calling `claim_tab` at all, or its claim had already
expired (`TAB_CLAIM_TTL`). **Practical fix that worked:** stop touching the shared pointer,
mint a genuinely fresh tab via `cfx.open_tab('about:blank', guard=True)` (NOT `ensure_tab`,
which just returns the current tab if it's still alive/in `list_tabs()` — it will happily hand
you back the SAME contested tab), `claim_tab()` it, and drive it via a PRIVATE env file/shell
export that is never written to `.jobenv.run`/`.jobenv.persist` — so the other agent keeps its
pointer and never gets its tab stolen either. Close and `release_tab()` your private tab the
moment your task resolves. **If a running driver's page state looks impossible (a field you
just filled reads empty, a button search fails that should obviously exist, a title you don't
recognise), check `location.href`/`document.title` FIRST before assuming a form-widget bug —
a same-tab hijack by the other agent is a real, live possibility, not a hypothetical.**

## Upload endpoint can't reach a file input nested two iframes deep (2026-08-28, Hippo Digital registration on careers.hippodigital.co.uk)

`POST /tabs/<tab>/upload` (wrapped by `atsform.upload()`) only resolves its `selector`
against the TOP-LEVEL document. `cfx.eval_frame()` can read/write text fields inside a
cross-origin iframe fine (and even inside an iframe nested a further level deep, e.g.
`iframe[src*='UploadFile.aspx']` reachable straight from the top level via `eval-frame`
without chaining), but the SAME reach does not extend to `/upload` — every variant tried
(a bare selector, a Playwright `>>>` piercing chain, and payload params `frameSelector`/
`frame`/`iframeSelector`/`frameUrl` alongside `selector`) returned `HTTP 500 Internal
server error`. Concretely: Hippo Digital's candidate registration is an ASP.NET WebForms
iframe (`registration.aspx`) whose "Upload CV" button calls `OpenBox()` to open a SECOND,
nested iframe (`/Popups/UploadFile.aspx?...`) containing the real `<input type=file>`
(`class="ruFileInput"`, a Telerik RadUpload control). Every other field on the outer
registration iframe (name/email/password/address/radios/consent) filled correctly via
`cfx.py eval-frame` + native-setter value/checked assignment — only the doubly-nested
file input was unreachable. Not yet fixed (no server-side support found for nested-frame
uploads); logged the posting `Blocked` rather than spend a 3rd attempt. If this pattern
recurs (any GDS/Telerik RadUpload-style "click to open an upload popup" ATS), the fix
would need to live in the camofox server's `/upload` handler (frame-tree traversal by
selector, matching what `/eval-frame` already does) — a client-side workaround was not
found this session.

## `uploadViaChooser` endpoint returns HTTP 500 (confirmed broken, 2026-08-28)

`atsform.upload_chooser()` / the raw `POST /tabs/<tab>/uploadViaChooser` endpoint is
documented as the fix for exactly the "no `<input type=file>` exists until a button
click opens a native OS file-chooser" pattern (CVLibrary-class widgets) — but tested
live against a genuinely chooser-gated Airtable form field (Compucorp's DevOps
Engineer application, "Drop files here or click to browse", which uses the File
System Access API with zero DOM fallback — confirmed no `<input type=file>` anywhere,
including inside the page's one shadow root, checked immediately post-click with no
delay) and it returned `HTTP 500 Internal server error` every time, regardless of the
`trigger` selector syntax tried (`text=...`, a plain CSS class). Matches the
docstring's own caveat ("Requires the server.js route (deployed via a camofox
container restart)") — the route is very likely just not deployed on this camofox
instance. Net effect: any form whose file input is TRULY chooser-gated (no DOM
fallback, not even a transiently-mounted one) is currently unfillable by this
toolkit — log `Blocked`, don't keep retrying the same 500 across sites.

## (add further gaps here as they're discovered)
