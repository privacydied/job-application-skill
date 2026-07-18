# Alternate Boards — Apply-Path Reality (verified 2026-07-15)

The SKILL.md "Also in rotation" list (RemoteOK, WWR, Wellfound, HN, company pages) names
these as sourcing channels but they are **NOT turnkey headless-apply channels** like
LinkedIn-EA / CSJ-TAL / Indeed-ATS. This session pivoted here when LinkedIn was
rate-limited and burned a full pass learning their real apply paths. Capture so the
next session probes the apply path FIRST and doesn't mistake "thin/closed" for
"exhausted by scarcity" — and doesn't fabricate to hit a target.

## When LinkedIn is rate-limited — pivot order that actually yields

LinkedIn is the only high-yield headless channel in this setup (180 tracked there,
`apply_ea.py` + `apply_queue.py` already built). With it off, the realistic reachable
on-profile inventory is near-zero. Pivot sequence that was actually tried 2026-07-15:

1. **CSJ** — already covered by `csj-payband-mining.md`. Audit all 15 families → 22
   target-family London/remote cards, only 2 junior-mid AND on-profile, both MI5
   clearance-gated (skip). Real ceiling there.
2. **Indeed** — was fully drained (every query auto-cooldown to ~next-day) AND is now
   behind a **Cloudflare wall** (manual CAPTCHA solve failing — user said skip).
   `references/indeed-exhaustion-and-dead-adverts.md` covers the dead-advert trap.
3. **Hackney** — `feed.py --nav …/job-search/` returns ~13 fresh, all social-care /
   licensing / manager / clinical. 0 on-profile for Jane.
4. **Reed.co.uk** — `https://www.reed.co.uk/` — **VERIFIED 2026-07-15 as a REAL
   non-LinkedIn channel** (the original board list + this note omitted it). Jane has a
   **live logged-in session** (CV uploaded). Source ~25 fresh UX/design jobs via
   `sites/reed.co.uk/scripts/feed.py --nav "https://www.reed.co.uk/jobs/ux-designer/london"`;
   apply is an on-site modal driven by `scripts/reed_apply.py <job_id>`. Harvested 8
   on-profile UX/Service Designer roles in one run. **Keys:** click Apply now / Submit via
   minimal `cfx.evaluate` DOM-click (snapshot ref-click 500s + modal won't open); the
   post-submit redirect 404s but the app registered — **verify via
   `reed.co.uk/account/jobs/applications` badge count**, never the 404. Screen by title
   not salary (Reed JD salary text is noisy). Full playbook: `references/reed-apply-playbook.md`.
   On-profile = UX/UI/Interaction/Service Designer, Trainee/Junior; exclude Lead/Senior/
   Architect/Developer/Manager + fashion-Print/Graphic.
5. **RemoteOK / WWR** — see below; apply path is NOT headless-submittable.

## RemoteOK — `https://remoteok.com`

- **Inventory (fast, structured):** public JSON API — `curl -fsS -A "Mozilla/5.0"
  "https://remoteok.com/api?tags=<tag>"` (first array element is a legal notice; real
  jobs follow). Tags that map to Jane's families: `designer`, `ux`, `ui`,
  `product-designer`, `user-researcher`, `frontend`, `web-designer`, `devops`, `qa`,
  `accessibility`, `content`, `wordpress`, `it-support`, `security`, `design-systems`,
  `creative`, `digital`. Filter: non-senior title + (remote / London / unspecified).
  Yielded ~17 on-profile London/remote candidates.
- **Apply path = HARD STOP (not headless).** Every posting's "How to Apply" resolves to
  **email your CV + a TestGorilla / online assessment gate** (e.g. `hr@example-recruiter.com` +
  `app.testgorilla.com/s/…`). No ATS form, no captured confirmation artifact → fails
  the SKILL.md "no confirmation ⇒ not Applied" rule. Even the 1 role without an
  assessment (0g Labs "UX UI Designer – AI Application") = "email your portfolio + a
  note", still no form/proof. **Do not count RemoteOK as a volume channel.** If the user
  ever wants these, they need a configured outbound email (himalaya is installed but
  unconfigured for you@example.com) AND the assessment gate still blocks proof capture.

## WWR — `https://weworkremotely.com`

- **JS-rendered, thin.** Static HTML yields ~1 listing; must drive via camofox
  (`cfx.navigate` + `cfx.evaluate` to scrape `a[href*="/remote-jobs/"]` after load).
  Category pages (`/categories/remote-design-jobs`) and keyword search
  (`/remote-jobs/search?term=…`) returned only **1–6 listings**, and **all senior-titled**
  (Staff/Senior UI/UX, Senior DevOps, Senior QA). 0 on-profile for Jane.
- Not a viable volume channel; not worth a heavy pass.

## Wellfound / HN "Who is hiring"

- Not scripted in this skill and not probed 2026-07-15 (RemoteOK/WWR already showed the
  remote-board pattern: thin + senior + email/assessment-gated). If revisited, expect the
  same apply-path reality — probe the apply mechanism before crediting inventory.

## WTTJ — genuine "needs creds" hard stop

- No `welcometothejungle` row in `ats-credentials.csv`; session not logged in. Provide
  Jane's WTTJ email/password + a populated profile → becomes a 3rd drivable board
  (`sites/welcometothejungle/NOTES.md`). Distinct from CSJ (which already has creds).

## The Dots — `https://the-dots.com` (verified 2026-07-15: DEAD on-profile inventory)

- Source via `sites/the-dots.com/scripts/feed.py --nav "https://the-dots.com/jobs/search?q=UX+Designer"`
  (~48 cards; on-profile non-fashion: Experience Designer Argos/Sainsburys, Junior Designer
  Oliver, Junior Designer MUBI, Middleweight Digital Designer Sainsburys, Mid Weight Designer
  Telegraph, UX Visual Designer Amazon, Product Designer ITV).
- **Apply path = off-site redirect to external ATS** (Greenhouse/Workday/Ashby) — The Dots is
  NOT the apply surface. More importantly: **the on-profile roles are STALE / DEAD adverts.**
  Verified 2026-07-15: Oliver = "no longer open"; ITV = 404; MUBI = "Job not found"; Amazon =
  heavy-JS timeout. Do NOT credit The Dots on-profile inventory without opening + confirming
  each live JD first — it aggregates expired postings. Net: not a viable volume channel.

## Adzuna — `https://adzuna.co.uk` (THE unblock for "LinkedIn off, do 100 more")

- **Canonical board #6** (`pipeline.py` FEEDS = `{indeed, wttj, csj, hackney, adzuna, reed}`).
  It was the ONE canonical board never sourced in the 2026-07-15 pivot runs — blocked on a
  missing credential, not on inventory. **Full detail + the exact credential trap:**
  `references/adzuna-sourcing-unblock.md`.
- In one line: `feed.py` needs `ADZUNA_APP_ID` + `ADZUNA_APP_KEY` (free at developer.adzuna.com).
  The `ats-credentials.csv` `adzuna.co.uk` row is WEBSITE login only (`you@example.com` /
  `[REDACTED — see ats-credentials.csv]`) — does NOT auth the API. Adzuna's website is anti-bot (search-URL nav
  bounces to homepage), so the JSON API is the only reliable path.
