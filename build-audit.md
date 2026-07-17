# Build Audit — Feed/Platform Expansion Candidates (2026-07-17)

> **STATUS: BUILT.** Every candidate below was live-probed and, where real, implemented.
> Feeds went 17 → 41 (`pipeline.py FEEDS`). Proven end-to-end with a real application
> (Monzo Content Strategist, Greenhouse → confirmation page).
>
> **The plan was wrong in six places. Probing found them; the table below is corrected.**
>
> | claim in this audit | reality |
> |---|---|
> | DWP Find a Job = "easiest new headless board", build #3 | ⛔ **PERMANENTLY CLOSED.** HTTP 200 + body "This site is now closed". Looked alive. |
> | Technojobs = "weak anti-bot" | ⛔ **DEAD.** `www` is a dangling CNAME (no A record); apex has 80/443 closed. Last archive.org 200: 2025-11-03. |
> | Charity Digital jobs | ⛔ **DEAD.** Renders a job list whose links all point at `charitydigitaljobs.org` — NXDOMAIN on 4 resolvers. |
> | UK Parliament `workforus.parliament.uk` | ⛔ **NXDOMAIN.** (Real board: `careers.parliament.uk`.) |
> | "BBC = Oleeo, 3rd use justifies the driver" | ❌ BBC is **SAP/jobs2web**, not Oleeo. Oleeo is **`*.tal.net`**, not `oleeo.com`. Met's `metpolice.tal.net` reads "System Pending Deletion" (live board: `policecareers.tal.net`). |
> | Dribbble "query Algolia directly" | ❌ Keys are real but the indexes are nav autocomplete — **there is no jobs index**. Its plain GET search works instead. |
> | "hackajob = no public feed, document only" | ❌ **Wrong** — public Astro directory, `sitemap-jobs.xml` ≈17k URLs. Feed shipped (discovery-only). |
> | Careerjet legacy API | ⛔ Legacy is **401-dead**; built against live **v4** instead (needs a key). |
> | Talent.com "JSON-LD has JobPosting" | ❌ Its JSON-LD is an `ItemList` of bare URLs. Parsed `data-new-id` instead. |
> | Trac "very drivable" | ❌ Unverified hypothesis. Search + every job detail 403 behind a Cloudflare challenge → **not** a sanctioned CAPTCHA → full halt. |
>
> **The #1 recommendation held for sourcing, not submitting.** ATS-direct sources
> beautifully (3,182 postings, keyless, no account). But most ATSes now gate the *submit*:
> Greenhouse ✅ (reCAPTCHA v2, sanctioned) · Lever ⛔ hCaptcha · Ashby ⛔ spam-flag ·
> Workable ⛔ Turnstile. And **Canonical's Greenhouse form requires an anti-AI attestation**
> that this skill must never tick. Full detail: `references/ats-apply-surface.md`.

Grounded in the repo: current coverage is 17 pipeline feeds (LinkedIn, Indeed, WTTJ, CSJ,
Hackney, Adzuna, Reed, Dots, TotalJobs/CWJobs, Guardian, CharityJob, CVLibrary, NHS,
MI5/MI6) plus the ATS drivers (Greenhouse, Lever, Ashby, Workday, Workable,
SmartRecruiters, Recruitee, HiBob, TalentLink, applicationtrack). Profile constraints:
junior→mid, London-or-remote only, no driving, British citizen (clearance-eligible),
families = design/UX, gov digital, IT support, DevOps/security, charity digital, growth,
music-tech.

## First principles: what makes a board worth building

The existing references already encode the selection function — a new feed only pays if
it clears all four gates that killed RemoteOK/WWR/Dots:

1. **Fresh on-profile junior-mid London/remote inventory the current 17 don't already
   aggregate** (Adzuna/Reed/TotalJobs/CVLibrary already swallow most generic UK postings —
   a new *generalist* board is mostly dedup noise)
2. **A provable headless apply path** — form-based, no email-CV/assessment gate, no
   downstream account wall, *or* downstream is an ATS already driven
3. **Bot-friendly sourcing** — stable URLs or JSON, no Cloudflare
4. **Lower competition per posting** than LinkedIn/Indeed (niche boards and
   single-employer portals win here)

That function immediately implies the biggest insight:

## ⚡ The highest-leverage "platform" isn't a board at all — it's ATS-direct company feeds

