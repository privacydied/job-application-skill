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

## Misc

- Cookie banner ("additional cookies") can overlay and eat trusted clicks on the
  results page — dismiss it first (feed nav path usually renders without it after
  ALTCHA; the banner appeared after a Continue POST). A JS `.click()` on the
  banner's accept/hide button is fine (it's a consent banner, not a wall).
- `board_cooldown.query_from_url()` can't extract a query from SID URLs — the feed
  uses the fixed key `london-search` (same pattern as WTTJ's `home`).
