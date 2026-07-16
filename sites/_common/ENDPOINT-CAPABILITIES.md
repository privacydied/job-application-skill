# camofox-browser endpoint capabilities & anti-detection posture

A per-endpoint map of what the camofox REST backend
(`camofox-browser/server.js`) actually exposes, how
each surface is hardened against behavioral bot-detection, and what is
**genuinely absent** (so a future run doesn't waste time looking for a knob that
isn't there, or re-deriving a gap that's already understood).

This is the "logically think through every endpoint" reference. It complements —
does not replace — `CAPABILITY-GAPS.md` (which is for *newly discovered* backend
limitations) and the "Anti-detection / human-behavior shaping" section of
`SKILL.md` (which is the operator-facing summary). When you change an endpoint's
behavior, update the matching row here.

> **Two layers.** Every hardening below lives in one of two places, and the
> distinction matters for "is this live yet?":
> - **Skill layer** — `sites/_common/scripts/cfx.sh` (Claude Code path) and
>   `~/.hermes/hermes-agent/tools/browser_camofox.py` (Hermes path). Edits here
>   take effect on the **next invocation**, no deploy. These two MUST stay in
>   sync — every anti-detection behavior is implemented identically in both.
> - **Server layer** — `server.js` inside the container. **Bind-mounted**
>   (`compose.yaml`: `./camofox-browser/server.js:/app/server.js:ro`), so edits go
>   live on `docker compose up -d camofox-browser` (~seconds recreate), not a
>   rebuild. A recreate kills the live session — only deploy when idle.
>   (`lib/`/`plugins/`/`package.json` changes still need `docker compose build`.)

## Interaction endpoints (the ones that generate behavioral telemetry)

| Endpoint | What it does | Anti-detection hardening | Layer / status |
|---|---|---|---|
| `POST /tabs/:id/click` | Click by `ref`, `selector`, **`frameSelector`+`selector`** (inside a cross-origin iframe), or **`x`/`y`** (trusted coordinate click). 3-tier fallback: normal → force → full mouse sequence. | **Position jitter** — lands off dead-center (`jitteredOffset`, capped ≤30% of the box or 15px so small targets never miss). **Hold duration** — randomized mousedown→up (`jitteredHoldMs` 40–140ms) instead of Playwright's 0ms instant tap. Fallback mouse-move is **interpolated** (`steps:8–15`), not a teleport. Cursor curve between points comes from camoufox's `humanize` launch option. `frameSelector` uses `page.frameLocator` (pierces cross-origin frames → reCAPTCHA anchor checkbox); `x`/`y` do interpolated-move + held-press at coordinates (challenge tiles). | server ✓ live (jitter/hold, `frameSelector`, `x`/`y`); skill helpers `cfx.sh click-frame`/`click-xy`; pre-action pacing ✓ live |
| `POST /tabs/:id/type` | Enter text. `mode=fill` (instant, = paste) or `mode=keyboard` (real key events). | Skill layer routes **short text (≤70 chars: logins, names, single-line answers) → `mode=keyboard`** with per-key delay; long free text stays instant-fill (mirrors a human pasting prepared content). Server keyboard mode uses a **per-character loop** with independently jittered inter-key gap AND per-key hold — not Playwright's single fixed `delay` (which types a whole field at a perfectly uniform cadence). | server ✓ + skill ✓ |
| `POST /tabs/:id/press` | Press one key (Enter/Escape/Tab…). | Randomized hold duration (`jitteredHoldMs` 30–110ms) vs instant tap. | server ✓ |
| `POST /tabs/:id/scroll` | One trusted `mouse.wheel` event per request. | Skill layer **chunks** one logical scroll into several 100–250px wheel ticks with small gaps (`scroll_chunked`) — a real wheel/trackpad never delivers one atomic delta. Server stays one-wheel-per-call by design; chunking is the caller's job. | skill ✓ (server intentionally minimal) |
| `POST /tabs/:id/hover` | **Real `page.mouse.move()`, no click.** Accepts `ref`/`selector` (jittered point inside the element) or explicit `x`/`y`. Interpolated over steps. | This is genuine, browser-**trusted** idle mouse movement — the one thing `/evaluate`-dispatched JS mouse events can't fake (those arrive `isTrusted:false` and are *counterproductive*). Used by `orientation_pause` for ambient "looking around" between actions. | server ✓ live |
| `POST /tabs/:id/navigate` | Go to a URL. Accepts optional `referer`. | **Referer chains (NEW, wired end-to-end).** A raw navigate sends an empty `Referer` **and** `Sec-Fetch-Site: none` — on a deep link that pair is a textbook "arrived by automation" tell (confirmed live against a header-echo endpoint). The skill layer now auto-derives a plausible referer (`compute_referer`/`_compute_referer`): explicit arg → the tab's live current URL (link-click mimic) → `https://www.google.com/` for cold deep-link entry → none for a bare homepage. Firefox derives the correct `Sec-Fetch-Site` from the referer. | server ✓ live; skill wiring ✓ live |
| `POST /tabs/:id/upload` | `setInputFiles()` onto an `<input type=file>`. File must be under the `/uploads` bind mount. | Not a detection surface (no synthetic input); path is sandboxed to `/uploads`. See `CAPABILITY-GAPS.md` for the verified recipe. | server ✓ live |
| `POST /tabs/:id/viewport` | `page.setViewportSize()`. | Returns an **honest `verified` field** (+ measured `actual`) — the resize silently no-ops in headed Firefox (this stack always runs headed under VNC/Xvfb), so the old `{"ok":true}` was a false positive. Viewport **diversity is not needed here anyway**: camoufox randomizes window+screen per browser launch for free. The skill layer no longer calls this at all. | server ✓ live |

