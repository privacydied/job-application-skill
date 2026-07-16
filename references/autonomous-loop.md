# Autonomous Application Loop — full per-posting mechanics

Extracted from SKILL.md (perf-roadmap E.3) to keep the always-loaded core slim. SKILL.md
keeps the loop skeleton + every ⛔ guardrail; this file is the detailed step-by-step the
model loads when actually applying. The batch/turn-economy playbook is `fast-loop.md`.

## Cheap pre-filter BEFORE opening anything

Pipe the whole feed list through `python3 sites/_common/scripts/precheck.py -` (file arg
also accepted) — per candidate, in code: title eligibility against the FULL
`references/target-roles.md` tier list, the location hard screen, tracker dedup
(canonical-id + Company+Role), and a salary-cache attach → `keep`/`review`/`drop`
verdicts with tracker-ready reasons. **A code call, not a memory judgment** — prose
recall of the tier list silently drops on-profile Tier B/C titles across dozens of cards
(`check_title.py` remains for a one-off title; LinkedIn's `feed.py` attaches `eligibility`
and precheck reuses it). `drop` → don't open "to be sure"; `review` → the JD's own
location line decides.

- **Re-mine after the first pass:** precheck's title-metadata filter over-drops genuinely
  on-profile *direct-employer* roles (card metadata has an empty company field; agency
  names only appear on the JD page). Re-scan the raw candidate set with the
  KEEP/AGENCY/SENIOR/BADENG regexes in `references/sourcing-screening-pitfalls.md`, then
  verify each survivor is LIVE (agencies recycle *expression-of-interest* ads: "does not
  represent a live vacancy") and actually London/remote (JD location, not card city).
- **Multiple sourcing passes?** Merge BEFORE precheck: `python3
  sites/_common/scripts/merge_sources.py <f1.json> <f2.json> … [--drop-tracked] [-o
  merged.json]` — flattens list- or `{board:[…]}`-shaped feed files, unions by canonical
  id (`?trk=` variants collapse), `--drop-tracked` removes rows the tracker already has.

**Then screen ALL survivors in ONE call:** `python3 sites/_common/scripts/jd.py
--nav-batch survivors.txt` (URLs one per line, or `-` on stdin) — navigates + extracts
every survivor sequentially (human pacing preserved), returns a JSON **array** of the
per-posting payloads step 1 describes; memoized in `.jd-cache/` (24h TTL) so
partial/retried batches reuse loads. Per-posting `jd.py --nav <url>` remains correct for a
single posting or to park the tab on the page.

## For each candidate posting — steps 0–10

0. **Dedup** — check `application-tracker.csv`. URL or Company+Role present with any
   status other than `Skipped`/`Blocked` → skip silently. Never apply twice. (`Blocked`
   MAY be retried once the blocker clears.)
1. **Screen** — from the `jd.py --nav <url>` payload (title/company, JD text,
   requirements, salary mentions, location signals, apply-funnel signature, hidden-text
   trap scan, title-eligibility verdict). Do **NOT** `snap` a JD page (biggest token
   payload in a turn) and do NOT revisit the JD for step 2. Log `Skipped` if: role clearly
   off-profile, requires citizenship/clearance he lacks, unacceptable location (rule
   below), staffing-agency repost, or listed salary blatantly below the cached median in
   `salary-cache.csv` (no cache entry → don't skip on salary).
   - **Platform-gated funnel (fast skip):** some "Apply" buttons route to a third-party
     funnel — an AI-recruiter chat, hiring-platform sign-up, or "download our app" wall.
     Signature: **no `<form>` with real fields** (no CV upload, no name/email, no Submit),
     only signup CTAs; `jd.py` flags it `funnel_suspect` (`total_fields: 0`). Real
     application fields = a real ATS you MUST complete; signup/app-wall only = log
     `Skipped` "platform funnel — no web application form", dismiss it (step 10), note it
     for the user, CONTINUE. Never `Blocked` (nothing to retry), never a hard stop.
     Related: a LinkedIn "Apply on company website" can cross-post to a different LinkedIn
     listing of the SAME role — dedup catches it.
2. **Extract** — the 3–5 must-haves, hiring manager if visible, exact JD phrasing — all
   already in step 1's payload (`requirements` + `jd_text`); same turn, no second visit.
3. **Tailor** — tailored resume (Step 2) + cover letter (Step 3) for THIS posting, both
   referencing the actual company/product. **⚡ Batch across the whole work list with
   `tailor.py`:** ONE spec JSON (per posting: `dir`, `company`, `family`, `subs`
   find/replace against the master, `drop` bullets, `cover` text) → `python3
   sites/_common/scripts/tailor.py apply <spec.json> --render`. **⚡ Set `family`**
   (pipeline sets it per queue row; else `family_of` the title) so tailor swaps the summary
   to that family's positioning FIRST — then `subs` is just a few company-specific tweaks,
   not a re-emit. The 11 family bases live in `applications/_bases/<family>/` (regenerate
   with `tailor.py build-bases` after editing `sites/_common/family-bases.json`); each
   ships a cover slot-template. **Company hook:** `python3
   sites/_common/scripts/company_cache.py get "<Company>"` first — reuse the cached
   one-line fact instead of re-researching; `company_cache.py put "<Company>" "<hook>"`
   after you find one. A real tailoring is ~a dozen small verbatim subs, NOT a re-emit of
   the whole blob (also sidesteps the line-based-patch trap; pin exact text with `tailor.py
   find "<snippet>"`). It writes cover letters, runs the placeholder/company-mention/
   wrong-company checks, and renders every PDF in one parallel pass. Spec shape:
   `references/fast-loop.md`. The placeholder check (`\[[A-Za-z][^\]]*\]`) is enforced by
   `tailor.py`; still check screener text you write later — a match is a hard failure
   (resume-file markdown links/HTML attrs don't count).
4. **Produce the upload PDF** — most ATS forms require one. Exception: WTTJ's "Apply with
   your profile" uses no upload (`sites/welcometothejungle/NOTES.md`). Clone → tailor →
   `sites/_common/scripts/make-pdf.sh applications/<company>-<role>` (serves the HTML on
   the host LAN IP, renders via the Playwright container, fails loudly if `pdftotext`
   extracts no text). `tailor.py --render` already did this for the whole list; standalone
   batch: `prerender-pdfs.sh <dirs…>` (opt-in `PRERENDER_SINGLE_CONN=1` renders all over
   one Playwright connection). Paste-into-textbox fields get the plain-text version.
   - **Upload** once the file input's ref is known: `sites/_common/scripts/upload-file.sh
     <ref> applications/<company>-<role>/resume.pdf` (stages into `uploads/`, POSTs, cleans
     up). Confirming the attach took: `CAPABILITY-GAPS.md`.
   - **Workday / Greenhouse upload gotchas** (click-drift, resume date-revert, silent
     submit wall, visually-hidden file input) → `references/apply-mechanics.md §Upload
     gotchas`, which points to the per-ATS references. Workday resume upload can be
     unbindable → log `Blocked`, don't submit corrupted dates to a regulated employer.
5. **Fill the form** — click Apply / Easy Apply, then **batch-fill in ONE call**: assemble
   `applications/<company-role>/apply.json` from the applicant facts + JD (`upload` the PDF,
   `fill` text incl. cover letter via `"@path"`, `select`/`radios`/`checkboxes`, `review`
   with the company name), **starting with `"defaults": true`** — auto-merges
   `sites/_common/apply-defaults.json` (name/email/phone/links/opt-out radios; optional
   semantics: no matching field → silent skip; your explicit keys win) — then `python3
   sites/_common/scripts/atsform.py apply <config>`. It prints a consolidated pass/fail
   summary; use primitives only for discovery or stragglers.
   - **Ashby** → `sites/ashbyhq/scripts/ashby.py apply` (own keys — `cv`/`files`/`toggles`).
     ⚠️ Its toggle `check` lies (reads the hidden checkbox, not the button) — before submit,
     click every required toggle's backing `input[type=checkbox]` if unchecked and trust
     `submit`'s "Missing entry" over `set-toggle`'s OK. Full recipe:
     `references/apply-mechanics.md` + `references/ashby-toggle-check-gotcha.md`.
   - **LinkedIn Easy Apply is NOT atsform** — shadow-DOM modal; drive with
     `sites/linkedin/scripts/easyapply.py` (`sites/linkedin/NOTES.md`). **⚡ Prefer the
     end-to-end driver `python3 sites/linkedin/scripts/apply_ea.py <job_id|url> "<Company>"
     "<Role>" [--resume /uploads/<f>.pdf] [--dry-run]`**: navs, opens, auto-answers
     screeners (consults the shared `screener.py` bank), re-uploads the resume, submits,
     confirms (incl. LinkedIn's auto-advance "sent" state), writes proof, logs `Applied
     --proof`, and records the outcome to apply-stats. Self-heals a dead tab; bails
     `NEEDS_HUMAN` (exit 7) on an unanswerable required screener; `--dry-run` walks to
     Review without submitting. Exits: 0 submitted · 7 needs-human · 9 no-tab · 3 failed ·
     5 dry-run-OK. **Deep per-ATS gotchas (batch EA, resume persistence, shadow radios,
     Ashby toggles) + the fixed auto-advance/bail notes: `references/apply-mechanics.md`.**
   - **Apply redirects to an external ATS → follow it and complete it there** — that's the
     core job, never a skip reason. WTTJ: prefer "Apply with your profile"; else take the
     external link. **New, un-automated ATS?** Drive it like any labelled web form (`apply`
     config works) and create `sites/<ats-domain>/NOTES.md` per the continuous-learning
     protocol. Free-text screeners: fresh 2–4 sentence answers grounded in the resume, same
     tailoring rules as the cover letter.
   - **⚡ Gating screeners (right-to-work / sponsorship / notice / relocation / years-of-X /
     demographics) come from the shared answer bank:** `python3
     sites/_common/scripts/screener.py ask "<question>"` returns the canonical answer + kind
     (radio/select/number/text) — seeded from the profile and shared across every ATS
     (apply_ea consults it automatically). A genuine miss prints `NEEDS_ANSWER`: answer it
     truthfully from `references/applicant-profile.md`, then `screener.py learn "<pattern>"
     "<answer>" <kind>` so it's free forever after.
6. **Review before submit** — the a11y text snapshot and `cfx.sh eval` are **BLIND to
   visual-only widget state** (reCAPTCHA checkbox state, whether a radio is actually
   selected, cookie banners covering the form). Before clicking Submit on ANY form: `cfx.sh
   shot <file>` and vision-check (a) no unchecked CAPTCHA, (b) the email reads
   you@example.com, (c) every radio/checkbox selected as intended, (d) no banner covering a
   control. **⚡ Region crop for the vision gate:** `python3 sites/_common/scripts/cfx.py
   shot <file> --selector "<css of the submit/email/consent area>"` (or `--clip x,y,w,h`)
   captures just that region — far fewer vision tokens and fewer misses than a full page.
   - **⛔ HARD EMAIL-IDENTITY GATE:** the pre-submit screenshot MUST show `you@example.com`
     — never a Google-OAuth address (`you@example.com`) or any other account. Adzuna's
     ApplyIQ validates the email against the logged-in account and refuses edits — if the
     screenshot shows a non-jane email, STOP: log out and re-authenticate with the
     email/password account (see the SSO override in Hard stops) BEFORE submitting.
   - **Solve reCAPTCHA v2 (AUTO, happy path, no halt):** unsolved checkbox → `recaptcha.py
     click <job_ref>` → `PASSED` or `CHALLENGE`; `CHALLENGE` → `solve-grid`, read the crop
     with vision, `solve-grid --tiles "<idx>"`. Invisible badge → trigger the real Submit,
     then `wait-token`. Verify the GREEN CHECKMARK via screenshot before Submit — the JS
     token alone is unreliable. (Turnstile/hCaptcha remain the full-halt case; CSJ's ALTCHA
     is the other sanctioned auto-solve.)
7. **Submit, then CAPTURE PROOF (hard rule).** Save the confirmation ("application sent"
   modal / thanks page) as a real artifact in the posting's folder:
   `applications/<company>-<role>/confirmation.png` or `confirmation.txt`. **No
   confirmation captured ⇒ NOT `Applied`** — filled-but-unconfirmed = `Applied?`; no
   evidence at all = `Unverified`.
8. **Log via `python3 sites/_common/scripts/log-application.py "<Company>" "<Role>"
   "<Source>" "<url>" Applied --proof applications/<slug>/confirmation.png [--next …]
   [--notes …]`** — **`--proof` is MANDATORY for `Applied`** (the logger exits 2 without an
   existing, non-empty confirmation file and records `proof=` in Notes). No proof → log
   `Applied?` or `Unverified` (no `--proof` needed). The logger updates any existing row in
   place (canonical URL id, then Company+Role) and only appends when none exists — **never
   hand-append (`echo >>`)**; duplicate rows poison feed/precheck dedup. It refuses
   session-bound `SID=` URLs and keeps the existing URL's dedup key when a posting moved
   board→ATS (new URL goes in Notes). Save tailored files as `applications/<company>-<role>/`
   (lowercase, alphanumerics + dashes).
9. **Close the posting's tab the moment it's resolved** (Applied/Skipped/Blocked): `cfx.sh
   close-tab` (also close any solved-CAPTCHA popup tab with `close-tab <tabId>`). Camofox
   keeps every tab in memory and open-tab starts failing around ~8 tabs, silently stranding
   the run. Closing is safe — sessions live in the profile, not the tab. Open a fresh tab
   for the next posting. (Hermes path: reuses one tab, nothing to do; `camofox_close`
   closes the whole session — end-of-run only.)
10. **⛔ Dismiss/hide the posting on the source site the moment it reaches a TERMINAL state
    (`Applied` or `Skipped`).** Use the board's own "Dismiss" / "Not interested" / "Hide
    job" control, for every terminal posting, before moving on — same weight as the tracker
    row. A future *sourcing* pass reads the board, not the tracker, so the tracker is not a
    substitute.
    - **`Blocked` is the ONE exception — never dismiss it** (retryable by definition;
      hiding makes it un-refindable). Dismiss only once it later resolves to
      `Applied`/`Skipped`.
    - No dismiss control on the detail page → go back to the search-results/feed view where
      the card-level control lives.
    - LinkedIn virtualization: the Dismiss control only exists on the results card, and
      results are virtualized/personalized — `feed.py hide <id>` may return
      `CARD_NOT_FOUND`. The posting is already logged (dedup protects); proceed, note that
      the on-site dismiss couldn't complete, and don't loop re-navigating hunting for an
      unrendered card.
    - **⚡ Batch the dismissals per board:** collect the run's terminal LinkedIn ids and
      `python3 sites/linkedin/scripts/feed.py hide-batch <id1,id2,…> [--nav <results url>]`
      — ONE results-page visit dismisses them all (a `CARD_NOT_FOUND` for an un-rendered
      card is a benign no-op; tracker-dedup still prevents re-application). Beats one nav
      per posting.
