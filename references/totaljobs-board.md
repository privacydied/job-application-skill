# TotalJobs — `totaljobs.com` (discovered 2026-07-16)

NOT in `pipeline.py` `FEEDS` (canonical 6 = indeed,wttj,csj,hackney,adzuna,reed) and NOT in the SKILL.md rotation — so it was never sourced this whole run until probed late. A real, large UK aggregator (sibling of CVLibrary/Reed).

## Reachability (verified 2026-07-16)
- `curl -s --max-time 25 -A "Mozilla/5.0 (Windows NT 10.0; Win64; x64)..." "https://www.totaljobs.com/jobs/ux-designer/in-london"` → **HTTP 200**, ~104 KB body, **76 "UX Designer" London** matches, `job-card`/`jobCard` elements present. So the site is NOT Cloudflare-walled at the HTTP layer.
- **Browsable in camofox via explicit `nav`** (the earlier "blank render" was the `open-tab "<url>"` auto-nav silent failure — see `camofox-open-tab-nav-pitfall.md`, NOT a TotalJobs block). With `open-tab "about:blank"` + `cfx.sh nav`, TotalJobs renders **22K+ chars**, extracts job URLs, and individual job pages show a real **"Apply" button** (`[e10]` etc.). So sourcing is fully feasible.

## Status = blocked on APPLY (account needed), not on sourcing/backend
- **Sourcing:** feasible — build `sites/totaljobs.com/scripts/feed.py` (copy Reed's; TotalJobs cards are `article`/`[data-jobid]`-style — verify live). Pagination + London/remote/national across the 12 Jane families.
- **Applying:** BLOCKED. Clicking "Apply" on a job while unauthenticated **redirects to `https://www.totaljobs.com/` (homepage)** — TotalJobs requires a logged-in account to apply. There is NO `totaljobs.com` row in `ats-credentials.csv`. Until a TotalJobs account is added (+ a `totaljobs_apply.py` modelled on `reed_apply.py`, handling the login-gated apply modal), it is a hard stop (login wall), not a data-scarcity ceiling.
- **Registration is ALSO headless-blocked (verified 2026-07-16):** navigating to the Sign-up hash step (`?login_source=Homepage_top-register#step-2`) shows an Email + Continue form. Typing `you@example.com` + Continue **stays on step 1** (email prefilled, no advance) and the page also shows "Already have an account? Log in" + a "Scan the QR code" mobile-app flow. So even attempting to create an account hits an **email-verification / OOB step that cannot complete headlessly** (no inbox access from the agent). The unblock is a real TotalJobs login (password reset emailed to Jane's inbox, done by the user) — NOT a self-service registration from the agent.
- The 2026-07-16 session mis-diagnosed TotalJobs as "backend dead" — it was the `open-tab` bug; browsing works fine once nav is explicit.

## Action for the next session (after a TotalJobs account is provided)
1. `curl` probe first to confirm HTTP 200 (rules out a real Cloudflare wall).
2. `open-tab "about:blank"` + explicit `cfx.sh nav` (NOT `open-tab "<url>"`).
3. Build `sites/totaljobs.com/scripts/feed.py` (copy Reed's).
4. Build `totaljobs_apply.py` (copy `reed_apply.py`) — but first log in to TotalJobs (account needed) so the Apply click opens the form instead of bouncing to homepage.
5. Filter on-profile: UX/Service/Interaction/Product Designer, User Researcher, Business Analyst, Content Designer, UX Writer. Exclude graduate/developer/engineer/senior/lead/AI-SC-cleared (off Jane's profile).

## Why it matters
When LinkedIn is rate-limited and CSJ+Reed look exhausted, TotalJobs is a 7th aggregator with its own distinct inventory (it is where Adzuna redirects sometimes). It should be ADDED to the canonical board set + the SKILL.md "Also in rotation" list so a future "LinkedIn off, do 100 more" run sources it on pass 1, not discovers it on pass 19.
