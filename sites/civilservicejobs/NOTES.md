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

### ⚠️ OPEN BUG: forms WITH a "Role specific questions" page never render Submit

Verified 2026-08-15 across three applications on the same account, same session, same spec:

| Application | Has "Role specific questions"? | Result |
|---|---|---|
| ONS — Content Designer | **no** | ✅ submitted, "Application received" |
| GDS — Interaction Designer | **yes** | ⛔ Submit never renders |
| DfE — Digital Content Producer | **yes** | ⛔ Submit never renders |

In all three the Declaration state was identical and correct: declaration checkbox ticked
(`datafield_205967_1_1`) and `datafield_76575_1_1` set to the option whose text is exactly
"Yes" (verified by reading `.value` back). On ONS the `<input type=submit value="Submit">`
appeared within seconds; on the other two, enumerating every `input[type=submit]`/`button`
returns only the cookie-banner controls and "Back", indefinitely — including after
re-dispatching `change` with the native setter and waiting ~20s.

So the blocker correlates with the extra page, NOT with the declaration gate. Working
hypothesis (UNPROVEN — do not treat as fact): the role-specific answers are being written
with the React native-setter + `input`/`change` and the page ADVANCES past its "Enter your
response…" error, but the server may still consider that page incomplete, and the Declaration
renders Submit only when every prior page is complete server-side.

**Next thing to try** (cheapest first): fill the role-specific textareas with REAL keystrokes
(`POST /tabs/<tab>/type` with `mode:"keyboard"`) instead of a native-setter write, click
Continue, then re-open the Declaration. If that renders Submit, the rule is "TAL persists
only genuinely-typed input on this page" and `tal_eform.py`/`tal_sec2.py` should use keystrokes
for role-specific pages. Both affected applications are filled and saved, so this can be
tested without redoing any content.
