# CAPTCHA policy — CANONICAL source

**Directive: solve every CAPTCHA the moment it appears, and carry on. A CAPTCHA is never a
reason to halt the loop, hand the tab to the user, or skip a posting.** Mirrored in SKILL.md,
GOAL.md, loop-prompt.md and goal-condition.txt; edit all of them together
(`references/maintaining-this-skill.md`).

## Solvers

| Challenge | Solver |
|---|---|
| reCAPTCHA v2 (checkbox / invisible badge / image grid) | `python3 sites/_common/scripts/recaptcha.py` — `click`, `wait-token`, `recheck`; `solve-grid --auto` for image grids (delegates to `tilevision.py solve`) |
| Cloudflare Turnstile | `python3 sites/_common/scripts/turnstile.py [sitekey]` |
| ALTCHA (CSJ) | `sites/civilservicejobs/scripts/feed.py` `solve_altcha()` |
| hCaptcha and any other image/tile/slider challenge | No shipped solver. `tilevision.py` is the generic per-tile classifier; try it on the grid. A challenge it cannot solve counts as a failed attempt |

## Procedure

1. Check for a popup tab first (`cfx.sh find-popup`); switch `CFX_TAB` if the challenge opened there.
2. Run the matching solver. Invisible reCAPTCHA (badge only) needs nothing: finish the form and
   submit; `recaptcha.py click` printing `NO-CHANGE` is normal.
3. Verify by screenshot (green checkmark, challenge gone, form accepted), never by JS token alone.
4. If a submit is rejected, screenshot and look for a missed required field before assuming the
   CAPTCHA failed.
5. Failed attempt: retry with a fresh challenge, pausing between tries (rapid retries raise the
   risk score). After 3 failed attempts on one posting, log `Blocked` with the reason, run
   `cfx.sh record-captcha-fail <domain>` and continue with the next posting.
6. `cfx.sh check-cooldown <domain>` before opening a posting on a domain whose challenge
   recently failed; on `cooldown active` log `Blocked` ("CAPTCHA cooldown") and move on.

## Mechanics

- reCAPTCHA grid: `solve-grid --auto` captures the crop, classifies each tile
  (NVIDIA → Nous → custom provider chain), trusted-clicks the picks, presses Verify and loops
  for bounded rounds. If `tilevision` fails, fall back to the agent-read `NEED_TILES` handoff
  (`solve-grid` phase A emits the crop and instruction, you pick indices by vision, phase B
  clicks them).
- Turnstile: the iframe sits in a closed shadow root, so `turnstile.py` reads the visible
  `.cf-turnstile` / `[data-sitekey]` host box, sends one trusted click at the checkbox and polls
  for a new `cf-turnstile-response` token. Returns `PASS`, `PASS:already-solved` or `FAIL:<reason>`.