The #1 documented blocker is the **downstream employer-ATS account wall** (Adzuna/WTTJ/
Dots source fine, then die at amazon.jobs). But **Greenhouse, Lever, Ashby, Workable,
SmartRecruiters and Recruitee applications are account-less** — and all six drivers
already exist in `sites/`. All six also expose **public, keyless JSON listing APIs**:

- `boards-api.greenhouse.io/v1/boards/<company>/jobs?content=true`
- `api.lever.co/v0/postings/<company>?mode=json`
- `api.ashbyhq.com/posting-api/job-board/<company>`
- `apply.workable.com/api/v1/widget/accounts/<company>`
- `api.smartrecruiters.com/v1/companies/<company>/postings`
- `<company>.recruitee.com/api/offers`

So one new feed — `sites/_common/scripts/ats_direct_feed.py` + a curated `companies.csv`
(~150–300 London/remote-UK companies on those ATSs, filtered by family) — gives a
**zero-CAPTCHA, zero-login, JSON-clean sourcing channel whose every result is directly
submittable with drivers already shipped**. It also beats boards on freshness (postings
appear on the ATS days before aggregators). Seed the company list from WTTJ/Dots
redirects already logged, plus known London design/music-tech/fintech employers (Monzo,
Starling, Deliveroo, Octopus, Zopa, SoundCloud, Beatport, Focusrite, Ableton, Framer,
Maze…). This is the single fastest route to "rapidly expanded."

## Tier 1 — Gov/public sector portals

The MI5/CSJ pattern: separate portal, own inventory, form-based apply,
clearance-eligibility is fine.

| Platform | Why | Apply path |
|---|---|---|
| **DWP Find a Job** — `findajob.dwp.gov.uk` | The *official* GOV.UK job board. Huge SME/junior inventory that never hits LinkedIn; famously bot-friendly plain HTML; free account | On-site apply form for many postings — likely the easiest new headless channel after ATS-direct |
| **GCHQ** — `recruitment-services.co.uk` / GCHQ careers | Completes the trilogy with MI5/MI6 already built; DevOps/cyber/design roles, junior schemes | Own portal; same "agent fills, noVNC oversight" model as applicationtrack |
| **Jobs Go Public** — `jobsgopublic.com` | Aggregates London borough councils + housing associations + charities — the exact §14 "one-person digital team" family; low competition | JGP is itself the ATS (like TalentLink) → one driver unlocks dozens of employers |
| **LGjobs** — `lgjobs.com` | Local-gov aggregator sibling; digital officer/IT support heavy | Mostly redirects to council ATSs (TalentLink — driver exists) |
| **jobs.ac.uk** | Universities: web editor / digital officer / e-learning / AV support at every London uni; slow-moving, under-competed | Most London unis use **Stonefish** — one new ATS driver covers ~50 employers |
| **UK Parliament** — `workforus.parliament.uk` | Digital/UX team (PDS) recruits separately from CSJ | Oleeo-based portal |
| **Met Police (staff roles)** — met careers | Non-officer digital/IT staff roles; London-locked so thin competition | Oleeo — same driver as Parliament/BBC if built once |
| **TfL careers** — `tfl.gov.uk/careers` | Big in-house digital team, perpetual IT support/service desk hiring, London | SAP SuccessFactors (new driver, but TfL alone justifies it; SF also covers many corporates) |
| **NHS supplementary: TRAC** — `trac.jobs` | jobs.nhs.uk is sourced but TRAC is where trust applications actually happen; also lists direct | Trac apply is a plain multi-step form — very drivable |
| **BBC / Channel 4 / ITV careers** | Design/UX/AV/digital at scale; BBC = Oleeo again | Oleeo driver (3rd use — this makes Oleeo the top *new ATS* to build) |

Note the pattern: **Oleeo** (Parliament, Met, BBC, NCA) and **Stonefish** (universities)
are the two new ATS drivers that each unlock a whole Tier-1 row, the way TalentLink
unlocked Hackney.

## Tier 2 — Sector verticals matched to role families

**Design/creative (§1–3, §10):**
- **If You Could** — `ifyoucouldjobs.com` — *the* London junior/midweight design board;
  It's Nice That's job board; exactly his level. Small enough that apply is often
  direct-form/ATS
- **Design Week Jobs** / **Creativepool** / **Dezeen Jobs** — digital designer inventory
  the aggregators miss
- **Dribbble jobs** — remote-heavy, mostly redirects to Greenhouse/Lever → feeds the
  ATS-direct channel

