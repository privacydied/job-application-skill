# UK Parliament — `hrhoc.parliament.uk` / `hrhol.parliament.uk` (MHR Web Recruitment)

Parliament recruits on **MHR Web Recruitment (iTrent)**. Not Oleeo, not Hireserve, and not
`workforus.parliament.uk` — that host is **NXDOMAIN**, as is `careers.parliament.uk`. The
canonical human entry point is `parliament.uk/about/working/jobs/`, which fans out to three
separate boards.

## Three boards, one app, three WVIDs

`ETREC179GF` is the search app; the `WVID` ("web view id") selects the employer stream.
Lords is on a **different host and instance path** (`hrhol` / `ce0913li`) — not just a
different WVID.

| stream | host + path | WVID |
|---|---|---|
| **pds** | `hrhoc.parliament.uk/ce0912li_webrecruitment` | `6744175kYE` |
| **commons** | `hrhoc.parliament.uk/ce0912li_webrecruitment` | `3402965kYE` |
| **lords** | `hrhol.parliament.uk/ce0913li_webrecruitment` | `7744073cYW` |

**PDS = Parliamentary Digital Service** — Parliament's in-house design/UX/engineering arm,
and the on-profile stream (§1/§3/§12). It is also the smallest: **a PDS pass returning 0 is
normal**, not a broken feed. Check `commons` before concluding anything is wrong (measured
2026-07-17: pds 0, commons 10, lords 5).

## Sourcing — camofox required

```bash
python3 sites/parliament.uk/scripts/feed.py --list-tenants          # no browser
CFX_KEY=… python3 sites/parliament.uk/scripts/feed.py               # all 3 streams
CFX_KEY=… python3 sites/parliament.uk/scripts/feed.py --tenant pds --what designer
```

**There is no HTTP route and no JSON endpoint.** Plain GET returns a shell; the vacancy list
is rendered client-side and **fires no XHR at all** (results are computed in-page from
embedded data), so there is nothing to intercept. POSTing the search form — replaying every
signed `%.`-prefixed hidden field and the `USESSION` token — returns a bare "Search for jobs"
page with an empty `.Mhr-jobSearchJobs` container. Rendering is the only route; the feed
exits 2 without `CFX_KEY`.

- Cards: `.Mhr-jobSearchJobs > *`, each with a stable `vac-id`.
- Fields: `.Mhr-jobDetailEntry` label/text pairs → *Apply by*, *Location*, *Salary*, *Basis*.
- **Cards render on load — do NOT click "Find jobs".** That click times out (~30s): it fires
  a re-render Playwright waits on, the documented click-hang pattern. A JS `.click()` fires
  but changes nothing, because no request is made.
- The board's keyword box is client-side, so `--what` filters titles in the feed rather than
  driving its UI.

## Canonical URL

```
<base>/ETREC179GF.open?WVID=<wvid>&VACANCY_ID=<vac-id>
```

Verified to deep-link straight to the job profile, **session-free**.

⚠️ **Do not use the card's `bu-send` attribute.** It points at `ETREC148GF` — the *apply*
screening flow, not the profile — and carries a `USESSION` token that expires. Without the
session it renders "Screening Questions" with no vacancy context; the vacancy title isn't
even on the page.

The job profile opens **in place** (the SPA never changes `location.href`), so there is no
per-vacancy URL to scrape from the DOM — the canonical form above is constructed, not read.

## Apply

Account-gated: MHR candidate account ("Existing user login" / "My applications" /
"My profile"). Sourcing is open; account creation is **NOT a hard stop** (SKILL.md) — an
account row now exists in `ats-credentials.csv` (`parliament.uk (UK Parliament MHR)`).
`ats_hint` is `mhr-webrec`.

### Apply flow (verified live 2026-09-24, PDS Interaction Designer REQ000147)
1. Job profile → **Apply online** → **Screening Questions** (age 18+ / right to work /
   5-year UK residency / current HoC-HoL-JointDept employee — all plain Yes/No radios,
   grouped by `name` matching `DUMMY.<N>-1-1`, answer by group index).
2. **Create an account** (not a hard stop): Title/Forename/Surname/Email/Confirm
   email/Password/Confirm password (`FORENAME1...`/`SURNAME...`/`EMAIL_ADDRESS...` etc. under
   `TUSERUSP.TRENT_SEC.1-1-1`) → submits straight into the application form, logged in.
