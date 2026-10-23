# *.myworkdayjobs.com — site notes

**Form-fill:** on an application step, use the shared engine `../_common/scripts/atsform.py`
(fill/select/radio/checkbox/upload/review by label). Workday is **multi-step** (My
Information → Experience → Questions → Review), needs an **account** (NOT a hard stop —
create with `you@example.com` + a generated password, record in `ats-credentials.csv`), is
**PDF-required** (upload a tailored resume or use "Autofill with Resume"), and has the
Apply-button click-drift below. Advance with "Save and Continue"/"Next".

A common **external ATS** landing spot from a board's "apply on company website" redirect.
Every instance lives at `<company>.wd<N>.myworkdayjobs.com`; the behavior below is generic.

## Apply button click-drift → navigate to its href (verified fix)
Clicking the job page's "Apply" — a11y ref, CSS selector, or JS `.click()` — never
navigates (`location.href` stays put). Root cause: it's an **`<a role="button" href="...">`**
(so `querySelectorAll('button')` misses it — always include `[role=button]`/`a[role=button]`)
and its SPA router listener doesn't fire in the automated context. **Fix: read the anchor's
`href` and `navigate` to it directly** (100% reliable) — `scripts/nav_to_link.py "Apply"`
does this (locate → read href → navigate → confirm). The landing page shows **"Start Your
Application"** with **Autofill with Resume / Apply Manually / Use My Last Application** —
prefer Autofill (upload PDF, let Workday parse, correct misparses). Still stuck after ~10
min → log `Blocked` (not Skipped) with the direct job URL in Notes; move on (time cap).
- camofox `/click` `coordinates` is NOT a standalone coordinate-click — the server requires
  `ref`/`selector` (`{"error":"ref or selector required"}` otherwise). Don't try bbox clicks.

## Cookie banner
Standard "Decline"/"Accept Cookies" on first load — accept early (an un-dismissed banner
can misdirect clicks), though it wasn't the Apply-click cause.

## Sign-in vs guest apply
Applying doesn't strictly require an account, but "Start Your Application" may offer/require
creating one. ATS account creation is pre-approved (email + generated password →
`ats-credentials.csv`) UNLESS signup demands more than name/email/password (e.g. SMS code) —
that IS a hard stop.

## My Experience (multi-entry) — do NOT batch ref-based `type()` across a re-render
Each entry's Month/Year date fields are a custom widget (id like
`workExperience-<N>--startDate-dateSectionMonth-input`) that **re-renders on every
interaction**, so refs captured from an earlier snapshot silently resolve to the wrong
element (confirmed: sequential ref-`type()` across ~20 date fields corrupted months to the
last-typed value, and leaked stray fragments into textareas). **Per entry:**
1. Get live IDs directly: `document.getElementById('workExperience-<N>--jobTitle')` etc.
   (IDs are stable within a field, unlike a11y refs across the page).
2. Set every field for that ONE entry in a SINGLE `evaluate` call (fresh `getElementById`
   per field, one atomic JS block) so no inter-call re-render invalidates a later target.
3. Native property setter + dispatch `input`, `change`, AND `blur` (Workday validation needs
   `blur` to clear "field required" on retry).
4. Re-verify via a fresh separate `getElementById` read — don't trust the setter's return or
   the a11y snapshot text.

## ⛔ Review step can silently revert a resume-autofilled entry's dates — real data loss
Symptom: after fixing all work-history entries (verified via `getElementById` before every
Save) and reaching Review with ZERO validation errors, one **resume-parsed** entry's From/To
dates revert to `12/<year>` (manually-added "Add Another" entries stay correct). Confirmed
real (survives a hard reload AND a fresh sign-in — the saved profile itself is wrong), not a
display artifact. Theory: the Review summary re-derives resume-autofilled entries from a
cached parse, not the live field.
**⛔ Do NOT click Submit when this happens** — the Review page is the real payload, so you'd
send wrong employment dates to a regulated employer doing background checks. Log `Blocked`,
report the specific field. **Four fixes all failed** (JS setter ±blur; atomic+blur; real
`type()` isolated fresh ref; delete+re-add entry then retry) — even a freshly re-added entry
reverts to "12" before any save, so it's a genuine widget/validation quirk, NOT camofox-
fixable — don't retry these. Untested idea if revisited: drive the `button "Calendar"` date
picker instead of typing. Else finish via noVNC (`http://nasirjones:6080/vnc.html`, sign in
`you@example.com`) — only that one field needs manual correction before Submit.

