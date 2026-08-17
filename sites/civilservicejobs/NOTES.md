# civilservicejobs.service.gov.uk — verified quirks & recipes

GOV.UK central vacancy board (Civil Service Jobs, "CSJ"). Guest-browsable for search +
job adverts; applying needs a CSJ account (or an external ATS — per posting, see below).
All findings below verified live 2026-07-13/14.

## ALTCHA gate — AUTO-SOLVE (sanctioned, THIS SITE ONLY)

Fresh sessions hit a "Quick check needed" interstitial with an **ALTCHA** checkbox
(`input[type=checkbox][id^=altcha]`, altcha.org — client-side proof-of-work; NOT
Google reCAPTCHA, NOT Turnstile; no iframes, no puzzle) + a Continue button that
POSTs back to the SAME URL (so URL-diffing click verifiers report `no_change` —
wait on `document.title` changing instead).

**User-sanctioned standing exception (2026-07-13): auto-tick + Continue on CSJ
only** — implemented as `solve_altcha()` in `scripts/feed.py` (call it after ANY
navigation that might land on the gate, including pagination and the apply flow).
Scope is exactly ALTCHA×CSJ: ALTCHA on another site, or any other CAPTCHA here,
stays a full hard stop per SKILL.md. Solve mechanics: trusted click the checkbox →
poll `checked === true` (PoW verifies in ≲5s; hidden input gets a ~520-char
payload) → JS-click Continue → poll title.

## SID links are ONE-SHOT and session-bound — use jobs.cgi?jcode= instead

Every on-site link is `index.cgi?SID=<base64(query params + reqsig signature)>`.
Verified failure modes:
- a card href `fetch()`ed then navigated (or used twice) → **"Cannot view job"**;
- a hand-constructed SID without a valid `reqsig` → generic 15KB bounce page;
- the search-context SID itself carries a timestamped `reqsig` → it EXPIRES.
  When the feed reports "not on a CSJ results page", regenerate: open the site,
  run the search again (London, radius 10mi), copy the results-page URL into the
  `csj` row of `searches.csv`.

**The stable, session-independent URL** (verified to navigate directly, works with
`jd.py --nav`, survives sessions — it's what CSJ's own share links use):

    https://www.civilservicejobs.service.gov.uk/csr/jobs.cgi?jcode=<vacid>

`<vacid>` = `joblist_view_vac=NNNNNNN` inside the card link's decoded SID. Log ONLY
jcode URLs in the tracker; never an `index.cgi?SID=…` URL (undedupable, expires).

## Sourcing — scripts/feed.py

```bash
python3 sites/civilservicejobs/scripts/feed.py --nav "<searches.csv csj nav URL>" --all-pages
# (--all-pages crawls the whole ~17-page result set; --pages N bounds it for a quick peek)
```
- Emits `{id, url(jobs.cgi?jcode), title, company(=department), location, salary,
  closes, ref, eligibility}` — pipe straight to `precheck.py -`.
- Handles ALTCHA, pagination ("next »"), tracker dedup (`jcode=`/`joblist_view_vac=`
  regex), board cooldown (BOARD `csj`, fixed QUERY `london-search` — keep in sync
  with searches.csv), stagetimer `source`.
- Results page is LIVE — counts change mid-session as postings close (saw 451→412
  in minutes; many close 11:55pm same-day). Source and apply in the same run;
  don't sit on a work list overnight.
- Cards list MULTIPLE locations ("Bristol, London, Newcastle-upon-Tyne, York") —
  contains-London = acceptable (precheck already keeps these); the advert's
  location section says which offices, and CSJ roles are typically hybrid (~60%
  office). A bare postcode ("SW1A 1AA") is London — precheck may mark it review.
- **No dismiss/"not interested" control exists** on results cards — SKILL.md step
  10's dismiss step is N/A here; tracker dedup via jcode is the only (and
  sufficient) resurfacing guard.

## Screening quirks

- Titles skew senior/manager-heavy; grade fields on the advert (AA/AO/EO/HEO/SEO/
  G7/G6/SCS) are the real seniority signal: EO/HEO ≈ junior-mid (target), SEO ≈
  mid (case-by-case), G7+ = senior (skip). The card doesn't show grade — it's in
  the advert's "Job grade" row (jd.py captures it in jd_text).
