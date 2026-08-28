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
    search. That's `feed.py`'s tracked default (`DEFAULT_LOCATION_TEXT = "London,
    England"`) — kept a bare city name deliberately, NOT a real postcode, so this tracked
    file carries no PII (SKILL.md §12).
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
