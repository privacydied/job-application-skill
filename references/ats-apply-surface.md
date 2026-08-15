# ATS apply surface — what actually submits (verified live 2026-07-17)

`sites/ats-direct/` sources from employers' own ATS boards because those ATSes accept an
application with **no account** — which sidesteps the downstream-account wall that stops
Adzuna/WTTJ/Dots at submit time. That premise holds for **sourcing** (3,182 postings across
68 companies in one pass, keyless). It does **not** automatically hold for **submitting**:
most ATSes now put an anti-bot gate on the submit button, and each vendor's is different.

Sourcing and submitting are separate problems. Never infer one from the other.

## Per-vendor submit reality

| ATS | submit | gate |
|---|---|---|
| **Greenhouse** | ✅ **WORKS** | reCAPTCHA v2 — a *sanctioned* exception (`recaptcha.py`). Verified end-to-end: Monzo Content Strategist → `/confirmation` "Thanks for applying!" |
| **Lever** | ⛔ **hCaptcha** | Clicking `#btn-submit` renders a **visible hCaptcha challenge** (~720×1021) which then drives a hidden `#hcaptchaSubmitBtn`. hCaptcha is NOT sanctioned → **full halt** per `captcha-policy.md`. Fill works; submit doesn't. |
| **Ashby** | ⛔ **spam-flagged** | A fully valid form returns *"Your application submission was flagged as possible spam."* Reproduced twice (Lendable), including a slow human-paced refill. Ashby's location autocomplete also returns "No results" for every query in this browser — consistent with the whole backend refusing this client. |
| **Workable** | ⛔ **Cloudflare Turnstile** | Rejects camoufox's fingerprint; fails even for a human via VNC. Not sanctioned → halt. Pre-existing finding, still true. |
| **SmartRecruiters** | ⚠️ **browser-only** | **No account wall and NO form CAPTCHA — both verified.** But the documented candidate API is token-gated (401 anonymously; the `/v1/companies/.../candidates` variant does not exist), and the `oneclick-ui` apply SPA sits behind a **DataDome** device check, so it is NOT HTTP-drivable. It IS drivable through the browser: see `sites/smartrecruiters/NOTES.md` (shadow-DOM form — use Playwright `role=` selectors via the REST `selector` param, NOT `evaluate`, which is blind here). This repo already drove one to the screening page (Experian, 2026-07-16). The most promising unexplored channel. |
| **Recruitee** | ⛔ **hCaptcha** | Account-less and otherwise trivially drivable (plain multipart POST to `/candidates`, no CSRF, server-rendered inputs) — but hCaptcha-gated on **34/34** live boards, white-labelled behind `*.recruiteecdn.com` with one global sitekey. hCaptcha is a named full-halt vendor in `captcha-policy.md`, so this is **policy-blocked, not merely hard**. Verified over HTTP 2026-08-15; no submit attempted. |

**Net (updated 2026-08-15):** Greenhouse remains the one proven *HTTP-and-browser* channel.
Of the two previously-untested vendors, **Recruitee is policy-blocked** (hCaptcha) and
**SmartRecruiters is the single best remaining lead** — no account wall, no form CAPTCHA,
blocked only by DataDome on the SPA, so a *browser* driver is plausible where an HTTP one is
not. If more volume is ever needed, building `sites/smartrecruiters/scripts/apply.py` against
the existing shadow-DOM `role=` recipe is worth more than any further Greenhouse
company-registry expansion, which has hit clear diminishing returns (round 3: 1,295
SmartRecruiters slugs -> 39 usable; 2,582 Recruitee slugs -> 45, of which ~25% were ATS demo
tenants that answer HTTP 200 forever).

⚠️ **Two liveness traps found while probing** (both now in `sites/ats-direct/NOTES.md`):
an unknown **SmartRecruiters** slug still returns **HTTP 200** with `{"totalFound":0}` — status
alone is worthless, gate on `totalFound>=1`; and **Recruitee** seeds every trial signup with a
demo posting, so abandoned sign-ups look live forever — inspect posting *titles*, not counts.
Recruitee also rate-limits hard (429 at 8 concurrent, indistinguishable from "no board").

Source everything; route
submissions to Greenhouse first, and treat a non-Greenhouse row as sourced-only until its
> Workable ⛔ Turnstile. Route submissions to Greenhouse first, and treat a non-Greenhouse row as sourced-only until its vendor is proven.

## Form mechanics learned the hard way

**Location autocompletes ignore a plain value-set.** Lever's `#location-input` and Greenhouse's
`#candidate-location` both keep the real answer in a hidden field (`selectedLocation`) that
only populates when a suggestion is *chosen*. A synthetic `value` set (or `atsform fill`)
leaves the visible box looking right and the hidden field empty → submit rejects with
"Please select a location from the dropdown menu". Recipe that works:

1. Type with **real keystrokes**: `POST /tabs/<tab>/type {selector, text, mode:"keyboard", delay:90}`.
   A synthetic `input` event does **not** fire the suggest XHR.
2. Wait ~5s, read the options (`aria-controls` listbox, or `.dropdown-results`).
3. Dispatch the **full native pointer sequence** on the chosen row —
   `pointerdown, mousedown, pointerup, mouseup, click`. **`mousedown` is the one that
   matters**: these widgets commit on mousedown to beat the input's blur. `click_selector`
   alone sets the visible text but leaves the hidden field empty.
4. Verify the **hidden** field, never the visible one.

**`/type` and `/click` take `selector` OR `ref` — and `cfx.sh` sends `ref`.** So
`cfx.sh type '[name="x"]' …` fails with `stale_refs` for a CSS selector. Use
`cfx.post(f"/tabs/{tab}/type", {"selector": …})` / `cfx.click_selector(sel)` instead.

**Greenhouse's upload verify false-negatives.** `atsform upload` reports `FAIL: NONE` while
the file *is* attached — Greenhouse swaps the `<input type=file>` out for a filename display
after upload, so the post-verify can't find the input. Confirm via
`.file-upload__filename p` text, not the input.

**Lever clears the resume on a failed submit.** `resumeStorageId` empties; re-upload before
retrying or you get "Please attach a resume" forever.

**`type=number` fields reject formatted money.** `"£55,000"` fails; send `55000`.

**Lever leaks the browser's timezone** into a hidden `timezone` field (it sent
`America/Los_Angeles`). Set it to `Europe/London` before submit — it's on his application.

## Answering rules that came up

- **EEO / demographic questions are optional** on every form seen here and have a
  "prefer not to say" option. Leave them blank — they are personal characteristics, not the
  agent's to answer. If a consent checkbox only covers the demographic survey, leave it
  unticked when the survey is blank.
- **"Cannot recall" is a legitimate answer** when the profile genuinely doesn't record
  something (Canonical's high-school grade dropdowns). Picking a percentile would be
  fabrication.
- **Unemployment**: "Current company" → `<last employer> (most recent)`. Accurate, not
  misleading.
