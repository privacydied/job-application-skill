# SAP SuccessFactors (career5.successfactors.eu / career55.sapsf.eu) — verified quirks

## ⛔ `atsform.combobox_pick`'s freetext fallback can silently commit the WRONG option on
this widget (2026-08-23, Capgemini Service Designer req 397090) — verified live.

The SF picklist (`input#<n>:_input` + `button#<n>:_selectButton`) has field ids containing
colons, so the REST `/type` endpoint 500s on it (known, documented in `atsform.py`). When
`combobox_pick` falls back past that to its "input-less dropdown" / freetext path, it can
report `OK=freetext:<value>` (or even a plain `option-click:<value>`-looking success) while
the widget's actual VISIBLE selection is a **different, nearby-in-the-list option** — not the
one requested, and not empty either, so it looks superficially fine (a real backing numeric
ID gets written, e.g. `tor__fcustUKEthnicity` -> `9942`). On the Service Designer application,
asking for **"Mixed Origin"** on the "Individual Race /Ethnicity" field silently landed
**"Black"** — a wrong DEMOGRAPHIC answer, the worst category to get wrong silently, and it
only surfaced on a pre-submit visual review screenshot (the a11y/DOM value read `Mixed Origin`
was NOT what was checked — the actual rendered `<input>.value` needs to be read/screenshotted,
not just trust the pick call's return string).

**The reliable fix, verified twice (Content Designer 429708 + Service Designer 397090):**
open the widget, then commit a REAL per-char filter rather than relying on the pick engine's
fallback:
```js
(()=>{const el=document.getElementById('<n>:_input'); el.focus();
const s=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
s.call(el,'<partial text, e.g. "United King">');
el.dispatchEvent(new Event('input',{bubbles:true}));
el.dispatchEvent(new KeyboardEvent('keydown',{bubbles:true,key:'g'}));
el.dispatchEvent(new KeyboardEvent('keyup',{bubbles:true,key:'g'}));
return el.value;})()
```
then re-query `li[role=option]` (the list re-renders/filters down to matches) and `.click()`
the option whose `.innerText.trim()` EXACTLY matches the target — never trust a bare
`combobox_pick()` call on this widget without a follow-up visual (screenshot) or backing-value
check (`document.querySelector('[name*=fcustUKEthnicity]').value` should be a plausible numeric
ID, but note the wrong option ALSO has a numeric ID — the only real check is reading the
VISIBLE `.value` text of the `_input` element, or a screenshot, against the intended option).

**Practical rule: after ANY `combobox_pick` on an SF `<n>:_input` field, re-read
`document.getElementById('<n>:_input').value` and compare it verbatim to the intended option
text before trusting it — especially for EEO/demographic fields.** A short list (< ~15 options,
e.g. Yes/No, work-eligibility) reliably resolves via plain `option-click` inside `combobox_pick`
with no issue seen so far; the failure was only observed on the longer virtualized lists
(country-of-residence, 190+ countries; ethnicity, 30 options) where the async suggestion path is
what's broken.

## Verified flow (guest self-registration apply, no pre-existing SF account)
1. `cfx.goto` the direct job URL — `https://career5.successfactors.eu/career?career_ns=job_listing&company=<company>&career_job_req_id=<reqId>` lands straight on the job posting, skip the search page.
2. Accept the cookie banner (`Accept All Cookies`) before anything else — it overlays a click target.
3. Click `Apply` (`a`/`button` with text `Apply now`/`Apply`) — this reveals the guest-apply
   form INLINE on the same page (resume, cover letter, email/password self-registration, name,
   phone, EEO questionnaire) — no separate signup step.
4. **CV upload**: click the plus-glyph icon `span#<n>:_attachIcon` to force-create
   `input[name="fileData1"]`, then `POST /tabs/<tab>/upload` to it. Confirmed by the page text
   containing the uploaded filename.
5. Email/password/name/phone fields (`fbclc_userName`, `fbclc_emailConf`, `fbclc_pwd`,
   `fbclc_pwdConf`, `fbclc_fName`, `fbclc_lName`, `fbclc_phoneNumber`) — `/type` 500s on these
   too in practice; use the native-setter + `input`/`change`/`blur` event dispatch directly (see
   `_sign_in`'s password-setting code in `sf_apply.py` for the pattern). **Save the
   self-registered password to `ats-credentials.csv` under
   `career5.successfactors.eu (<Company>)`** — a second application on the SAME SF tenant
   (`company=` param) re-uses the candidate profile (resume, name, email, phone, even
   Country of Residence carry over) once signed in, cutting the second application's fill
   time drastically.
6. `select#fbclc_ituCode` (phone country code) and `select#fbclc_country` (Country of
   Application) are plain native `<select>` elements — set `.value` directly + dispatch
   `input`/`change`, no combobox dance needed.
7. Privacy Notice acknowledgement (first application on a tenant only): click the
   `a#dataPrivacyId` link, it opens a `[role=dialog]` modal — click its `Acknowledge` button.
   A SUBSEQUENT application on the same tenant/account does not re-ask this.
8. **The visible "Apply" span (`span#qaApplyBtnWrapper`) is a WRAPPER, not the real
   button** — clicking it does nothing (no error, no navigation, looks like a no-op). The
   real target is the nested `button#fbqa_apply` — click that directly. Successful submit
   replaces the whole page with `Your application has been sent. Thank you!`.
9. A validation failure re-renders the SAME form with a banner at the very top: `Please
   complete all required fields and re-submit. The following fields require a valid input:
   <Field Name>` — re-check that exact field's backing value/visible text before re-submitting.

## `sf_apply.py`'s "Apply now" click regex missed a plain "Apply" button (FIXED 2026-08-26, Capgemini UX Designer req 189453)
The reveal-the-form click used `/apply now/i` only. This posting's button text is plain
`Apply` (`#fbqa_apply`), so the regex found nothing, the `if(a) a.click()` silently no-op'd,
and the script fell straight through to filling fields against the still-collapsed
job-listing page — `Email` landed on some unrelated hidden field, and CV upload then failed
with `no attach icon` because the guest-apply section was never opened. **Fix (in
`sf_apply.py`): match `#fbqa_apply`/`[id$=":_apply"]` by id FIRST, falling back to a
broadened `/^apply( now)?$/i` text match**, and print a WARN if neither is found instead of
silently continuing.

## ⛔ EDITING ONE `<n>:_input` PICKLIST CAN SILENTLY BLANK A SIBLING FIELD (verified live 2026-08-26, Capgemini UX Designer req 189453) — re-verify EVERY picklist right before submit, not just the one you just touched
On the returning-candidate (signed-in) application form, committing a value into one
`<n>:_input` picklist via the native-setter+filter method (the reliable fix documented
above) can trigger a React re-render that **silently clears the committed value of a
DIFFERENT, already-filled picklist** elsewhere on the same page — observed twice in one
session: (1) setting the 4 custom Yes/No screening radios, then fixing 5 unrelated
picklists, wiped all 4 radios back to unchecked; re-setting the radios AFTER the picklists
fixed it and they held. (2) Fixing the "disability adjustments" (field 25) and "gender
identity" (field 33) pickists, then fixing two unrelated consent picklists (21, 29),
silently blanked 25 and 33 back to empty even though they had verified-correct values
moments earlier. **Neither wipe surfaced as a validation error** — the fields just read
empty on the next read. **Practical rule: do a full VALUE=='' sweep of every previously-set
picklist/radio immediately before clicking the final submit button, and re-fill anything
that reads back empty — never trust "I set it earlier and verified it once" as sufficient
for a form with more than one picklist.** Also confirms the NOTES.md warning above generalizes
beyond ethnicity/country: apply the "re-read `.value` after every commit" rule to ALL
`<n>:_input` fields on a multi-picklist SF form, not just the historically-flaky ones.

## `atsform.fill_eeo()`'s generic ethnicity attempt still fails to commit on THIS form's widget — the manual native-setter+filter fix works reliably
`fill_eeo()`'s combobox_pick attempt on "Individual Race /Ethnicity*" reported
`FAIL: free-text commit had no resolved target — refusing to guess a field` (safe failure,
did not silently pick wrong) — same underlying widget flakiness as the earlier-documented
ethnicity/country lists. The manual fix (clear value via native setter → type a short filter
string e.g. `"Mixed"` → dispatch `input`+`keydown`+`keyup` → wait ~1.5s → find the
`li[role=option]` whose `innerText.trim()` EXACTLY equals the target → `.click()` it → re-read
`.value` to confirm) resolved it cleanly to `"Mixed Origin"` (this Capgemini form's actual
broad-category label — matches the applicant's truthful "Mixed" identity). This form's option
list for "How do you identify?" (field `33`) is literally `Female`/`Male` (not `Man`/`Woman` as
`applicant-profile.md`'s example phrasing suggests) — filter by a short prefix (`"Ma"`) and
match on the REAL rendered option text, don't assume the profile's example wording is the
verbatim option label on every tenant's form.

## Signing in mid-application (returning candidate) swaps the guest-form's uploaded CV for the profile's stored one — always re-check/re-upload the CV AFTER sign-in, not before
On a guest-apply form (not yet signed in), the CV/cover-letter attach icons work immediately
(`span[id="<n>:_attachIcon"]`, click → `input[name="fileData1"]` appears within ~1.5s — the
documented `_upload_cv` 4s wait is sufficient in practice; the ONE observed `CV_UPLOAD_FAIL
file input never appeared` was a one-off flake, not reproducible on a manual retry with the
identical selector). But clicking "Already a registered user? Please sign in" (`a[onclick=
openSignInModal()]`, modal fields `#username`/`#password`, submit `button#fbqa_signin`) DROPS
whatever was uploaded pre-sign-in and reloads the candidate's PREVIOUSLY-STORED document from
an earlier, different application (e.g. `base-resume.pdf` from a prior job's submission) —
the Resume field re-renders with an EDIT (pencil) icon instead of a PLUS icon once a document
already exists on the profile. **After any sign-in step, re-check the Resume/Cover-letter
filename in the page body text and re-upload via the pencil-icon flow
(`span[id="<n>:_attachIcon"]` with class `glyphicon-pencil addAttachments`, same
click→wait→`/upload`→confirm-by-filename recipe, just a different icon glyph) if the
attached filename doesn't match the CURRENT application's tailored resume.** Don't trust a
pre-sign-in CV upload to survive sign-in.

## `#fbqa_apply` click POST reports `timed out after 30s` on a SUCCESSFUL submit — don't treat the click timeout as failure, re-check page state first
Both the sign-in submit (`#fbqa_signin`) and the final apply submit (`#fbqa_apply`) triggered
a real page navigation, and `cfx.click_selector`'s underlying Playwright trusted-click POST
timed out (30s) BOTH times — apparently because the click's own actionability-wait outlives
the page it was clicking on (the DOM it's inspecting for post-click state gets torn down by
the navigation mid-wait). In both cases the click had actually fired and the intended
transition happened (signed in / application submitted) despite the client-side timeout
error. **On a `timed out after 30s` CfxError from `click_selector` on a submit-shaped
button, don't assume the click failed — re-read `document.title`/`location.href`/
`document.body.innerText` immediately; a "Your application has been sent. Thank you!" body
means it worked.**
