# jobs.service.gov.uk ("GOV.UK Work Hub / Find a job") — site notes

A GOV.UK-branded experimental job-search aggregator (nav item "Find a job" under "Work
Hub"). Added 2026-08-28. **This is NOT Civil Service Jobs** (`civilservicejobs.service.gov.uk`,
board `csj`) — different domain, different platform, different account system — but it
DOES surface some genuine Civil Service vacancies as a subset (see Dedup below). It also
carries a large volume of ordinary UK private-sector/agency ads (retail, construction,
recruitment agencies, etc.), despite the GOV.UK branding — think "a general UK jobs
aggregator that GOV.UK happens to run", not "the government's own vacancies".

Scripts: `scripts/feed.py` — browser-driven search enumeration (registered in
`pipeline.FEEDS` as board `govukjobs`; rows added to `searches.csv`). No apply driver
shipped yet — every candidate needs a per-posting `/jobs/<id>/apply` check to see which
of the two apply shapes it is (see below), then the generic `atsform.py apply` engine for
the ones that don't hit the GOV.UK One Login wall.

**Akamai-fronted, camofox-only.** A plain `curl`/non-browser UA gets HTTP 403 on the
search page. There is no keyless HTTP sourcing path here (unlike ats-direct/Adzuna) —
`feed.py` must run with a live `CFX_TAB`.

## Search mechanics (verified 2026-08-28)

