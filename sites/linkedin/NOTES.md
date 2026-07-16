# linkedin.com/jobs (LinkedIn) — site notes (sourcing recipe)

Highest-quality role targeting, but **login-gated**. Treat login as a hard stop:
confirm a logged-in session first; if walled, message the user to log in at
`http://nasirjones:6080/vnc.html` and WAIT (see SKILL.md login-wall rule) — don't
scrape logged-out (LinkedIn bot-walls guests hard).

**2026-07-13: sourcing recipe confirmed live-working.** Session was already logged in
(sidebar showed "Jane Doe"), no login wall hit. The `keywords=`+`location=`+
`f_TPR=r604800`+`sortBy=DD` search URL works and the results heading
(`"<query> in <location>" · N results`) confirms the query actually applied — but the
**result set is noisy**: promoted/sponsored cards for totally unrelated roles (Senior
Marketing Manager, Co-Founder/CTO, Solutions Architect, etc.) are interspersed with
genuine matches at the same `div.job-card-container[data-job-id]` selector, so don't
assume every enumerated card is on-topic — screen titles before opening each one.
Broader queries (e.g. "UX Designer") surface meaningfully more relevant cards than
narrow ones (e.g. "Product Designer" alone returned almost no design-relevant results
in the same location/window) — run 2-3 title variants per session, not just one.
`f_WT=2` (remote) was NOT used this run (plain `location=London...` was enough to
surface Hybrid/Onsite London + some remote); revisit `f_WT` filters if London-only
search under-yields.

## Search URL
```
https://www.linkedin.com/jobs/search/?keywords=<role>&location=<loc>&f_TPR=r604800&f_WT=2&sortBy=DD
```
`f_TPR=r604800` = past 7 days · `f_WT=2` = remote (1=on-site, 3=hybrid) · `sortBy=DD`
= most recent · add `&f_E=2,3` for entry/associate level.