2. **7-page application form**, all-in-one draft, re-enterable via **My applications → Update**
   any time (survives navigating away — session/tab loss does NOT lose the draft):
   Personal Information → Application Guidance (info only) → CV Upload → Criterion Responses
   → Diversity Monitoring → Other Information → Declaration and Next Steps.
3. **CV Upload**: plain `<input type=file>`, upload via `/upload` with `selector` OR the
   snapshot `ref` of the upload button (both work) — **rename the file to something generic
   first** ("Your document upload should be anonymised... This includes the filename").
   512KB soft limit stated but a 32KB PDF uploaded fine.
4. **Criterion Responses**: exactly 3 free-text boxes (`VALUE.REC_FORM_FLD_SB1.TRENT_REC.2-1-N-1`,
   N=1..3), max 500 words each, generically labelled "Criteria 1/2/3" — **the actual criteria
   text lives ONLY in the Person Specification on the job profile / JD attachment, not on this
   page** — read and note it BEFORE starting the apply flow (a `cfx.ensure_tab`d side-tab risks
   losing session state on this vendor — see the footgun below — so capture the JD text from the
   initial job-profile read, before clicking Apply online).
5. **Diversity Monitoring**: DOB (`VALUE.TREC_FORM_FLD.TRENT_REC.1-2-1`, `dd/mm/yyyy` free text)
   + ~15 selects (national identity / ethnicity / sexual orientation / gender identity / trans /
   gender-same-as-birth-sex / religion / caring / socio-economic-background ×6). Options are
   lettered ("A: British", "L: Mixed - Other Mixed or Multiple ethnic groups") — match by
   substring/includes, not exact text (the letter prefix varies by field).
6. **Other Information**: source ("Where did you see this advertised?"), notice period
   (free text), Armed Forces community Yes/No.
7. **Declaration**: one checkbox ("Declaration consent") + **Next** — no distinct
   "Submit"/"Send application" button anywhere in the DOM (`grep BU_` on the page shows only
   `BU_PREVIOUS`/`BU_UPDATE`/`BU_NEXT` — no `BU_SUBMIT`). Clicking Next here returns to the
   Application Summary page, which is the same page an incomplete draft shows.

### ⚠️ UNRESOLVED — no confirmable "submitted" signal (2026-09-24)
After every one of the 7 sections shows **"Mandatory fields complete"** (readable per-link via
the a11y snapshot title attr, not visible as plain text) and Declaration's Next is clicked, the
**My Applications list still shows the vacancy under "In progress applications" with an "Update"
button** — never a distinct "Submitted"/"Applications you have submitted" section, no
confirmation banner, no confirmation email checked (would need IMAP). The page's own copy
("select the corresponding Update button" to "update **or submit**") suggests Update IS the
single re-entrant action for both editing and submitting, and this vendor may simply not
surface a separate post-submit state — but this is NOT verified. **Logged `Applied?`
(unconfirmed), never `Applied`, per the no-confirmation-no-Applied rule.** Before trusting a
future PDS/Commons/Lords MHR submission as `Applied`, verify via: (a) a confirmation email in
the applicant inbox (`fetch_verification_code.py` can poll for one), or (b) re-opening
"My applications" after some delay to see if the entry ever migrates out of "In progress", or
(c) directly asking the recruitment team's contact address whether an application was received.
Do not re-drive this exact application (re-submitting risks a duplicate); if support confirms
receipt, flip the tracker row to `Applied` with that confirmation as `--proof`.

### Footgun: fresh `cfx.ensure_tab`/side-tab work can silently swap `hrhoc` → `hrhol`
Opening a second tab (e.g. to re-read the JD without losing the application draft) and later
returning to the "same" `CFX_TAB` can land you on `hrhol.parliament.uk` (Lords) instead of the
`hrhoc.parliament.uk` (Commons/PDS) tenant you were on — the two are different hosts/sessions,
and a `cfx.py goto` on a stale/reused tab reference does not guarantee which login session comes
back. **Symptom:** navigating a "known-good" URL suddenly shows "Existing user login" (logged
out) or a Bar-Assistant/House-of-Lords listing instead of your PDS draft. **Fix:** the
in-progress draft itself is NOT lost (My applications → Update recovers it) — just re-login
(email/password from `ats-credentials.csv`) on the correct host and resume from My Applications,
never assume the draft is gone. Avoid opening a side tab mid-application if at all possible;
read the JD/person-specification BEFORE clicking "Apply online" instead.
