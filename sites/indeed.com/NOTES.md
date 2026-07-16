# indeed.com / smartapply.indeed.com ("Indeed", "Indeed Easy Apply") — site notes

Indeed is a guest-browsable board (no login to search/read) AND, for "Easily apply" jobs,
its own lightweight ATS (`smartapply.indeed.com`). Applying requires an Indeed account.

## ⛔ The #1 time-sink: `cfx.sh click`/`click-xy` silently no-ops here — JS-click + verify
Across the whole Easy Apply flow (CV-options, Continue, Go back, Preview, radios,
checkboxes, Submit) `cfx.sh click` returns success-shaped JSON (sometimes literally
`{"error":"Internal server error"}`) while the click NEVER reaches the element (React
re-renders faster than the click resolves / overlays steal the target). Fix — fire a real
DOM `.click()` via `/evaluate`, and ALWAYS re-evaluate to confirm the state changed:
```
POST /tabs/{tab}/evaluate
{"userId":"nasirjones","expression":"[...document.querySelectorAll('button')].find(b=>b.textContent.trim()==='Continue')?.click(); true"}
```
Radios/checkboxes (same no-op, e.g. work-permit / security-clearance groups) — target by
value and verify `.checked` in the SAME call: `document.querySelector('input[value=\"33039\"]').click()`.
Confirm `.disabled`/`.checked`/`location.href` actually changed before assuming success
(same false-positive as `sites/recruitee/NOTES.md`, far more pervasive here).

## ⚠️ Smart Apply silently attaches WRONG data from account history — verify BEFORE submit
"Apply with Indeed" can jump straight to Review (100%) using stored account data. Two fields
were wrong live and BOTH must be checked on the full scrolled Review page:
1. **"Relevant experience"** pre-filled from the account's stored `workExperienceOptions`
   with an unrelated entry (a real hospitality job from the underlying account). Fix: its
   "Edit" → `.../resume-module/relevant-experience` → two plain `<input role=combobox>`
   (`#job-title-input`, `#company-name-input`, NO a11y ref) → set via `getElementById` +
   native value setter + `dispatchEvent(new Event('input',{bubbles:true}))` → "Continue".
2. **CV** auto-attached is whatever was LAST used on the account (a stale prior resume), not
   a fresh upload. Fix: its "Edit" → `.../resume-selection-module` → upload straight to the
   hidden input (skip the CV-options menu):
   ```
   POST /tabs/{tab}/upload  {"userId":"nasirjones","selector":"input[type=file]","path":"<file>.pdf"}
   ```
   Verify via the page-count next to the thumbnail changing (e.g. "1/2"→"1/3"); the thumbnail
   image renders slowly, so a blank thumb ≠ failure but also ≠ success — check the count.
Both cards live in the MAIN document. The Review page's "Edit" LINKS themselves live in the
`mosaic-provider-module-apply-preview` iframe (no a11y refs) — reach via
`document.querySelectorAll('iframe')` + `.className.includes('apply-preview')` +
`.contentDocument` + `getBoundingClientRect()` coordinate math.
Also: a pre-existing account may default-select an unrelated CV on EVERY apply flow — always
check the CV radio's selected filename; don't assume a fresh login starts CV-less.

## Submit button
- **Use native `element.click()`, not `cfx.sh click`** (500s here):
  `[...document.querySelectorAll('button')].find(b=>b.textContent.trim()==='Submit your application')?.click()`
  (confirmed by the `/graphql` submit firing). Success → URL `.../form/post-apply` + "Your
  application has been submitted!".
- A transient "trouble submitting your application" modal after a native click is RETRYABLE
  (not a hard fail) — close its lone `<button>` in `[role=dialog]`, native-click Submit again.
- **Starts `disabled` and does NOT enable on a timer** — it needs the "Preview what the
  employer sees" modal opened + closed first (reproducible). Try that before assuming a field
  is missing.