## Enumerating results: use `scripts/feed.py` (built 2026-07-13) — do NOT hand-type the JS anymore
`sites/linkedin/scripts/feed.py --nav "<search url>"` navigates, scrolls the
virtualised results pane, enumerates every `div.job-card-container[data-job-id]` /
`li[data-occludable-job-id]` card, and — critically — **dedups against the FULL
`application-tracker.csv` in code** before returning anything, mirroring the fix
already shipped for WTTJ and Indeed. Before this script existed, every LinkedIn
sourcing pass was an ad-hoc JS snippet typed into `cfx.sh eval`, with the calling
agent manually eyeballing the card list against the tracker each time — expensive
in tokens and exactly the failure class (missed/incomplete manual dedup) that
caused a real duplicate application on Indeed (see indeed.com/NOTES.md). Use:
```bash
python3 sites/linkedin/scripts/feed.py --nav "https://www.linkedin.com/jobs/search/?keywords=UX%20Designer&location=London%2C%20England%2C%20United%20Kingdom&f_TPR=r604800&sortBy=DD"
python3 sites/linkedin/scripts/feed.py hide <id>     # after Applied/Skipped, per SKILL.md's absolute dismiss rule
```
`--all` opts back into the unfiltered list; `--scrolls N` controls how many times it
scrolls before reading (default 4 — increase if a search returns mostly blank
title/company entries, meaning cards below the fold haven't rendered their text yet).
Empty result (exit 1) = genuinely exhausted for that query — mark it with
`sites/_common/scripts/board-cooldown.sh mark linkedin "<query>"` rather than
re-running the same search. **Still screen titles yourself** — dedup only removes
already-known ids, it does not filter LinkedIn's interleaved off-profile
promoted cards (Senior Marketing Manager, Solutions Architect, Co-Founder/CTO…).

## ✅ RESOLVED (2026-07-13): "Apply on company website" was never a dead click
**Corrects a wrong prior conclusion here** ("confirmed 5x... genuine LinkedIn/company-side
no-op" — wrong, do not resurrect it). The button genuinely opens a real **"Share your
profile?"** consent dialog before handing off to the destination ATS — our own
camofox-browser was silently auto-closing it (via an overly generic cookie-dialog
dismiss pattern) inside the same click request that opened it, before any snapshot could
ever see it. Full root cause + fix in `CAPABILITY-GAPS.md`'s matching entry. **Just use
`python3 cfx.py click-follow <ref>`** — it now clicks through this modal automatically.
**Retry any posting currently logged `Blocked` for this reason — not actually stuck.**
On `unhandled_dialog` (a dialog appeared with no safe "Continue" control found): read
`dialog_text`, snapshot the tab, handle it manually — don't treat it as a dead end.

## Applying
- **Easy Apply** (in-LinkedIn) — a multi-step modal (contact → resume → questions →
  review → submit). **Drive it with `sites/linkedin/scripts/easyapply.py`, NOT
  `atsform.py`** — the whole modal lives in a shadow DOM that atsform's main-document
  selectors can't see (see the shadow-DOM section below).
- **"Apply" (external)** — redirects to the company ATS (Greenhouse/Lever/Workday/
  Ashby/…); follow it and use that ATS's recipe. Same external-ATS rules as always.
- **DOM note: LinkedIn's Easy Apply modal is NOT `.jobs-easy-apply-modal`** in the
  current UI — that classname (and `.artdeco-modal`) matched nothing via `eval`
  querySelector even while the modal was visibly open on screen (confirmed via
  screenshot). The modal/button DOM uses hashed CSS-module classnames (e.g.
  `_3bc34f41 _5390511b ...`) that change per deploy — **don't hardcode a modal
  classname selector.** The real reason `eval` querySelector saw nothing: the modal is
  in a **shadow root** (below), so `document.querySelector*` can't reach it at all.
- The page's "Easy Apply" trigger is a **`link`** (`aria-label="Easy Apply to this job"`),
  NOT a `<button>` — a `button`-only querySelector misses it. `easyapply.py open` handles
  both. This trigger lives in the MAIN document (only the opened modal is in the shadow root).

### ✅ SOLVED: "Save this application?" dialog "stuck-loop" — it was a shadow-DOM problem
Earlier this job (FE fundinfo 4430943239) was logged as an unrecoverable "instant skip":
clicking Easy Apply opened the `Apply to FE fundinfo` modal (Contact info, fields
pre-filled) with an `alertdialog "Save this application?"` (Dismiss/Discard/Save) stacked
on top, and ref-clicks / xy-clicks on Dismiss/Save did nothing (byte-identical
screenshots). **Root-caused and fixed 2026-07-13 — the application was then submitted
successfully through this exact flow.**

**Root cause:** the Easy Apply modal AND its "Save this application?" dialog render inside
the **shadow DOM of a `div.theme--light` host**, not in the main document. Confirm with
`eval`: `document.querySelector('[role=dialog]')` → null and the phrase "Save this
application" is NOT in `document.body.innerText`, yet both are visibly on screen. The
buttons live at `host.shadowRoot`, so:
  * camofox **`click <a11y-ref>`** and **`click-xy <x> <y>` don't reliably resolve into the
    shadow top-layer** → the click lands nowhere, screenshot unchanged. THIS is why it
    looked like an unrecoverable loop. (Playwright's *CSS-selector* engine DOES pierce open
    shadow roots — so `/upload` and selector `/type` reach shadow inputs — but a11y-ref and
    coordinate clicks do not.)
  * A **JS `.click()` executed inside the shadow root works** (JS pierces open shadow DOM
    natively). That is the fix, and it's what every `easyapply.py` primitive does.

**Why the save-dialog appears at all:** it's the modal's *close/blur confirmation*. It pops
when focus leaves the shadow-modal or the backdrop gets a gesture — which the OLD
coordinate/ref clicks did (they landed outside the shadow layer), so the dialog kept
re-appearing → the "loop". Driving purely via in-shadow JS never blurs the modal, so it
does not recur. **A focus-stealing camofox `/type` (selector-based, real keyboard) ALSO
triggers it** — so fill via in-shadow JS value-set (`easyapply.py fill`), not `/type`, while
inside the modal.

### Easy Apply recipe (use `sites/linkedin/scripts/easyapply.py`)
```
python3 sites/linkedin/scripts/easyapply.py open          # click the Easy Apply link
python3 .../easyapply.py dismiss-save                      # clear the save-confirm if present
python3 .../easyapply.py state                            # {header, step, progress, nav, errors, labels}
python3 .../easyapply.py fill  "<label>" "<value>"        # in-shadow value-set (no focus steal)
python3 .../easyapply.py select "<label>" "<option>"      # native <select> in shadow
python3 .../easyapply.py radio "<question>" "<option>"
python3 .../easyapply.py check "<label>" [on|off]         # checkboxes / consent / "select all that apply"
python3 .../easyapply.py upload "<file-in-uploads>"       # path resolves to /uploads/<name> (container mount!)
python3 .../easyapply.py next                             # auto: Submit>Review>Continue
python3 .../easyapply.py submit                           # clicks Submit, verifies "application sent"
```
**`next` refuses to advance past unanswered required fields** (2026-07-13: a real run
advanced past an "Additional Questions" step — salary/right-to-work/notice/demographics —
without answering any of it, which looked like "the bot dismissed the questions." `next`
now scans the current step for required text/select/radio fields still empty and returns
`BLOCKED_UNANSWERED_REQUIRED: <label> | <label>...` with exit 3 instead of clicking
through. Fill each listed field, then call `next` again; `--force` overrides if you've
confirmed by hand a flagged field isn't really required. Doesn't check checkboxes — a
required consent checkbox and an optional "Follow company" one aren't reliably
distinguishable, so answer those from `state`'s `labels` yourself before advancing.)

**All field lookups (`fill`/`select`/`radio`/`check`/`next`/`submit`) are scoped to the
correct dialog, not the whole shared shadow root** — the shadow host can contain more
than one `[role=dialog]` at once (e.g. a messaging chat popup alongside the real Easy
Apply form); searching the whole root risked silently matching the wrong widget.

Loop per step: `state` → answer fields from `references/applicant-profile.md` → `dismiss-save`
→ `next` → `state` (check `errors` is `[]` before advancing). Steps seen on FE fundinfo:
Contact info (0%, Location is required + empty even though other fields pre-fill) → Resume
(33%, upload tailored PDF + salary/screener) → Additional Questions (67%, native-`<select>`
+ "select all" checkboxes + right-to-work radio + consent checkbox) → Review (100%) →
Submit. Uncheck the "Follow <company>" box on Review before submitting.
- **Always double-check screener answers BEFORE the Additional Questions step, not after
  — a slow-to-fix answer can get submitted out from under you.** Confirmed live
  2026-07-13 (Baller League posting): the user was also watching/driving the same
  camofox session via VNC and clicked Submit themselves partway through a correction —
  the bot's own `submit` call landed a beat later, found the button already gone, and
  reported `FAIL: no submit button`, which read as "not submitted, safe to keep
  editing" when the application had actually already gone out. **Fixed:** `cmd_submit`
  now checks the page for "application sent"/"submitted" text before reporting FAIL, so
  a genuinely-already-submitted state reports SUCCESS instead of a misleading failure.
  Still always cross-check against the site's own Applied/tracker list before logging
  `Applied` in `application-tracker.csv` — don't trust either the bot's or the
  screenshot's confirmation text alone when a human may be driving the same tab.
- **Numeric "years of experience with <named tool>" screener questions are a real hard-
  stop candidate if the tool isn't in `references/applicant-profile.md`** — don't
  default to "0" just because it's the safe-looking truthful answer; that can
  understate genuine daily-use experience the applicant profile simply hasn't caught
  up with yet (happened with a "years with Claude Code" question — profile only had
  "GenAI/prompt engineering" documented generically, not that specific tool by name).
  If there's any doubt and the user is reachable, ask before filling a numeric
  experience field for a named tool that isn't explicitly in the profile.
- **Upload path gotcha:** camofox's `/upload` rejects any path not under `/uploads`
  (`HTTP 400 path must resolve inside /uploads`). The skill's `uploads/` dir is mounted
  there — copy the tailored PDF into `uploads/` and pass just its basename; `easyapply.py
  upload` rewrites it to `/uploads/<basename>`. After upload, LinkedIn moves the file out
  of the `<input>` into a selected resume "card", so `input.files[0]` reads empty — verify
  by the card's filename text, not the input (the script does this).
- The `Save this application?` `dismiss-save` action clicks the dialog's own **Dismiss (✕)**
  (returns to the form). Save/Discard both CLOSE the modal — don't use them to progress.

## LinkedIn → Adzuna / ApplyIQ external-apply hop
Several postings (e.g. Solirius Reply User Researcher `4438932407`) route Apply →
`linkedin.com/safety/go/?url=...adzuna.co.uk...` → Adzuna's own ApplyIQ flow, not a
direct destination-ATS handoff. **Full recipe (login, reCAPTCHA, cookie banner,
confirmation) is in `sites/adzuna.co.uk/NOTES.md`** — read that once you land on
Adzuna, don't re-derive it here.