## "Save and Continue" no-ops → a required field whose error renders INLINE, not in a banner
Symptom: "Save and Continue" seems dead — URL/title unchanged, and `[role=alert]`/`.error`/
`[aria-invalid=true]`/`[data-automation-id=errorMessage]` all empty. **It's neither a dead
button nor an SPA blocker** — required fields are empty and Workday renders each field's
error INLINE in its own widget text (`Error: The field <label> is required…`), not in a
banner. Detection when a step won't advance:
```js
[...document.querySelectorAll("[data-automation-id^=formField-]")]
  .filter(f => /Error:/.test(f.innerText))
  .map(f => f.getAttribute("data-automation-id"))   // also check [data-automation-id=inputAlert]
```
**Two easily-missed required My Information fields:**
1. **`formField-source` — "How Did You Hear About Us?"** — required *multiselect*: click its
   `input[placeholder="Search"]`, trusted-click the `[data-automation-id=promptOption]` you
   want (Civil Service Jobs / Direct Source / Referral / Social Media / … — the true board).
   Shows "0 items selected" until picked.
2. **`formField-candidateIsPreviousWorker` — "Have you previously worked for <Company>?"** —
   required Yes/No radio whose labels are NOT in the input's own text — select by VALUE:
   `input[type=radio][value=false]` = No, `value=true` = Yes.

**⚠️ Workday submit/nav buttons no-op on synthetic `.click()`** — `pageFooterNextButton`
(Save and Continue) and `signInSubmitButton` ignore a scripted click; use a **trusted**
`/click` with a selector (or `cfx.click_and_follow`), e.g.
`selector:"button[data-automation-id=pageFooterNextButton]"`. (The button fired fine; the
step correctly refused to advance past the empty required fields whose inline errors were
invisible to the checked selectors.)

**⛔ Honeypot:** the sign-in / account-create form carries a hidden
`data-automation-id="beecatcher"` ("… for robots only, please leave blank") field — NEVER
fill it.

