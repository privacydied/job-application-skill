# Profile platforms & marketplaces — set up once, then passive

Platforms whose **apply path** is a signed-in profile rather than a form: matching is
inbound (employers approach you) or brief-based. An agent cannot complete these
autonomously — they need his identity, his consent, and in several cases a video/ID check.
The honest implementation is this page: **what the user does once, and what it yields**.

⚠️ **"No apply path" ≠ "no feed".** Two of these DO have public listing surfaces and ship
real feeds; the rest genuinely have nothing to harvest. Verified per-platform 2026-07-17 —
don't generalise from one to the others:

| platform | public feed? | apply |
|---|---|---|
| **hackajob** | ✅ **YES** — `sites/hackajob.com/` (public Astro directory, `sitemap-jobs.xml` ≈17k URLs) | profile-gated (every CTA → `/talent/sign-up`) |
| **Find an Apprenticeship** | ✅ **YES** — `sites/findapprenticeship.service.gov.uk/` | DfE candidate account |
| **Cord** | ❌ no — every route returns an identical 8.7KB "JavaScript is not enabled" shell; its 323 `/api/` routes are account-scoped (401) | profile-gated |
| YunoJuno / Worksome / Contra | ❌ no public route | profile/brief-gated |
| Outlier / DataAnnotation / Mercor / Alignerr | ❌ marketing pages only | assessment/ID-gated |

hackajob's feed is **discovery-only** (`ats_hint: "hackajob-match"`): the rows are a hiring
signal, not something to submit to. It is also **US-heavy** — an 8-page support sweep
returned 76 non-UK / 17 UK / 3 London, so expect a thin London yield.

Cord has a sitemap listing ~3,169 job URLs, but deliberately has **no feed**: the rows carry
no location (precheck screens on it), no salary, slugified titles, and every `<lastmod>` is
the sitemap's own build timestamp — closed roles are indistinguishable from open ones.

## Why they're worth the one-off effort

Every other channel in this skill costs ~1 unit of effort per application. These cost one
setup and then produce inbound leads indefinitely. They're the only channels in the whole
skill with that shape, which is exactly why they're worth doing even though they can't be
automated.

## Reverse marketplaces — employers apply to him

| Platform | URL | Fit | Setup |
|---|---|---|---|
| **hackajob** | `hackajob.com` | DevOps / IT support / frontend. Salary-transparent, employers initiate. **Sourceable** — see `sites/hackajob.com/`. | Sign up → skills + salary expectation + right-to-work → sit in the pool. Some roles gate on a timed tech assessment. |
| **Cord** | `cord.com` (`cord.co` 301s here) | London tech; direct-message hiring, no recruiters. No public feed. | Profile + role preferences; he messages hiring managers directly. |

## Freelance / contract marketplaces

A £300/day junior–mid design contract is a legitimate parallel track to permanent
applications — and contract work is one of the few routes that pays *while* the permanent
search runs.

| Platform | URL | Fit | Setup |
|---|---|---|---|
| **YunoJuno** | `yunojuno.com` | London freelance design/dev marketplace; brief-matching. The strongest UK creative-freelance fit. | Freelancer profile + rate + portfolio; vetted before briefs arrive. (No public freelancer/job route — `/hire/freelancers` and `/freelancer/jobs` both 404 logged-out.) |
| **Worksome** | `worksome.com/uk` | Contract/external-workforce platform; UK enterprise clients. | Profile + rate + compliance (IR35 status). |
| **Contra** | `contra.com` | Commission-free freelance; design-heavy, remote/global. | Portfolio-led profile; inbound + browsable opportunities once signed in. |

## AI-training marketplaces — the §7 pivot

`references/target-roles.md` §7 already lists "AI Trainer / Data Annotation QA (design/UX
domain expert)" at Tier C. These platforms hire exactly that: domain experts to train and
evaluate models. His design + GenAI + prompt-engineering background is the qualifying
signal, and the work is remote and hourly.

| Platform | URL | Notes |
|---|---|---|
| **Outlier** | `outlier.ai` | Freelance AI training by domain. Sign-up → domain quiz → paid tasks. |
| **DataAnnotation** | `dataannotation.tech` | Assessment-gated; pays per task once through. |
| **Mercor** | `work.mercor.com` | Interview-based matching to AI-lab work. |
| **Alignerr** | `alignerr.com` | Expert RLHF/eval work; application + assessment. |

⚠️ All four gate on an **assessment or ID/video check** and pay per task. Treat as an
income channel, not an "application" — **never log these in `application-tracker.csv` as
`Applied`**: there is no employer, no vacancy, and no confirmation artifact, so they cannot
satisfy the no-fabrication rule.

## Apprenticeships — `findapprenticeship.service.gov.uk`

A **real feed** (`sites/findapprenticeship.service.gov.uk/`), not a manual channel.
Cyber/DevOps Level 4 apprenticeships have no age limit, pay a wage, and solve the named
cert gap in `target-roles.md` §6 — low competition for a career-changer with real
experience. Worth sourcing only if he'd accept apprentice-level pay; ask before a volume
run.

⚠️ Two traps that make it look dry when it isn't: `distance` defaults to `"all"` (England-
wide) and silently ignores `location`; and `searchTerm` matches the apprenticeship
*standard*, not free text — `cyber` returns ~2 in all of England. A low count there is the
board being honest, not a broken feed.

## Rule

Nothing on this page produces a tracker `Applied` row. They are inbound/income channels.
The tracker's `Applied` status still requires a real vacancy and a real confirmation
artifact — see SKILL.md.