**Pre-action pacing wraps every interaction above** (skill layer, live): each
page-affecting call waits `human_pause` (~0.7–2.9s, ~1-in-6 a longer 2–6s
"reading" pause) first, and every *navigation* adds `orientation_pause` (2.5–6s
dwell + one idle scroll-or-hover). Root cause it fixes: 11 clicks logged ~2–3s
apart almost to the second preceded a real Turnstile failure — Cloudflare scores
the whole session's cadence, not just the challenge click. Escape hatches
(testing only, never for real applications): `CFX_NO_PACING`/`CAMOFOX_NO_PACING`,
`CFX_NO_KEYBOARD_TYPE`/`CAMOFOX_NO_KEYBOARD_TYPE`, `CFX_NO_IDLE_SCROLL`,
`CFX_NO_IDLE_HOVER`, `CFX_NO_REFERER`/`CAMOFOX_NO_REFERER`.

## Read / navigation-control / plumbing endpoints (no behavioral telemetry)

| Endpoint | Purpose | Notes |
|---|---|---|
| `POST /tabs` | Create a managed tab. | Fingerprint (window/screen/canvas/WebGL/TLS/UA) is set at **browser launch**, not per tab — every restart rotates it for free. Fails `Internal server error` at the tab cap (~8); reuse an idle `about:blank` tab or delete stale ones. |
| `GET /tabs`, `GET /tabs` (list) | Enumerate tabs for a user. | Backs `cfx.sh list-tabs`/`find-popup` — the popup-Turnstile discovery path. |
| `GET /tabs/:id/snapshot` | Accessibility-tree snapshot + refs. | Passive. Refs (`e3`, `e8`…) are what `click`/`type`/`hover` target. |
| `POST /tabs/:id/wait` | Wait for a condition/timeout. | Passive. |
| `POST /tabs/:id/back` · `/forward` · `/refresh` | History / reload. | Real browser navigation (carries native referer/history). `refresh` is used to fetch a fresh CAPTCHA token. |
| `GET /tabs/:id/links` · `/images` · `/downloads` | Extract page resources. | Passive read. |
| `GET /tabs/:id/screenshot` | PNG of the tab. | Passive. Backs the VL/vision CAPTCHA-solve path. |
| `GET /tabs/:id/stats` · `GET /metrics` · `GET /health` | Diagnostics. | `health` needs no auth — use it to confirm the engine is live. |
| `POST /tabs/:id/evaluate` | Run JS in page context. | **Never use to simulate input** — JS-dispatched mouse/key events are `isTrusted:false` and actively *hurt* the trust score. Fine for passive reads (e.g. `location.href` for the referer chain) and DOM inspection. |
| `POST /tabs/:id/extract` | Structured content extraction. | Passive. |
| `POST /sessions/:userId/cookies` | Inject/read cookies. | Session persistence. |
| `DELETE /tabs/:id` · `/tabs/group/:id` · `/sessions/:userId` | Teardown. | **RAM control — close a tab the moment a posting is resolved.** Camofox holds every open tab's page in memory and `POST /tabs` starts failing (`Internal server error`) at a **~8-tab cap**. Idempotent (`ok:true` even if already gone). `cfx.sh close-tab [tabId]` wraps `DELETE /tabs/:id`; closing is **safe** — login/cookies live in the profile, not the tab. Hermes reuses one tab across postings so it doesn't accumulate; `camofox_close` there deletes the whole *session* (`DELETE /sessions/:userId`), i.e. end-of-run only. |
| `POST /act` | **Second, independent** action-dispatch endpoint (batch). | Has its **own duplicate** click/type/press implementation — historically drifted from the `/tabs/:id/*` handlers. Brought to parity (position jitter, hold durations, per-char typing). If you harden a `/tabs/:id/*` interaction, grep `/act` for the same pattern and fix it there too. |
| `POST /start` · `/stop` · `/navigate` · `/snapshot` (legacy, non-tab) | Single-page legacy API. | Prefer the `/tabs/:id/*` API. |

## Genuinely absent — don't go looking for these

- **No drag-and-drop endpoint.** No way to do an HTML5 drag or a slider drag via
  the API. Slider/behavioral CAPTCHAs are therefore unsolvable here (log
  `Blocked`).
- **No touch / pointer-event API.** Mouse only. Fine — the fingerprint presents
  as desktop Firefox.
- **No per-request User-Agent / header override** (besides `referer`). The UA is
  fixed at launch by camoufox. Don't try to spoof per-navigation.
- **No caller-exposed hold/dwell params** on click/press. Hold durations are
  randomized *internally* (`jitteredHoldMs`) — you get realism for free and
  can't (and shouldn't) pin them.
- Normal clicks auto-jitter off-center internally, so no separate click-position
  param is needed (coordinate click via `x`/`y` exists for element-less targets —
  see the click row).

(Coordinate/iframe click, `/hover`, and `referer` used to be absent — they now
exist; see the interaction rows above.)

## Verifying a server.js change is live

`server.js` is bind-mounted (deploy = `docker compose up -d camofox-browser`), so a
change is live once the container has recreated and `curl -fsS
http://localhost:9377/health` shows `browserConnected:true`. To confirm a specific
endpoint, exercise it — e.g. nav a scratch tab to `https://postman-echo.com/headers`
with `referer:"https://www.google.com/"` and check the echoed `Referer` /
`sec-fetch-site: cross-site`.
