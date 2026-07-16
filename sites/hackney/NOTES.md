# recruitment.hackney.gov.uk — verified quirks & recipes

London Borough of Hackney careers site ("Find Yourself in Hackney"). Forked from the
Civil Service Jobs flow 2026-07-14 — same feed pattern, MUCH simpler platform.
All findings verified live 2026-07-14.

## Platform map

- **Sourcing**: plain server-rendered **WordPress** at `recruitment.hackney.gov.uk`.
  Guest-browsable. **No login, no SID sessions, NO CAPTCHA observed** (if one ever
  appears here it is NOT covered by any auto-solve sanction — hard stop per SKILL.md;
  the ALTCHA exception is CSJ-only).
- **Applying**: "Apply Now" on a vacancy page → **Lumesse TalentLink**
  (`https://emea3.recruitmentplatform.com/apply-app/pages/application-form?jobId=…`)
  — an external ATS, **automated via `sites/recruitmentplatform/scripts/talentlink.py`**
  (see `sites/recruitmentplatform/NOTES.md`). Hackney is the single-PAGE
  variant: one `talentlink.py apply <cfg> --submit` fills every section and submits.
  LIVE-BROWSER-TESTED 2026-07-14: Help Desk Operative submitted end-to-end
  (confirmation "we have received your application"). The `…-anonymous-apps`
  taxonomy on every card means Hackney runs **anonymised applications** — expect the
  ATS to separate identifying fields from the assessed application; answer normally.

## URLs / ids

- Stable canonical vacancy URL (log THIS in the tracker):
  `https://recruitment.hackney.gov.uk/vacancy/<slug>/`
- Search: `https://recruitment.hackney.gov.uk/job-search/` (+ optional
  `?directorate=<slug>` filter); pagination `…/job-search/page/N/` (past the last
  page WP serves a not-found template — the feed stops on it / on zero new cards).
- WP post id (`article#post-24457`) is a secondary id; the slug is the dedup key.

## Card quirks

- **Duplicate `class` attribute on `<article>`** — the card carries TWO class
  attributes (`class="media mt-2 mb-5" id="post-…" class="post-… vacancy
  directorate-… service-… organisation-…"`). Browsers DROP the second attribute at
  parse time, so the directorate/service/organisation taxonomy is **unreachable from
  the DOM** (empty in feed output). Don't chase it via `classList`; if it's ever
  needed, fetch the raw HTML. Company is therefore fixed "Hackney Council" (accurate
  for this board).
- Salary + closing date share one bold line: `£37,509 to £41,637 – Closing date:
  2 August` (no year — closing dates are near-term; treat ambiguity as this year).
- Small board: ~15–20 live vacancies total; the feed sources ALL of them (fixed
  cooldown key `hackney`/`all`) and precheck does the screening. Yield check
  2026-07-14: 17 fresh → 1 genuine Tier-A keep (Associate Content Designer).

## Page quirks

- **Cookie dialog owns the page's first `<h1>`** ("This site uses cookies…") — it
  broke naive h1 extraction (jd.py now prefers the main-content heading; anything
  else reading headings here should scope to the content block, not document-first).
  The dialog did NOT intercept card-link navigation in testing (unlike CSJ's banner).
