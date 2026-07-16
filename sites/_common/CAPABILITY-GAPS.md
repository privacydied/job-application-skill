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

## (add further gaps here as they're discovered)