`https://www.jobs.service.gov.uk/jobs/search?keywords=<kw>&locationId=<id>&location=<text>`
  - `keywords` blank returns the WHOLE board (8,958 results for a London search at time
    of writing) — always pass a keyword. No boolean OR observed (same discipline as CSJ:
    one term per query, add more `searches.csv` rows for more families).
  - `location` alone (a bare city name, e.g. `location=London`, no `locationId` needed)
    works fine — verified live 2026-08-28, same result-card count as a postcode-anchored
    search. That's `feed.py`'s tracked default (`DEFAULT_LOCATION_TEXT = "London"`) — a
    BARE city name, deliberately, NOT a real postcode (keeps this tracked file PII-free,
    SKILL.md §12). ⚠️ **`"London, England"` (with the comma+country suffix) returns ZERO
    results** — verified live, the geocoder doesn't resolve it — so if you ever see that
    form reintroduced here or in feed.py, it's a regression, revert to the bare city name.
  - `locationId=<postcode-derived-id>&location=<postcode>%2C+Greater+London%2C+London%2C+
    England` also works and anchors a tighter 10-mile radius (verified with the
    applicant's real postcode from `apply-defaults.json`'s `"Postal"` field — do NOT
    hardcode a real postcode in this NOTES file or feed.py; pass it via `--where`/
    `--location-id` at call time if postcode precision is wanted).
  - Pagination: `&pageNumber=N` (1-indexed). The site returns HTTP 200 with an empty
    result set past the last page (doesn't 404 like Hackney) — `feed.py` stops when a
    page yields zero NEW ids, not on a page-not-found signal.

Cards are clean, stable `data-testid` attributes — no scraping fragility observed:
`div[data-testid^="searchResultCard-"]` (id embedded in the testid) wraps
`a[data-testid^="jobTitle-"]` (href `/jobs/<24-hex-id>`), `p[data-testid=
"searchResultCardEmployer"]` (two `<span>`s: company, `" - location"`),
`p[data-testid="searchResultsCardTags"]` (Permanent/Full time/Hybrid/etc. spans), and
`p[data-testid="searchResultCardJobDescription"]` (a JD snippet, useful for a cheap
first-pass screen before opening the posting).

## Apply mechanics — TWO shapes, only knowable per-posting

Open `https://www.jobs.service.gov.uk/jobs/<id>/apply` — it always lands on a "Before you
apply" interstitial (standard "don't include bank details/NI number/DOB" notice). The
button on THAT page tells you which shape this posting is:

### Shape A — "Continue to the employer's website" (external redirect)
No GOV.UK login needed. Lands on the employer's own careers page or a 3rd-party ATS.
**Prefer this shape** — drive it like any other external-ATS posting. A first pass
(2026-08-28, ~15 postings checked across UX/Product-Design/DevOps/IT-Support/Business-
Analyst keywords) found bespoke/agency systems almost exclusively — NONE of the standard
guest-drivable ATSes (Greenhouse/Ashby/Lever/SmartRecruiters/Workable) turned up in that
sample. Observed destinations: `additionalresourcescareers.net`, `contactrh.com`
(Webrecruit-powered agency sites), `aplitrak.com` (Hays redirect layer), `webrecru.it`,
`aventumhr.my.salesforce-sites.com`, `*careers.co.uk` bespoke company portals (Kier,
Virgin Active, AS Watson). **Always run `ats_router.classify()` on the redirect URL
first** in case a guest-drivable ATS does turn up in a larger sample — don't assume every
redirect is bespoke from this one sample.

**Verified working example — Additional Resources' portal (Webrecruit-family), plain HTML
form, no login:** fields are `First Name*`/`Middle Name`/`Last Name*`/`Email Address*`/
`Mobile Number*`/`Cover Letter File` (optional upload)/`Select cv*` (required upload),
submit button text is **"Save & Proceed"**. Drives cleanly through the generic
`atsform.py apply` engine with `"defaults": true` — see "Verified end-to-end test
applications" below for the exact run and the real bug it surfaced.

### Shape B — "Continue" (in-platform GOV.UK Design System wizard) — LOGIN WALL at submit
No visible redirect; the button just says "Continue" (not "...to the employer's
website"). This is a native multi-step wizard hosted on jobs.service.gov.uk itself:
`Your details` (Full name) → `Upload CV` → `Include a message or covering letter` → ...
All of that fills fine with the generic engine (see the upload gotcha below). **But
submitting past the cover-message step requires being signed in to GOV.UK One Login**
(`/auth/sign-in?returnTo=...`) — confirmed by manually POSTing the page's own
`/api/jobs/apply` endpoint and getting back `401 {"error":"Unauthorised"}` even with a
non-empty payload (the UI just shows a generic "Something went wrong. Please try again."
banner, which is misleading — it is NOT a form-validation error, it's the 401 masked).

**GOV.UK One Login requires a mobile phone number for SMS/call verification** on top of
email+password. Credentials row `jobs.service.gov.uk (GOV.UK One Login)` now exists in
`ats-credentials.csv` (added 2026-08-28 — the user already holds this account), so
email+password sign-in itself is NOT a hard stop — but the SMS/call code that follows
is a **per-session OTP the agent cannot receive**. Treat this exactly like SKILL.md's
standard **login-wall hard stop**: navigate to `/auth/sign-in`, enter the credentials,
and when the OTP prompt appears, STOP and message the user (site, that it's a GOV.UK
One Login SMS/call code, the noVNC link) and WAIT — do not guess, do not retry, do not
skip past it. Once the user relays the code (or completes it themselves in noVNC), enter
it, confirm the session (account/"Sign out" visible), and resume the SAME in-progress
application from where the wizard left off — the form state on jobs.service.gov.uk
survives a same-tab sign-in redirect since `returnTo` brings you back to the exact
posting's cover-message step. Log `Blocked` (retryable, not permanent) if the user isn't
available to supply the code right then; re-attempt once a session is confirmed live
rather than re-asking for a fresh code every posting — the One Login session, once
established, should persist across multiple Shape B applications in the same run.

## Form mechanics that matter

**GOV.UK Design System file-upload widget produces a FALSE NEGATIVE in `atsform.upload()`
— verified on the in-platform "Upload a CV" step (Shape B).** The real `<input
type=file id=cvUpload class=govuk-file-upload>` is CSS-hidden (`position:absolute;
width:1px;height:1px;clip:rect(0,0,0,0)`) by the enhanced GDS component, which replaces
the visible interaction with its own styled dropzone. `atsform.upload()`'s POST to
camofox's `/upload` endpoint DOES succeed server-side (`{"ok":true,"uploaded":"/uploads/
<file>"}`, confirmed in the camofox container logs), and the page visibly shows "Files
added — `<file>` has been added" with a green checkmark — **but re-reading
`document.querySelector(sel).files[0].name` afterward returns empty**, because the
GDS component's JS re-render either replaces the input node or stops reflecting state
through the original element once the file is registered in its own internal list. So
`upload()` reports `FAIL upload 'Upload a CV': NONE` on a genuinely successful upload.
**Do not trust that FAIL for this specific widget class** (`class="govuk-file-upload"`)
— screenshot the page instead to confirm ("Files added" + filename + green check is the
real success signal on this shape). This is a candidate for a general `atsform.upload()`
fix (checking for a sibling "Files added"/filename-echo element as a fallback success
signal) if the GDS file-upload component is encountered on other GOV.UK-family sites
(NHS Jobs, findapprenticeship.service.gov.uk likely share it) — not fixed here because
Shape B is a hard stop anyway (can't reach submit without One Login), so the false
negative doesn't currently block a real application; flag it if that changes.

Also on Shape B: the cover-message textarea (`#coverMessage`) has **no `<label for>`
association** — `atsform.fill("message", ...)` / any label-substring lookup fails
(`FAIL fill: no text field for label ~'message'`); address it directly by CSS id instead
(`atsform.py fill "#coverMessage" "@/path/to/cover.txt"`).

## Known failure modes + verified fixes

**⛔ REAL BUG FOUND AND FIXED (2026-08-28) in the SHARED `atsform.py` — affects every
board that uses `"defaults": true`, not just this one.** Driving Shape A's plain-HTML
form (First Name / Last Name / Email Address / Mobile Number) surfaced a genuine
cross-field-contamination bug in `_fill_with_aliases`'s alias table:
`apply-defaults.json`'s `"full name"` default aliases to `["name", ...]` and
`"address line 1"` aliases to `["address", ...]`. Those two bare, single-word aliases
matched via `_RESOLVE`'s tier-2 "word-boundary anywhere in the label" rule — which also
matches ANY OTHER field whose label merely CONTAINS that word. Concretely: alias `"name"`
(meant to bind "Full name" to a field literally labelled just "Name") ALSO tier-2-matched
the **"First Name"** field (because "First Name" contains the word "name") and overwrote
the correct value ("Jane", set moments earlier by the "First name" default) with the
WRONG one ("Jane Doe", the full-name value). Same mechanism: alias `"address"` (meant
for "Legal Address"/plain "Address" fields) tier-2-matched **"Email Address"** and filled
the applicant's street address into the email field. Both are silently WRONG answers that
would have gone out on a real submitted application if not caught by a visual review
before submit — this is exactly the class of error SKILL.md's step-6 review exists to
catch, and it very nearly went out (confirmed live on the AA Global Group / Additional
Resources posting before being caught and fixed).

Root cause: `_fill_with_aliases` called every alias through the same unrestricted
`fill()` → `_resolve()` path (tiers 0–3, where tier 2/3 allow a loose "word appears
anywhere in the label" match) with no distinction between a safe multi-word alias
("legal address", "phone number" — very unlikely to collide) and a dangerous bare
dictionary word ("name", "address" — highly likely to collide with sibling fields like
First/Middle/Last Name or Email/Home/Billing Address).

**Fix (shipped in this commit, in `sites/_common/scripts/atsform.py`):** `_RESOLVE`'s JS
now accepts a `maxTier` cutoff; `_resolve()`/`fill()` thread through a `max_tier`
parameter (default 3, unchanged behaviour for every existing caller); a new
`_STRICT_TIER_ALIASES = {"name", "address"}` set makes `_fill_with_aliases` pass
`max_tier=1` (exact match or starts-with only) for exactly those two aliases, while every
other alias keeps the old loose matching that was added on purpose to fix real blockers
(preferred-surname/zip-code/legal-address wording mismatches — see the alias table's own
inline history). Verified live on THIS posting: before the fix, "First Name" held "Jane
Doe" and "Email Address" held the street address; after the fix (re-run on the same
live page after manually clearing both fields), First Name = "Jane", Email Address =
"you@example.com", Last Name/Mobile unaffected (they were already correct — they don't hit
the alias fallback at all, since "First name"/"Last name" exact-match their own fields
directly). `python3 -m py_compile` clean; no regression expected for the OTHER aliases
in the table since only `"name"` and `"address"` were restricted.

**Any other board using `"defaults": true` with a form that has separate First/Middle/
Last Name fields (no single "Full Name"/"Name" field) and a separate Email field (no
literal "Address" field) was ALSO at risk of this same silent corruption** — this wasn't
a jobs.service.gov.uk-specific bug, this posting just happened to be the one that
surfaced it. If you see a suspiciously full "First Name" or a suspiciously
non-email-shaped "Email" field on ANY board's review screenshot, this is the first thing
to suspect (check the applied `atsform.py` version has this fix).

## ⛔ REAL BUG FOUND (2026-08-29) — "Your details" Full name field filled with the WRONG name

Drove several Shape B applications this run using `atsform.py fill "Full name" "Jane Doe"` —
that literal string is SKILL.md's generic placeholder/example applicant name (used in the
doc's own "quick form facts" section as a stand-in for illustration), **NOT the actual
applicant's name**. It does not match the real value in `sites/_common/apply-defaults.json`'s
`fill."Full name"` key (that file is gitignored and is the real source of truth — read it
directly, never infer the real name/email from SKILL.md's example text OR from prose in this
note, including this sentence). **Correction to an earlier draft of this section:** an earlier
version incorrectly claimed the uploaded CV/cover letter also carried the wrong (placeholder)
name — that was checked and is FALSE. The resume PDFs (e.g. `uploads/family-support.pdf`,
verified via `pdftotext`) correctly carry the applicant's real name/email/phone throughout, as
they always have. Only the GOV.UK Work Hub's own "Your details" form FIELD was wrong on these
3 submissions — the CV attachment itself was always correct.

So at least 3 applications this run went out with the Work Hub's own "Your details" name field
reading the WRONG (SKILL.md-placeholder) name while the attached CV/cover letter correctly
carry the applicant's REAL name — a visible, confusing name mismatch on a real submitted
application (same failure class as the alias cross-contamination bug documented above: a
plausible-looking default silently wrong). Confirmed affected (still logged `Applied` —
GOV.UK's account UI has no post-submit edit/undo, so this cannot be fixed after the fact):
**E-Wealth Alternatives (Social Media & Content Executive)**, **NM Software Solutions (Cloud
Engineer)**, **NM Software Solutions (Business Analyst)**. The two Shape B submissions from
the ORIGINAL 2026-08-28 sweep (Rannes Departmental Store Web Designer, Hado Catering Promotion
Business Analyst) may or may not carry the same mistake — the saved confirmation screenshots
only capture the final "Application sent" page, which doesn't echo the name field back, so
this could not be verified either way from the artifacts on disk. The mistake was caught and
stopped before the 4th Shape B posting attempted this run (Chevron/Ramudden, which was
separately Skipped for an unrelated truthful-answer reason) — no submissions after these 3
carry this error.

**Fix (in effect from the point this was caught onward):** always fill the "Your details" →
"Full name" field by reading the current value straight out of `apply-defaults.json`'s
`fill."Full name"` key at drive time, never by typing SKILL.md's illustrative placeholder
text. General lesson for this whole skill: SKILL.md's "Quick form facts" example block
(Jane Doe / you@example.com / example.com) is DOCUMENTATION SHORTHAND, not a literal value to
type into a live form — the actual source of truth for every form field is
`sites/_common/apply-defaults.json` + `references/applicant-profile.md`.
Cross-check against those, never against SKILL.md's own illustrative text or against a PRIOR
note's prose (as this very section demonstrates — verify the underlying file directly), before
filling a name/email field on any board.

## What success looks like

**Shape A (external redirect), Additional Resources/Webrecruit-family form:** page
re-renders in place (no URL change) to a "Thank you" panel — heading "**Thank You for the
submission.**" plus a "Click here to return to our careers page" link. Screenshot that
panel as proof.

## Verified end-to-end test applications

- **2026-08-28 — Additional Resources (recruiting agency; employer anonymised in the ad
  as "a global ship owner"), Junior IT Support Engineer / IT Support Technician,
  Westminster, £25k-£30k.** Sourced via `govukjobs` keyword `"IT Support Engineer"`,
  Shape A external redirect from `jobs.service.gov.uk/jobs/6a76230e13170e423c0ee89c` to
  `additionalresourcescareers.net`. Full generic-engine drive: `atsform.py apply` with
  `"defaults": true` + `{"upload": {"Select cv": "family-support.pdf"}}`, `atsform.py
  review "Additional Resources"` (clean), `atsform.py submit "Save & Proceed" "thank|
  success|received|submitted|application"` → `SUCCESS: submission confirmed`, proof at
  `applications/additional-resources-junior-it-support-engineer-it-support-technician/
  confirmation.png`, logged via `log-application.py`. This run is what surfaced and
  verified the alias cross-contamination bug above (caught via the pre-submit
  screenshot review, fixed, and RE-VERIFIED correct before the real submit — the
  submitted application carries the CORRECT field values, not the buggy ones). Proves:
  the board sources correctly, the generic `atsform.py apply` engine drives a
  plain-HTML external ATS form on this board end-to-end with no board-specific driver
  needed, and the fix holds on a live page.
- **2026-08-28 — DevOps Engineer posting (id `6a72d2eb8426b08f481ed67d`), Shape B
  in-platform.** Drove `Your details` → `Upload CV` (hit the false-negative upload
  described above; confirmed via screenshot that the upload actually succeeded) →
  `Include a message or covering letter` (filled via `#coverMessage` CSS-id, since the
  textarea has no associated `<label>`) → blocked at Continue with a masked 401 from
  GOV.UK One Login. Confirmed the underlying cause by a manual `fetch('/api/jobs/apply',
  ...)` from the page context returning `401 {"error":"Unauthorised"}`. Logged as the
  genuine hard-stop described above — not applied (correctly; would have needed an
  account this run cannot create).

## GOV.UK One Login is NOW WORKING end-to-end (2026-08-28, later same day)

The SMS/call hard-stop above is SUPERSEDED. `ats-credentials.csv` row `jobs.service.gov.uk
(GOV.UK One Login)` was added, and a live session was established via
`/auth/sign-in` -> One Login -> **TOTP code from an authenticator app** (NOT SMS — the
page's own copy about SMS/call is misleading; the actual second factor asked for was a
6-digit authenticator-app code). Once live, the session is a normal browser-profile
cookie and **persists across MANY Shape B postings in the same run** (verified: 4+
in-platform submissions back-to-back with zero re-auth) — check liveness by hitting
`/account` and looking for "Sign out" in the header + "Welcome back!"; only re-request a
code if that check actually fails, never pre-emptively. Shape B is therefore now REAL,
drivable inventory, not a standing hard stop — drive it like Shape A.

## Verified end-to-end Shape B submissions (2026-08-28, session established)

- **Rannes Departmental Store Ltd, Web Designer.** Your details -> Upload CV
  (family-design.pdf) -> cover message (tailored WordPress/CryptoKnowledge web-design
  copy) -> Continue landed directly on "Application sent" (no fresh login prompt — the
  session from an earlier posting was still live). proof=confirmation.png.
- **Hado Catering Promotion Limited (trading as "Hanawata London"), Business Analyst.**
  Same flow, family-product.pdf, tailored cover message. proof=confirmation.png.

## Shape A additional verified patterns (2026-08-28)

- **`app.webrecruit.co` (Webrecruit "ApplyOnline" flow)** — distinct from the
  Additional-Resources-portal Webrecruit pattern already documented above. URL shape
  `https://app.webrecruit.co/JobSeeker/ApplyOnline?jobid=<id>&boardid=<id>`. Flow:
  "Apply as Guest" -> a "Confirm email address" modal (fill `#email`, click Proceed —
  **the FIRST attempt's fill can get wiped when the modal re-opens on the immediately
  following "Apply as Guest" click; re-fill immediately before the actual Proceed that
  advances**) -> "Upload your CV" (a real, working `input#UploadResume`, no false
  negative here) -> a separate **`input[type=submit][value="Upload"]`** button (NOT
  text-matchable via `.textContent` — it's an `<input>`, use `.value`) confirms the
  upload and advances to "Choose your resume" (select the uploaded file's radio, click
  Continue) -> a full **Application Questions** page (covering letter textarea +
  Webrecruit's standard EEO block rendered as **radio-styled `<input type=checkbox>`
  groups for single-select questions** like Ethnicity/Religion — same
  looks-like-radio-is-actually-checkbox quirk as other Webrecruit-family boards; verify
  each group's real `type` before choosing radio vs checkbox selectors) -> Confirm
  Contact Details (First/Last/Mobile **AND an "Evening number" that LOOKS optional in
  the UI but is server-side required** — fill it with the same mobile number if no
  landline exists, or the final submit bounces with "The Evening number field is
  required.") -> "Apply for Job" submits to a real "Congratulations! You've applied..."
  confirmation. Verified live: The Institution of Structural Engineers, Digital Content
  Producer (Farringdon, EC1V). proof=confirmation.png.
- **`aptrack.co` (a Hays-style tracking-redirect layer, same family as `aplitrak.com`)**
  — URL shape `https://www.aptrack.co/uap/<token>/`. A "Go to application form" link
  reveals a SIMPLE inline form on the same page (`firstName`/`lastName`/`email`/`phone`/
  `cv` file/`message` textarea) — drives cleanly through the generic `atsform.py apply`
  engine, submit button text "Apply now". Verified live: IPS Group Limited (recruiting
  for an undisclosed insurance-sector employer), Business Analyst.
  proof=confirmation.png.

## Known dead-ends / walls found sourcing broadly (2026-08-28)

- **`careers.virginactive.co.uk`** — a Shape A redirect can 404 on the employer's own
  portal even though the GOV.UK card still shows the posting as live (Virgin Active,
  Product Designer vacancy 37264). Genuinely dead advert, not a driver bug — check for a
  plain "404/Page not found" body before assuming a filling problem.
- **`aswatsoncareers.com` (AS Watson Group's careers portal)** — "Start application"
  opens an in-page CONVERSATIONAL CHATBOT widget (not a static form), including a
  structured "Fill in manually" address sub-form. Every field binds fine via native-setter
  value/checked assignment (verified: name/email/address/state all readable back
  correctly), but the form's own Send/submit control (`aria-label="Send"`,
  `type=submit`) never advances the conversation — tried a plain `.click()`,
  `form.requestSubmit()`, a TRUSTED `cfx.click_selector()` (timed out 30s), and a
  blur-triggered validation retry. Genuine dead submit on this specific chatbot widget;
  logged `Blocked`, not a false negative.
- **`careers.hippodigital.co.uk` (Hippo Digital's ASP.NET WebForms candidate portal)**
  — registration requires an account; the whole outer registration form is inside ONE
  iframe (`registration.aspx`) and fills fine via `cfx.py eval-frame` (name/email/
  password/mobile/address/all radios/consent all verified bound). BUT the mandatory "You
  must have at least 1 CV" upload opens ANOTHER, nested iframe (`/Popups/UploadFile.aspx`,
  a Telerik RadUpload control) two levels deep from the top document — the camofox
  `/upload` REST endpoint cannot reach it (every selector/frame-param variant tried
  returned HTTP 500; `eval-frame` CAN read text out of that same nested iframe, so the
  gap is specific to `/upload`, not iframe traversal in general). Genuine tool capability
  gap, written up in `sites/_common/CAPABILITY-GAPS.md`. Blocked all three Hippo Digital
  roles sourced this run (Intermediate Content Designer / UX Designer / User Researcher)
  on this one wall — don't re-attempt per-role, it's the same registration flow.
- **`wavetrackr.com` apply forms (used by Essential Employment Ltd and probably other
  agencies)** — a plain HTML form but gated by a VISIBLE Cloudflare Turnstile "Verify you
  are human" checkbox. Non-sanctioned CAPTCHA per SKILL.md — full halt, escalate via
  `blockers.py record`, do not attempt to solve. Verified live: Essential Employment Ltd,
  Content Designer (Hackney).

## Genuinely UK-wide remote search (2026-08-28, coordinator-prompted)

The `location` query param does NOT accept the word "Remote" — GOV.UK's own city/
postcode autocomplete rejects it outright ("There are no matching locations for
'Remote'", 0 results). The CORRECT mechanism is the separate **Working Pattern**
filter, exposed as the URL param **`jobBase=REMOTE`** (seen live on the checkbox
inputs: `jobBase=REMOTE|ONSITE|HYBRID|FIELD_BASED`). It works **standalone with no
`location`/`where` param at all** — `?keywords=<kw>&jobBase=REMOTE` searches the
WHOLE UK and returns genuinely home/anywhere-based roles ("3 UX Designer jobs in UK
With the following filter: Remote"), a separate pool from the London-anchored
`--where` searches this file documents elsewhere. Drive it via `feed.py --nav
"https://www.jobs.service.gov.uk/jobs/search?keywords=<url-encoded kw>&jobBase=REMOTE"`
(the `--nav` flag takes a full search URL, bypassing `--what`/`--where` entirely).
Verified live: VolkerWessels UK's Graduate Digital Developer (nominally "Preston,
PR2 5PE" but Working pattern = Remote) came from exactly this search and was
successfully applied to.

## `jobs.justice.gov.uk` (MoJ's Oracle Recruiting-style portal — DISTINCT from
`jobtrain.co.uk`, both under "Ministry of Justice", 2026-08-28)

Real, drivable Shape A pattern, separate account system from the `jobtrain.co.uk`
Justice Digital portal documented elsewhere in this file — same employer name, two
completely different ATSes depending on which MoJ team posted the vacancy. Two sharp
edges found:

1. **Some `<select>` fields (County, Nationality, and other large/searchable lists)
   are Select2 autocomplete widgets whose underlying `<option>` list is EMPTY until
   you search** — programmatically injecting a fake `<option>` and setting `.value`
   LOOKS like it worked (the widget visually updates, `select.value` reads back
   correctly) but the server silently rejects it on the next page submit ("This field
   is required" reappears, real user-visible data loss). The fix: dispatch a real
   `mouseover→mousedown→mouseup→click` event sequence at the `.select2-selection`
   element's centre coordinates (a plain `.click()` does NOT reliably open the
   dropdown here — Select2 needs the fuller mouse-event sequence), which opens
   `.select2-results__option` items; if a `.select2-search__field` input is present,
   set its value via the native-setter trick + `input` event to filter the list, then
   click the matching real `.select2-results__option` (via `mouseup`, not `click` —
   that's the event Select2 listens for). Confirmed genuine only when
   `select.selectedOptions[0]` shows a real numeric option value the widget generated
   itself, never a value you invented.
2. **A required radio group can have a same-named HIDDEN decoy `<input type="hidden"
   name="X">` positioned BEFORE the real `<input type="radio" name="X">` in the DOM**
   — `document.querySelector('input[name="X"]')` with no type filter silently grabs
   the decoy, and setting `.checked` on it is a complete no-op with no error (the real
   radio never shows checked, and a Submit attempt bounces with "This field is
   required" while every OTHER field on the page reads back fine). Cost two failed
   Submit clicks on the final Declaration page before being caught. **Always qualify
   a radio/checkbox selector with `input[type=radio]`/`input[type=checkbox]`, never a
   bare `input[name=...]`, on this ATS** (and generally, whenever a same-named field
   mysteriously won't take a value here). A failed Submit that resets a field back to
   empty with no visible error is a strong signal to check for exactly this pattern
   before retrying blindly.

## `feed.py --nav` pagination BUG (found + fixed 2026-08-28, later same day)

`feed.py`'s page loop used `nav` (the caller's full search URL, e.g. one carrying
`&jobBase=REMOTE`) **only for page 1** and silently fell back to the default
London-anchored `_search_url()` — which has no `jobBase` support at all — for every
page after that. So a `--nav "...&jobBase=REMOTE" --pages 3` call was really "1 real
remote page + 2 regular London pages for the same keyword", re-fetching London noise
under a REMOTE label. Confirmed live: an unfixed 3-page run against `IT Support
Technician&jobBase=REMOTE` returned cards tagged `location: "London"`, `"Kent"`,
`"Slough"` etc. mixed in with `"Remote"` ones. **Fixed** with a new `_nav_page_url(nav,
page)` helper that rewrites the `pageNumber` param onto the SAME nav URL (preserving
every other param) instead of falling back to `_search_url()`; the main loop now calls
`_nav_page_url(nav, p) if nav else _search_url(...)`. `py_compile` clean. Re-ran the
same 6 families post-fix — genuine remote-only pagination confirmed (fewer total cards
than the buggy run, as expected once the London contamination is removed). Any other
board's `feed.py` that supports both `--nav` and `--pages` should be checked for the
same bug shape.

## 2026-08-28 (later same day) — broad re-sourcing sweep: Shape A pool confirmed thin

Coordinator-prompted push past the 13-Applied baseline. Ran a large fresh sourcing pass
specifically to test whether the "pool is thinning" read from earlier today still held:
- 20 NEW London-anchored keyword families (3 pages each) not in the original 37-row seed
  — Design Systems Designer, Accessibility Designer, Content Strategist, Junior/
  Application Security Analyst, Technical Support Analyst, 2nd Line Support, Computer
  Repair Technician, Motion Designer, Video Editor, Prompt Engineer, AI Product
  Designer, Digital Engagement Officer, Release Engineer, Web Operations Engineer,
  Vulnerability Management Analyst, Design Researcher, Usability Analyst, Creative
  Technologist, Digital Content Executive (all now added to `searches.csv`). 235 unique
  cards → precheck: 1 keep (a senior/experienced-only compliance contract role, off-
  profile despite the bare Tier-C title match), 0 review, 234 drop (149 "title not in
  target-roles.md tiers" — i.e. genuinely off-profile noise the keyword pulled in
  because search matches on description/company text not just title, 55 seniority-
  flagged, 23 in-batch agency-repost duplicates).
- 26 `jobBase=REMOTE` UK-wide families, 1 page each (pre-bug-fix, so genuinely remote):
  302 unique cards combined with the London set → precheck: 6 keep (3 Field Service
  Engineer — screened out, applicant has no full driving licence per
  `applicant-profile.md`; 1 Lloyds Banking Group SRE — Workday, see below; 1 Regulatory
  Compliance Analyst dup; 1 NM Software Solutions Business Analyst — genuinely new,
  Shape B, logged as pending-OTP not Blocked since it was found same-session as the
  already-known Blocked rows).
- 10 deep-paginated ORIGINAL Tier A families at 8 pages each (UX/Product/Content
  Designer, Business Analyst, DevOps Engineer, IT Support Technician, User Researcher,
  Web Developer, Service Desk Analyst, Digital Officer) — 510 unique cards, i.e. real
  additional volume exists deeper in the result list beyond the original 3-4 page
  passes. precheck: 2 keep + 2 review, ALL four resolved as non-convertible: a BMS
  (Building Management Systems) Design Engineer — an industrial/HVAC role that slipped
  the `check_title` "Design Engineer" industrial-modifier guard (BMS isn't yet in
  `_DESIGN_ENG_INDUSTRIAL`, flag for a future guard update, not fixed here since a
  single manual override was cheaper than a code change for one instance); a Platform
  Engineer contract role, hybrid-onsite Swindon for an IBM banking client — off-location
  (no relocation) and off-profile ("experienced" contractor, IR35); the Regulatory
  Compliance Analyst dup again; and the KNOWN "No10 Digital Business Analyst" Civil
  Service cross-post the module docstring already warns about (confirmed still
  correctly `Skipped` in the tracker from its CSJ sourcing — not re-driven).
- Re-ran the REMOTE sweep (17 families, 3 pages, POST-pagination-fix) to get a clean
  remote-only read: 123 unique cards → precheck: 2 keep, both already accounted for
  above (the NM Software BA dup + one more Field Service Engineer, skipped same reason).

**Total: ~935 unique cards screened across London + remote + deep pagination this
sweep, yielding exactly ONE genuinely new convertible-track candidate (NM Software
Solutions Business Analyst, Shape B — gated on the same One Login session as the
pre-existing Blocked rows) and one Workday-class-gap Blocked row (Lloyds SRE).**
Everything else was off-profile noise, seniority, duplicates, or a real applicant-
profile screen (driving/relocation). This is honest evidence the Shape A external-
redirect pool for this board, at this point in the day, really is close to exhausted
for the applicant's on-profile families — not a sourcing-technique gap. **The single
lever left with real remaining payoff is the GOV.UK One Login session** (Shape B):
once live it should surface/unblock the 2 pre-existing Blocked rows
(`E-Wealth Alternatives` Social Media & Content Executive, `NM Software Solutions`
Cloud Engineer) plus this run's new NM Software Solutions Business Analyst find.

**Confirmed Workday IS reachable from this board (Lloyds Banking Group, Site
Reliability Engineer, `jobs/6a7f57ac0e0eda050e276452`)** — Shape A redirects through
`aplitrak.com` to `lbg.wd3.myworkdayjobs.com` (a `broadbean_external` Workday tenant).
Logged straight to `Blocked` citing the documented class-level capability gap
(`references/workday-resume-upload-unbindable.md` — hidden `file-upload-input-ref`
input never binds a real file) rather than burning a live attempt on a wall that's
already fully diagnosed elsewhere — consistent with the PRIOR-ART GATE.

Also useful: this ATS's 7-step wizard (Create Account skipped if already logged in) —
Eligibility → General Information → Success Profile → Equality and Diversity →
Declaration — supports genuine account reuse across different MoJ postings on the
SAME `jobs.justice.gov.uk` domain (log in with the existing `ats-credentials.csv` row
instead of registering fresh when you hit "email already in use"). The Success Profile
step on name-blind postings requires an actually-name-blind CV (no name/contact/
institution in the file) — generate one with `reportlab` rather than reusing a normal
CV, since the "I have removed personal details that could identify me" checkbox is a
real declaration, not a formality.

## DANGER: dismissing an informational modal can silently WITHDRAW an application
(Webrecruit-family `careers.battersea.org.uk`, 2026-08-28)

On a Webrecruit-family portal (verified: Battersea Dogs & Cats Home's careers site), an
"anonymised shortlisting" Notice modal appeared mid-application with only a bare `×`
close icon visible in a quick DOM scan. Clicking that `×` did NOT just dismiss the
modal — the site interpreted it as **declining to provide personal data**, and the
whole application was silently terminated: the page changed to "Thank you for your
interest. We appreciate and acknowledge your right to withhold sensitive personal
data, but unfortunately cannot proceed with the application." No confirmation dialog,
no undo. Had to re-open the vacancy's `ApplyNow` link and redo the entire multi-page
form from scratch. **Lesson: before clicking ANY `×`/close control on an unexpected
modal mid-application, read what the modal actually says and look for the REAL
intended dismiss action (often a separate "Ok"/"Continue"/"I understand" control) —
a generic close icon on a consent-flavoured notice is not always a no-op.**

## Sourcing notes (2026-08-28 broad keyword sweep)

`searches.csv` grew from 7 to 37 `govukjobs` keyword rows this run (every Tier A/B family
from `references/target-roles.md` not yet seeded — Interaction Designer, User Researcher,
UX Researcher, Visual/Digital/Web Designer, SRE, Platform Engineer, Infrastructure
Support, Linux Administrator, SOC Analyst, IT Support Technician, Desktop Support,
Service Desk Analyst, Application Support Analyst, 1st Line Support, Digital Officer,
Digital Content Officer, Web Editor, QA Tester, Accessibility Specialist, Frontend/Web/
WordPress Developer, Growth Designer, Content Creator, Digital Content Producer, Cloud
Support Engineer, Network Technician, Multimedia Designer). Each `--pages 4` query
returns 25-40 fresh cards on a board this size — the on-profile pool here is much larger
than the original 7-keyword seed suggested. **Cross-board dedup gap confirmed live:** a
card whose `company` field is the recruiting AGENCY/ATS name (e.g. "Web Recruit Ltd",
"inploi") rather than the real employer will NOT be caught by a Company+Role tracker
cross-check against an already-applied row logged under the real employer name (e.g. The
Institution of Structural Engineers, applied earlier via totaljobs.com under its own
name) — the GOV.UK card and the totaljobs card describe the SAME vacancy but the
pre-drive dedup only compares surface company strings. Real fix would need URL-target
resolution (following the Shape A redirect) before the dedup check, not just the search
card's `company` field — flagged as a gap, not yet fixed in `feed.py`/`precheck.py`.
Also confirmed: a "Downham"/other-name London postcode (e.g. `EC3A 7JB`) IS genuinely
City of London despite the odd place-name prefix some agency listings use — check the
postcode district, not just the word before it, before screening out on location.

## `jobtrain.co.uk` (multi-tenant Civil Service / public-sector ATS — verified via
`justicedigital` tenant, 2026-08-28)

Real, drivable Shape A pattern, but has TWO sharp edges worth knowing before starting:

1. **Every file-upload event on this site WIPES every other in-progress field on the
   current tab** (all radios revert to unchecked, all text/select fields the user just
   set go blank) — confirmed repeatedly: filling ~18 fields, then uploading a CV,
   silently reset all 18 back to empty/unanswered, with NO visible error. The fix:
   **upload every file FIRST** (CV, cover letter, etc. — nothing else on that tab), THEN
   fill every other field on that tab in one pass, and never touch a file input again
   after that. The uploaded file itself is NOT lost by other fields' `input`/`change`
   events — only an upload event resets the DOM's OTHER fields.
2. **Different upload widgets on the SAME application accept different file types** —
   the CV widget under "About You" accepted a plain `.pdf`, but the separate "Statement
   of Suitability" / cover-letter widget under "Supporting information" rejected `.txt`
   outright ("Oops! Supported file types: .doc, .docx, .pdf, .xlsx, .xls") with NO
   visible error until you dispatch a `change` event on the input by hand (setting
   `.files` alone via the `/upload` REST endpoint does NOT surface the site's own
   validation banner — you have to `el.dispatchEvent(new Event('change',{bubbles:true}))`
   to see it). Fix: **converted the plain-text cover letter to a real PDF** in-process
   with `reportlab` (monkey-patch `hashlib.md5` to drop the `usedforsecurity` kwarg first
   — this host's Python/OpenSSL combo throws `TypeError: 'usedforsecurity' is an invalid
   keyword argument for openssl_md5()` on reportlab's default import path otherwise) and
   uploaded that instead. Always assume `.txt`/`.rtf` might be rejected on ANY upload
   widget on this ATS family and check for a rejection banner, don't just trust a
   silent-looking DOM `files.length===1`.

Also useful: registration is `RegisterNoPassword1` (first/last name only) ->
`DecideInternalExternal` ("I don't work here" for external candidates) -> email+mobile+
T&Cs -> a 2-question eligibility gate (Civil Service Nationality Rules Yes/No, then a
per-role SC/DV clearance eligibility Yes/No — answer per the applicant's real residency/
vetting-eligibility facts, not whether they currently hold clearance) -> a 4-tab wizard
(About You / Supporting information / Equal opportunities / Review and submit, each
showing a green check only once genuinely complete) -> a final "create a password to
track your application" step AFTER clicking Submit, which is the point the application
actually posts (verified: URL lands on `/Application/ThankYou`). Radio/select `name`
attributes are template-generated and get reused across DIFFERENT questions further down
the same page (e.g. `equality_sexual_orientation` was actually the gender-identity select
on one page and a Yes/No disability-scheme select on another) — always confirm by reading
each `<option>` list and the visible label text, never assume the `name` attribute means
what it says.
