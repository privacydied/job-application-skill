# Adzuna — the one canonical board that unblocks "100 more" when LinkedIn is off

`pipeline.py`'s `FEEDS` dict is the FULL canonical board set for this skill. It is exactly
**six** boards: `{ indeed, wttj, csj, hackney, adzuna, reed }`. (Confirmed 2026-07-15 by
reading `sites/_common/scripts/pipeline.py` — there is no 7th board.)

When a "LinkedIn off, do 100 more" run stalls at a data-scarcity ceiling on CSJ + Reed,
**Adzuna is the board most likely to actually hold the remaining inventory** — and it is
the one board in the canonical set that was NEVER sourced in the 2026-07-15 pivot runs,
because it was blocked on a missing credential. Capture so the next session tries it FIRST.

## Why Adzuna is the real unlock
Adzuna is a **free JSON API aggregating ALL UK jobs** (LinkedIn / Indeed / CSJ / Reed +
every employer ATS). No browser, no Cloudflare, no anti-bot on the API. A single
`--what "UX Designer" --where London` query returns 50 structured postings per page.
If the API key is present, `sites/adzuna.co.uk/scripts/feed.py` can surface 50-100+
on-profile junior-mid UX/Service/Product Designer + UR + BA roles across the whole market
in one pass — far beyond the per-board scarcity that stalls CSJ/Reed.

## The credential trap (verified 2026-07-15)
- `ats-credentials.csv` row `adzuna.co.uk` = `you@example.com` / `[REDACTED — see ats-credentials.csv]`.
  **This is the Adzuna WEBSITE login password, NOT the API key.** It is documented as
  "current, working" for the website ApplyIQ flow in `sites/adzuna.co.uk/NOTES.md`.
- `feed.py` needs **TWO distinct env vars**: `ADZUNA_APP_ID` + `ADZUNA_APP_KEY`, obtained
  from a free https://developer.adzuna.com signup (60 seconds, no card). The website
  password does NOT satisfy the API auth — using it as `app_id` returns `AUTH_FAIL`.
- **Adzuna's website is PARTIALLY drivable (verified 2026-07-15, corrected).** Direct nav to a
  search URL bounces back to the homepage (cookie-consent overlay, no results) — anti-bot
  blocks URL-nav. BUT the **search FORM works**: accept/decline cookies, type the keyword
  into the job field + location into the location field, click the green Search button to
  land on a real results page (thousands of UX Designer Jobs in London). Use this as a
  fallback when the API key is unavailable. Caveat: result cards link OUT to employer ATS
  (CVLibrary/TotalJobs/Indeed) which are themselves walled, and the DOM is wedge-prone
  (modals + anti-bot) — so the **JSON API remains the reliable, bulk path**. Do NOT rely on
  the website for harvesting; get the API key.

  **Website detail-URL extraction (verified 2026-07-15):** the visible result-card hrefs are
  anchor-less search/salary-filter URLs, NOT posting URLs — so filtering on those is useless.
  The REAL posting URLs are `https://www.adzuna.co.uk/jobs/details/<id>` — extract them with
  `a.href.match(/adzuna\.co\.uk\/jobs\/details\/\d+/)` AFTER scrolling the results page a few
  times to lazy-load cards. Each detail page has an Apply-for-this-job button that redirects
  via `/jobs/land/ad/<id>` to the employer's ATS. For UX/design roles the redirect lands on
  CVLibrary (cv-library.co.uk) — an agency board, NOT an employer ATS (verified: a UX Designer
  detail redirected to a cv-library.co.uk/job/... URL). So Adzuna's UX inventory is largely
  CVLibrary agency reposts, which are themselves account-gated (see cv-library-board.md).
  Treat the website as a discovery path, not a submission path.


## Action for the next "LinkedIn off" session
1. Check `echo $ADZUNA_APP_ID` / `echo $ADZUNA_APP_KEY`. If unset → this is THE unblock.
2. Ask the user for the Adzuna API key (free at developer.adzuna.com) OR generate one.
3. `export ADZUNA_APP_ID=... ADZUNA_APP_KEY=...` then
   `python3 sites/adzuna.co.uk/scripts/feed.py --what "UX Designer" --where London --pages 3`
   → pipe to `precheck.py` → `jd.py --nav-batch` → apply via each posting's ATS link.
4. Adzuna postings link OUT to employer ATS (Greenhouse/Workday/etc.) — apply there via
   `atsform.py` / the per-ATS drivers, same as The Dots. Expect some dead-advert rot
   (verify JD liveness before tailoring — see `indeed-exhaustion-and-dead-adverts.md`).

## Reality check
Adzuna is the only canonical board with enough inventory to approach a 100-target when
LinkedIn is rate-limited. The other four non-LinkedIn canonical boards (csj, reed, indeed,
hackney) + WTTJ are either exhausted, Cloudflare-walled, 0-on-profile, or creds-gated. If
Adzuna's API key is also unavailable, the remaining gap is genuinely unreachable without
LinkedIn (limit lifts) or WTTJ creds — state the ceiling once, don't fabricate.