**Automated in `atsform.py` (so you don't hand-drive these):** `select()` has a Workday
multiselect branch (formField-by-label → trusted-click Search → pick promptOption),
`set_radio(q,"Yes"/"No")` maps to `value=true/false` for the label-less radios, and
`click_button("Save and Continue")` retries with a trusted `/click` when the synthetic click
no-ops. So `atsform.py apply <config>` drives My Information — just include `select`/`radio`
entries for "How Did You Hear About Us?" and "Have you previously worked for …?".

## ⛔ "Create Account" step stalls silently, twice live (2026-09-27, Jupiter Asset Management + Condé Nast)

On two unrelated Workday tenants today, the guest-apply flow's step 1 "Create Account" form
(email + password + verify password) filled correctly (verified via read-back), and clicking
the `button[data-automation-id=createAccountSubmitButton]` (also tried via generic text-match
click) produced NO visible change — no error message, no navigation, no progress indicator —
even after a 6s wait. A honeypot field ("Enter website. This input is for robots only, do not
enter if you're human.") is present on the same page but was never touched, so it is unlikely
to be the direct cause, though its mere presence suggests active bot-detection on this step.

**Not yet root-caused.** Two live sightings, no working fix found this session. Candidates for
a future investigation: (1) the click may need to be a genuine trusted click via the `/click`
endpoint with `ref`/`selector` rather than a synthetic `.click()` — same class of issue
documented elsewhere in this file for Workday's Next/Sign-in buttons (see "synthetic .click()
no-ops on Workday" notes); (2) Workday's bot-detection may be silently rejecting the whole
session before this point; (3) the honeypot field may need to be explicitly left with its
default (empty) value in a specific way rather than simply untouched.

**Workaround for now:** if `Autofill with Resume` -> `Create Account` stalls with no error
after ~10s and a retry, log `Blocked` (not a 3rd attempt) rather than sink further time — this
matches the existing "Still stuck after ~10 min -> log Blocked" guidance for Workday generally,
just found earlier in the flow (step 1 of 7) than previously documented cases.

## ✅ FIXED (2026-09-28, Entrust Junior Product Designer, R004374): candidate (1) above was correct — use a trusted `cfx.click_selector`, not a raw `.click()`
Confirmed on a third live tenant: filling the Create Account form exactly as before (email,
password, verify-password, honeypot left untouched, terms checkbox ticked) then calling
`cfx.click_selector('button[data-automation-id=createAccountSubmitButton]')` — the SAME
trusted-click mechanism already documented above for `pageFooterNextButton`/
`signInSubmitButton` — advanced the flow immediately and correctly to the next step
(`Autofill with Resume` page). A generic JS `.click()` or ref-based click had been the
previous (failing) approach on this exact button in the two 2026-07-27 sightings. **This
button belongs in the same "no-ops on synthetic .click(), needs a trusted /click with
selector" family as the other Workday nav buttons — treat `createAccountSubmitButton`
identically to `pageFooterNextButton` from now on, not as a separate mystery.** If it still
silently stalls after using `click_selector` specifically, then escalate to `Blocked` per
the workaround above; don't burn time on a raw `.click()` first.

## Etsy/Depop Workday (2026-10-05, Product Designer 12-month FTC) — verified submit, hard lessons
- **Only entries typed in the CURRENT page visit survive Save and Continue.** Autofill-parsed Work Experience
  entries (and any entry edited only via native setter) were silently dropped on save/back-forward; the
  draft also accumulated 12 duplicate entries. Reliable recipe: Apply Manually, delete all entries, then add
  every entry in ONE visit and save once.
- Native-setter does NOT commit `<textarea>` (Role Description, questionnaire answers) or date inputs. Focus the
  element with JS (`el.focus()`), press Backspace once, then `cfx.press` each character. Month "01" needs
  `0` then `1`. A half-typed date shows "Invalid Date" and makes every later trusted click time out.
- Add Another: use JS `.click()` after `scrollIntoView`; trusted click can time out. Next/Submit: trusted
  `click_selector` works when no invalid date is on the page.
- If every click on every tab times out (`cfx.py check-engine` says click endpoint broken) restart the
  container: `cd /volume1/docker/playwright && sudo -n docker compose restart camofox-browser`
  (`cfx.py restart-engine` only runs `docker start` and does nothing on a running container).
- Submit lands on Candidate Home (`/jobTasks/completed/application`); proof = "Interest in <Company>!" email
  from the tenant's `@myworkday.com` plus the My Applications row.
- Depop is reached from a Totaljobs listing via "Apply on company website" -> etsy.wd5 Depop_Careers.

## Global Media Group (thisisglobal.wd3) Create Account + Application Questions (2026-10-05) - verified submit
- Create Account stalled with native-setter fill + trusted click. What worked: type email/password/verify with
  `/type` `mode:keyboard` (real keystrokes), then `cfx.sh click-xy <x> <y>` on the button centre. The call returned
  HTTP 500 but the page had advanced to My Information. A `click_filter` div overlays `createAccountSubmitButton`.
  Check the page, do not trust the error.
- Workday dropdown buttons (`button[aria-haspopup=listbox]`): open with `cfx.sh click <ref>` from `snap`, then tag
  the `li[role=option]` with an id via eval and `cfx.click_selector('#id')`. The click may time out but still commit.
- Multiselect (Race/Ethnicity): click the input, type the word, press Enter to filter, then click the option.
- My Experience can be skipped when Work Experience is not starred: CV upload only (`/upload` `path` = bare file in uploads/).
- Social Network LinkedIn rejects a normal profile URL ("Invalid LinkedIn URL"); leave it empty.

## Accenture (accenture.wd103) sign-in works now; Workday dropdown recipes (2026-10-05) - verified submit
- The old "email verification never arrived" wall is gone: Apply Manually -> Sign In With Email using the csv row signed
  straight in. Re-try the earlier Accenture Blocked rows with that account.
- "How Did You Hear About Us?" is a hierarchical multiselect. Typing a name in its search box and pressing Enter
  filters to a match ("Indeed" works). The list has no Adzuna; pressing Enter on a no-match search selects the FIRST item
  of the open sub-list, so never press Enter on a search with "No matches found".
- Work Experience is required here: type Job Title / Company / month / year with `/type` `mode:keyboard`
  (ids `workExperience-<N>--jobTitle`, `--startDate-dateSectionMonth-input`, ...; N is not 1). Save advanced fine.
- Dropdown buttons: `cfx.sh click <ref>` from a fresh snap, retry once if the option list is empty, then tag the
  `li[role=option]` with an id and `cfx.click_selector`. Checkbox with hidden input: scrollIntoView then JS `.click()`.