- London salary bands are often listed separately ("£43,760 (National) /
  £47,670 (London)") — use the London figure.
- **Nationality/vetting are REAL hard screens here**: most posts require specific
  nationality rules (UK national/settled status — Jane: British citizen, fine)
  but SC/DV clearance posts (MI5, NCA, etc.) need sustained UK residency history
  and are worth skipping if the advert demands existing clearance.
- Adverts include an **"Artificial intelligence" section** stating the
  department's AI-use policy for applications. Read it per posting; the skill's
  standing rule (write everything as Jane, from Jane's real experience, never
  state the application was AI-written) already complies with "AI as assistance"
  policies — a posting that outright forbids any AI involvement is a per-posting
  judgment to surface to the user, not silently ignore.

## Applying

Two mechanisms, per posting (both visible on the advert page):
1. **"Apply at advertiser's site"** → external ATS (seen: app.beapplied.com) —
   normal external-ATS flow, `atsform.py apply` etc.
2. **"Apply and further information"** → CSJ's own application flow — needs a CSJ
   account (email/password signup with you@example.com per the standing ATS-account
   rule; record in `ats-credentials.csv`). Civil-service applications are
   Success-Profiles based: personal statement (word-capped), behaviour statements,
   sometimes CV upload. This signs you into `cshr.tal.net` = **Lumesse TalentLink**,
   the same engine as Hackney — so DON'T build a driver from scratch: start from
   `sites/recruitmentplatform/scripts/talentlink.py` (see its NOTES). Caveat: that
   adapter was built + live-verified on Hackney's SINGLE-page form; CSJ is MULTI-page
   (Your CV → Personal statement → Preferences → Declaration), so the first CSJ run
   should confirm/extend it for the per-page advance flow rather than assume it works
   end-to-end.

**Apply-time dedup (do NOT skip):** the eform runs on a `cshr.tal.net/.../eform/<ID>` URL that
carries NO jcode, but the tracker keys CSJ on `jobs.cgi?jcode=<id>` — so the eform driver can't
dedup on its own. When you drive **`tal_eform.py` (S1), `tal_sec2.py` (S2 — the FINAL submit), or
`tal_eform_mon.py`**, **ALWAYS pass the jcode you sourced**:

```bash
python3 tal_eform.py <eform_base> <spec.json> --submit --jcode <id> --company "<dept>" --role "<title>"
python3 tal_sec2.py  <eform_base> <spec_s2.json>  --jcode <id>          # S2 = the completing submit
```

(or embed `jcode`/`url`/`company`/`role` in the spec JSON — the drivers read either). Each then
guards via the shared `tal_eform.csj_dedup_guard` → `precheck.guard` and refuses to re-drive a
vacancy already Applied. Omit it and dedup is SKIPPED (the driver WARNs to stderr) — that is
exactly the gap that let jcode 2005473 be Applied twice. `tal_sec2.py --force` overrides the guard,
for the one legitimate case: a row mis-logged `Applied` after S1 while S2 is genuinely pending.

## Misc

- Cookie banner ("additional cookies") can overlay and eat trusted clicks on the
  results page — dismiss it first (feed nav path usually renders without it after
  ALTCHA; the banner appeared after a Continue POST). A JS `.click()` on the
  banner's accept/hide button is fine (it's a consent banner, not a wall).