- **This is the single board with enough aggregated UK inventory to approach a 100-target
  without LinkedIn.** When stalled on CSJ+Reed exhaustion, ask the user for the Adzuna API
  key before concluding the ceiling.

## Verified: Reed re-source yields NO fresh on-profile inventory (2026-07-15)

After harvesting Reed (badge=10, all on-profile UX/Service Designer), a re-source across 6
families returned only: already-applied ids (57044891 confirmed "applied 7 hrs ago" on its
own page), one persistent wedge (57119546 UX Writer — Apply modal won't open via any click
method), off-location Salisbury trainee. **Conclusion: Reed is genuinely exhausted, not
under-sourced.** A re-source that returns only already-tracked / off-location / wedged cards
IS the data-scarcity signal — don't keep re-sourcing hoping for more. (Same signal for CSJ
after all 15 families × London+national are drained.)

## Bottom line for "LinkedIn off, do 100 more"

The non-LinkedIn fresh on-profile pool is **NOT automatically zero** — **Reed.co.uk is a
real, harvested channel** (Jane's session is live; 8 on-profile UX/Service Designer roles
applied in one run via `scripts/reed_apply.py`). So the pivot order is: **CSJ** (audit
all 15 families) → **Reed** (feed + `reed_apply.py`) → **Adzuna** (get API key, then
`feed.py` — the real volume unlock) → **Indeed** (drained + Cloudflare wall) → **Hackney**
(0 on-profile) → **The Dots / RemoteOK / WWR** (dead/stale/email/assessment/senior-gated) →
**WTTJ** (needs creds). After exhausting CSJ + Reed (+ Adzuna if key obtained), the
*remaining* gap is genuinely unreachable without **LinkedIn** (rate-limited) or **WTTJ creds**
— at that point state the data-scarcity ceiling ONCE with the concrete unblocks (LinkedIn
limit lifts / WTTJ creds / Adzuna API key / Indeed Cloudflare clears). **Never fabricate
applications or pad with senior/off-profile/clearance-gated roles to hit a target** — that
violates the no-fabrication rule and poisons the tracker.