**Music-tech (§10 — his standout differentiator, currently zero dedicated channels):**
- **Music Business Worldwide jobs** — `musicbusinessworldwide.com/jobs` — the industry's
  main board (labels, DSPs, music-tech startups; London-heavy)
- **UK Music / Record of the Day** boards — smaller but hyper-on-profile
- Plus the ATS-direct company list: Spotify, SoundCloud, Beatport, Kobalt, Believe,
  Focusrite, Native Instruments, Ableton, LANDR — most on Greenhouse/Lever
  *(account-less apply)*

**Charity/purpose (§14 — CharityJob is covered, add):**
- **CharityConnect jobs** / **Third Sector Jobs** / **Charity Digital jobs** — the
  digital-officer family specifically
- **Escape the City** — purpose-driven junior digital roles, London-centric

**IT support / DevOps / cyber (§5, §6, §13):**
- **Technojobs** — `technojobs.co.uk` — UK IT board, 1st/2nd-line + junior sysadmin
  heavy, weak anti-bot
- **JobServe** — huge IT inventory (contract-skewed, but contracts are a legitimate
  tangential pivot for a support tech)
- **CyberSecurityJobsite.com** — junior SOC/analyst listings clustered in one place
- **hackajob** — reverse marketplace: build profile once, employers apply to *you*;
  near-zero marginal effort per "application", strong for DevOps/support

**Fintech (design+IT crossover, London's biggest employer pool):**
- **eFinancialCareers** — UX/IT-support roles inside finance; junior roles pay above
  market

## Tier 3 — Aggregator APIs (cheap breadth, dedup-heavy)

- **Reed's official API** — `developer.reed.co.uk` (free key). Reed is currently
  browser-scraped despite being the best non-LinkedIn board; the API would make Reed
  sourcing instant and cooldown-free. Probably the single cheapest upgrade on this list.
- **Jooble API** (free partner key) and **Careerjet API** — same shape as Adzuna,
  different inventory tails
- **Talent.com** — big aggregator, structured pages
- **Himalayas.app** — remote board with a clean public JSON API (unlike RemoteOK it links
  to ATSs, not email gates) — the one remote board worth another look

## Tangential pivots (new *kinds* of platform)

1. **AI-training marketplaces** — Outlier, DataAnnotation, Mercor, Alignerr: "design/UX
   domain-expert AI trainer" is already Tier C in target-roles §7. These are
   sign-up-once platforms, not per-job applications — one afternoon each, then passive.
2. **Freelance/contract platforms with UK creative focus** — **YunoJuno** (London
   freelance design/dev marketplace, brief-matching), **Worksome**, Contra. A £300/day
   junior-mid design contract is a legitimate parallel track while permanent apps run.
3. **Reverse marketplaces** — hackajob (above), **Cord** (`cord.co`, London tech,
   direct-message hiring). Profile-based: fill once, respond to inbound.
4. **Apprenticeship route** — `gov.uk` Find an Apprenticeship: cyber/DevOps Level 4
   apprenticeships have no age limit, pay a wage, and solve the cert gap named in §6.
   Worth one feed if he'd consider it — genuinely low competition for career-changers
   with real experience.

## What NOT to build (fails the gates, per prior probes)

Monster/Jobsite (dead/absorbed into TotalJobs), SimplyHired/Glassdoor (Indeed shells —
same Cloudflare), WWR/RemoteOK (proven thin/email-gated), grad boards (Milkround/Bright
Network — he's not a recent grad), agency boards (Hays/Michael Page — CV-drop black
holes, no confirmation artifact → fails the "no proof ⇒ not Applied" rule).

## Suggested build order

1. **ATS-direct feed + company list** (0 new drivers, kills the downstream-wall problem)
2. **Reed API key** (upgrade existing best board)
3. **DWP Find a Job** (easiest new headless board)
4. **Oleeo driver** → unlocks Parliament + Met + BBC + NCA in one go
5. **Jobs Go Public** (board = ATS, like TalentLink)
6. **If You Could + MBW** (thin but hyper-on-profile, near-zero competition)
7. **GCHQ** (pattern already proven with MI5/MI6)
8. **hackajob/Cord/YunoJuno** profiles (one-off setup, passive yield)

## Next step

Live-probe the top candidates (verify apply paths, anti-bot posture, and the exact ATS
behind DWP/Oleeo/JGP) **before** committing to build order — skipping the apply-path
probe is the documented session-burner (see `references/alternate-boards-apply-paths.md`).