- `board_cooldown.query_from_url()` can't extract a query from SID URLs — the feed
  uses the fixed key `london-search` (same pattern as WTTJ's `home`).

## Section 2 end-to-end — VERIFIED 2026-08-15 (ONS Content Designer, "Application received")

Section 1 and Section 2 are **separate eforms**. Submitting S1 does NOT open S2 in place:
the S1 eform locks ("submitted and can not be edited") and its `/page/N` URLs then redirect
to the Applications list. Reach S2 via the Applications centre:
`.../candidate/application/<APP_ID>` → **"Continue application"**.

S2 pages: **Your CV → Personal statement → Preferences → Declaration.**

Three things cost a full cycle and are not obvious:

1. **`/save_page` in the URL does NOT mean submitted.** After walking the pages the URL
   becomes `.../eform/<ID>/save_page` with only a "Back" button, which reads like a finished
   submission. It isn't. The **authoritative** signal is the Applications list status:
   `Application started` = NOT submitted · `Application received` = submitted.
   Always confirm there before logging `Applied`.

2. **An unfilled Preferences page silently blocks the submit.** "Select your preferred
   location" (`datafield_53467_1_1`, e.g. London / Home Working / Manchester) errors on that
   page but the walker still advances to Declaration — so the Declaration looks reachable
   while the form can never submit. Fill Preferences BEFORE the Declaration.

3. **The Submit button does not exist until the gate is set** (as SKILL.md says, but the
   ordering matters): tick the declaration checkbox (`datafield_205967_1_1`) AND set the
   "Full Application Form Submitted?" select (`datafield_76575_1_1`) to **Yes** — only then
   does `<input type=submit value="Submit">` render. Before that, enumerating buttons returns
   only cookie-banner controls and "Back", which looks like a structural wall and is not one.

**Name-blind recruitment:** the CV and personal statement pages each carry their own
"I have removed all personal information" checkbox and BOTH must be ticked. Strip name,
educational institutions, age, gender, email, address, phone, nationality. Employers may
stay — only *educational institutions* are named in the strip list — but describing an
employer generically ("a music technology startup") is safer and reads fine.

**AI policy (important, and DIFFERENT from Canonical's):** Civil Service adverts say
"Artificial intelligence can be a useful tool to support your application, however, all
examples and statements provided must be truthful, factually accurate and taken directly from
your own experience." So AI-assisted drafting of the applicant's REAL experience is
explicitly permitted — what is forbidden is presenting invented or borrowed examples as his
own. That is a *lower* bar than Canonical's outright ban, and CSJ must NOT be lumped in with
it. Draft only from `references/applicant-profile.md`; never invent a STAR anecdote.

### ✅ SOLVED: "the Submit button never renders" = a SECOND required CV textarea is empty

**Root cause (2026-08-15): the "Your CV" page has TWO required textareas, not one.**

  `datafield_99856_1_1` — "Provide your employment history details"
  `datafield_99863_1_1` — **"Provide details of your previous skills and experience"**

Fill only the first and the page still advances on Continue, every later page fills
normally, and the Declaration renders **only "Back"** — no Submit, forever. Tick the
declaration checkbox and set "Full Application Form Submitted?"=Yes and *still* no Submit,
because TAL renders it server-side only when every prior page is complete. Fill
`datafield_99863_1_1` and Submit appears immediately. Verified by fixing exactly that on two
stuck applications, both of which then submitted to "Application received":
DfE Digital Content Producer (ref 475477) and GDS Interaction Designer (ref 473690).

**I first mis-diagnosed this** as "forms with a Role specific questions page can't submit",
because the one form that DID submit (ONS Content Designer) happened to lack both that page
and the second textarea. That correlation was a coincidence. The role-specific page is
irrelevant. Recording the wrong diagnosis here cost a cycle; the lesson is that the
"There is a problem" banner naming the missing field is on the **CV page**, not on the
Declaration where the symptom appears — so when Submit is missing, go back and re-read every
earlier page's banner rather than theorising about the Declaration.

**Finding it:** the Continue-walker does not necessarily land on every page. Enumerate pages
directly — `.../eform/<ID>/page/1..N` — and read each one's error banner. On the DfE form the
incomplete CV page was `page/6`, *after* the Declaration at `page/5`, so walking forward from
page 1 never revisited it.

**Checklist before expecting Submit on any CSJ Section 2:**
1. BOTH CV textareas filled (`99856` employment history, `99863` skills/experience).
2. Personal statement filled.
3. Preferences — every select set (an unset preferred location silently blocks submit too).
4. Role-specific questions answered, if the form has them.
5. Then declaration checkbox + "Full Application Form Submitted?"=Yes → Submit renders.
6. Confirm via the Applications list: **"Application received"** is the only proof.

### Recurring blocker: a required FREE-TEXT work-location field on Preferences (DSIT pattern)

Confirmed twice on DSIT forms (Programme Support Officer, Portfolio Analyst): Preferences
carries BOTH a location dropdown AND a separate required free-text input
`datafield_74443_1_1` — "Your first choice of work location". Setting only the dropdown
leaves the text field empty, the page still advances on Continue, and the Declaration then
renders no Submit. The error banner reads "There is a problem — Blocker field. - This field
is required — Your first choice of work location", and it is on the PREFERENCES page, not the
Declaration where the symptom appears.

Fill every empty `input[type=text]` on Preferences (London here) as well as every empty
select. Both applications submitted immediately afterwards.

This is the second distinct instance of the same general rule, so treat it as the rule:
**when Submit does not render, enumerate `.../eform/<ID>/page/1..N` and read each page's
"There is a problem" banner.** Do not theorise about the declaration gate — in every case so
far the gate was already correct and an earlier page was quietly incomplete.

## Route classification FIRST — most CSJ adverts are not drivable (2026-08-16)

`scripts/classify_route.py` splits a feed's cards into `tal` / `external` / `closed` before
any of them costs a tailoring pass. This matters because a CSJ Section 2 is 30+ minutes of
bespoke writing, and discovering "this one hands off to the department's own ATS" AFTER
writing it is the expensive way to find out.

Measured over 19 vacancies sourced across his role families (service/interaction design, user
research, content design, business analysis, devops, SRE):

| | count |
|---|---|
| in-platform TAL eform (drivable) | 9 |
| "Apply at advertiser's site" → department ATS, needs an account | 9 |
| closed / unknown | 1 |
| **TAL *and* on-band (EO/HEO/SEO)** | **2** |

Seven of the nine drivable ones were **Grade 6/7**, i.e. senior — off-band per the grade rule
above. So the drivable-and-on-band CSJ set is far smaller than the raw card count suggests
(883 cards sourced in one pass). Classify, then filter by GRADE, then write.

⚠️ Two classifier traps, both of which UNDER-report the drivable set:
1. **The apply block is inside a COLLAPSED "Apply and further information" section**, so its
   button text is absent from `document.body.innerText`. Matching on innerText alone reported
   1/19 drivable; querying the DOM for an `Apply now` control reported the true 9/19. Use the
   DOM for the control, innerText for the "advertiser's site" prose.
2. `goto()` returns before CSJ renders the apply block — poll for a marker before reading.

## ✅ SOLVED 2026-08-17 — HMRC "Desirable experience and skills" was a HIDDEN CONDITIONAL FIELD

**The section below is superseded. HMRC CSJ vacancies are drivable.** Verified end to end on
the re-advertised Senior Business Analyst (jcode 2009725, ref 476852, eform 57897164).

`datafield_50629_1_1` is **owned by a Yes/No radio, `datafield_50626_1_1`** ("Do you have the
relevant experience and skills as outlined above?"). Until that radio is set, the textarea is
rendered with **`offsetParent === null` — it is HIDDEN** — and the server discards anything
typed into it. That is the whole mechanism:

```
before: input[name=datafield_50626_1_1] (radio Yes/No)  -> UNSET
        textarea[name=datafield_50629_1_1]              -> required=true, visible=FALSE
set the radio to Yes  ->  textarea visible=TRUE
fill it               ->  reads back 1575 chars
Continue, navigate away, come back  ->  radio still Yes, textarea STILL 1575 chars
```

The old spec set the textarea and never set the radio, so every attempt typed into a hidden
control. The prior diagnosis ("the value LANDS then is dropped — look at the POST body")
had the mechanism right and simply never found the cause. It is not HMRC-wide platform
behaviour and it is not a persistence bug: it is one missing spec key.

**Fix in the spec, not the driver:** include `"radio": {"datafield_50626_1_1": "Yes"}` (or
`"No"`) alongside the textarea. Generally — **on any CSJ page, set radios/selects BEFORE the
text they control, and treat `offsetParent === null` on a required field as "its owner is
unset", never as "the field is broken."** `tal_eform.walk()` now also runs a top-up pass that
re-asserts any spec text/textarea reading back empty after the owning controls settle.

⚠️ Truthfulness note for this specific question: the four desirable criteria are a mixed bag
for this applicant (has data analysis/visualisation and Agile; has NOT customs/trade
regulations or line management). Desirable criteria are not pass/fail and the field is a
250-word details box, so the honest construction is Yes **with the details box stating exactly
which are met and which are not** — never a bare Yes implying all four.

---

## ⛔ SUPERSEDED (2026-08-16 diagnosis) — HMRC "Desirable experience and skills" will not accept input

Confirmed on TWO separate HMRC vacancies (Senior Business Analyst 2009576, Senior Test
Engineer 2008608), so it is HMRC-form-wide, not posting-specific. The textarea reports
`disabled=false`, `readOnly=false`, and sits inside the normal form next to `continue_button`.

**⚠️ DIAGNOSIS CORRECTED 2026-08-16 — it is a PERSISTENCE failure, not an input failure.**
Re-tested on a fresh eform (57875389, the same 2009576 vacancy) after an engine restart:

  * React native value-setter + `input`/`change`/`blur` → **`value.length` reads back 4**.
    The value LANDS. The original note said it read back 0; that was almost certainly a
    symptom of the wedged engine that session, not of the field.
  * Click `continue_button`, then re-open `/page/1` → **`value.length` is 0 again.**

So the value is accepted client-side and then dropped: either the POST omits this field or the
server discards it. That changes what is worth trying. The old note points at INPUT METHOD, so
the natural next step was a fourth way of typing — which cannot work, because typing already
works. Anyone picking this up should look at the POST body (is `datafield_50629_1_1` in it?)
and at whether the field belongs to a different form/section than `continue_button` submits.

Net effect at the time: Submit never rendered. **That conclusion is now WRONG — see the
SOLVED section above; the cause was the unset owning radio, and HMRC vacancies drive fine.**
Continue still POSTs, so the walk advances, but the Declaration page keeps listing that page
under "problems that need to be fixed" and **Submit never renders**. Everything else on those
forms persisted normally. CPS (2009637) and FCDO (2007055) submitted cleanly through the same
driver on the same day, so the driver is fine. Hand HMRC vacancies to the user in noVNC.