- Indeed Easy Apply's Review has an **enterprise reCAPTCHA v2 checkbox** (cross-origin iframe)
  gating Submit — now reachable via `/click` `frameSelector` / `recaptcha.py` (covers
  enterprise). **CAPTCHA policy still applies: STOP + hold + hand to the user** unless opted
  in. Red herring: a "What employers see…" info modal renders over the same area — the real
  reCAPTCHA sits just above Submit (screenshot the full scrolled page).

## Sourcing — `scripts/feed.py`
Guest search → distinct `{id,url,title,company,location}` by `data-jk`. **Dedups against the
FULL tracker in code** (`load_seen_jks()` regex-scans the whole tracker for `jk=` tokens;
`--all` opts out) — no manual dedup step. Auto-dismisses the "Get new jobs by email" modal
(`#mosaic-serpModals`) via `scripts/dismiss_modal.py`. Usage:
`feed.py --nav "https://uk.indeed.com/jobs?q=UX+Designer&sort=date&fromage=7" --pages 2`.
Empty (exit 1) = exhausted → `board-cooldown.sh mark indeed "<query>"`.
- **⚠️ `jk` is not always stable** — Indeed re-serves some postings under a new jk (repost /
  ephemeral id), and a sponsored slot can emit a placeholder-looking jk (`fedcba9876543210`)
  from the `id`-fallback (`data-jk || id.replace(/^job_/,'')`). Pure jk dedup can miss these —
  give a "fresh" result's title+company a glance if it looks familiar. TODO: content-based
  (title+company+location) dedup pass as a safety net.
- **⚠️ Multi-phrase `or` queries silently degrade** to loose/related matching (`"UX Designer"
  or "Product Designer"` returned "Multimedia Designer", "Product Owner", etc. — none literal;
  a LONE quoted phrase stays exact). It's specifically `or`, not parens/exclusions. No loop fix
  needed — the `target-roles.md` title pre-filter drops the noise before opening. Treat an
  Indeed result set as recall-widening, NOT a hard filter. (LinkedIn's OR-bundle is unaffected.)
- **Screening tip:** for a generic company name + a suspiciously specific salary-banded tech
  role, `web_search "<exact street address>" company` fast-resolves agency/fake-vs-direct
  (a "UX Designer" posting's address was a shisha lounge). JD phrasing alone is a weak signal.

## Hiding Applied/Skipped — "Not interested" (NOT on Blocked)
Cards have a **"Not interested"** button (results + detail). Use on every `Applied`/`Skipped`
so repeat searches don't resurface them. `scripts/feed.py hide <jk>` finds by `data-jk` and
clicks it — handles the two gotchas: it's an icon button with empty `textContent` (label only
in `aria-label="Not interested"`), and clicking collapses the card in place (node stays, goes
empty) rather than removing it → "hidden" = node gone OR near-empty. Manual:
`[...document.querySelectorAll('button')].find(b=>b.textContent.trim()==='Not interested')?.click()`.

## Login / account
- "Apply on company site" OR "Apply with Indeed" triggers `secure.indeed.com/auth` — a full
  account wall. **Treat as a login wall blocking the BOARD** (not one posting) per SKILL.md.
  Even some external-ATS "Apply on company site" jobs (BAE, UNiDAYS) insert Indeed's account
  gate ("You must create an Indeed account before continuing…"); once logged in it proceeds.
- **Email/password account creation is pre-approved** (SKILL.md hard-stop exception, like
  Workday) — don't wait for the user unless it demands phone verification.
- Screener radios (work permit, security clearance, "28+ days outside UK", notice/salary,
  "how did you hear") recur on public-sector postings (CGI, BAE) — drive with the JS-click +
  verify pattern above; plain text `<input>`/`<textarea>` work with normal `type`.
- Postings WITHOUT "Easily apply" route straight to the employer's external ATS
  (Greenhouse/Lever/Workday/Ashby — recipes under `sites/`), skipping smartapply entirely —
  often the smoother path.
