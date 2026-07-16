# CAPTCHA policy — CANONICAL source (perf-roadmap E.4)

This is the single canonical statement of the CAPTCHA policy and its solve/halt
mechanics. The safety-critical **directive** (full halt for any non-sanctioned CAPTCHA;
exactly two sanctioned auto-solves) is deliberately still mirrored inline in the
load-bearing surfaces (SKILL.md, GOAL.md, loop-prompt.md §4, goal-condition.txt,
loop-preflight.py, CAPABILITY-GAPS.md, per-board NOTES.md) — that redundancy is the
safety feature, do NOT remove it. What lives ONLY here is the detailed *mechanics*.
**Editing the policy? Update every mirror and run the audit grep in
`references/maintaining-this-skill.md`.**

## The directive (mirrored; keep it everywhere)

**⛔ FULL IMMEDIATE HALT of the whole loop for ANY CAPTCHA except the two sanctioned
exceptions.** User directive; overrides everything; stricter than a login wall.

## Sanctioned exception 1 — reCAPTCHA v2 family (auto-solve)

Checkbox / invisible badge / image-grid → `python3 sites/_common/scripts/recaptcha.py`:
- `click` / `wait-token` / `recheck` cover the checkbox + invisible badge cases.
- `solve-grid` covers the image grid: **Phase A** captures the crop + instruction and
  emits `NEED_TILES`; you pick the tile indices with vision; **Phase B** clicks them +
  Verify, looping multi-round up to `max_rounds`.
- **Verify results via SCREENSHOT (the green checkmark), not the JS token** — a stale
  `api2/bframe` iframe makes `detect` report a phantom open challenge.
- If a submit is rejected, screenshot first and look for a missed required field before
  concluding it's a CAPTCHA.
- This exception is narrowly the reCAPTCHA v2 solve — metronomic clicks elsewhere still
  degrade Cloudflare's risk score.

## Sanctioned exception 2 — ALTCHA on civilservicejobs.service.gov.uk ONLY

Deterministic client-side proof-of-work; auto-solved by
`sites/civilservicejobs/scripts/feed.py solve_altcha()`. **ALTCHA on any other site, or
any other CAPTCHA on CSJ, is still the full halt.**

## Everything else (Turnstile / hCaptcha / …) — the halt procedure

1. **Stop** — leave the tab open, the form filled exactly as-is.
2. **Message the user in that SAME turn:** company/role, site/URL, what's blocked, that
   it's **held**, + VNC `http://nasirjones:6080/vnc.html`.
3. **END your turn and wait.** Do NOT keep sourcing or touch other postings; do NOT fold
   it into an end-of-run summary; do NOT log `Blocked`-and-move-on (only if the user
   explicitly says "skip this one"); do NOT auto-solve or batch it.
4. On the user's "solved": re-verify it's cleared and finish the SAME application.

Mechanics:
- **Check for a popup tab first** — Turnstile can open as a real new tab (`cfx.sh
  find-popup`); switch `CFX_TAB` there to point the user at it (don't click it yourself).
- Manual VNC clicks may need a couple of tries (noVNC teleport clicks lack movement
  telemetry) — not a license to auto-click.
- Don't retry a failed Turnstile in a tight loop — fast retries compound the risk score.
  Log `Blocked` and let it cool off.
- **Cooldown:** `cfx.sh check-cooldown <domain>` before opening a posting on a domain
  that failed before (`cooldown active` → log `Blocked`, reason "CAPTCHA cooldown");
  `cfx.sh record-captcha-fail <domain>` the moment a challenge is *confirmed* failed (not
  merely seen) — exponential backoff capped 24h, shared across agents.
