# job-application — an agent skill for automated job applications

> _I will maintain this skill until I get a job, lol._

A toolkit an AI agent (Claude Code, or any agent that can run shell + read `SKILL.md`)
uses to **source jobs from job boards, screen them against your profile, fill and submit
ATS application forms in a browser, and track everything** — end to end, on-profile only.

It is built around a small set of Python drivers over an anti-detect browser's REST API,
plus per-site "recipes" (`sites/`) and hard-won ATS notes (`references/`). The agent's full
operating manual is **`SKILL.md`** — read that after this.

> ⚠️ **Your data stays local.** All personal information (your profile, resumes, cover
> letters, application history, credentials, cookies) is **gitignored** — it lives on your
> disk but is never committed. This repo ships only the tooling + placeholder `*.example`
> templates. See [What's ignored](#whats-kept-out-of-git) below.

---

## What it does

- **Source** — pull fresh postings from job boards (LinkedIn, Indeed, Reed, Welcome to the
  Jungle, Civil Service Jobs, Adzuna, and more) via `sites/<board>/scripts/feed.py`.
- **Screen** — filter to roles that genuinely fit your profile (title, seniority, location,
  right-to-work) before spending any effort. On-profile only; no spray-and-pray.
- **Apply** — drive the ATS form to submission: Ashby, Greenhouse, Lever, Workday, Workable,
  SmartRecruiters, plus in-platform flows (LinkedIn Easy Apply, WTTJ). Answers come from your
  profile/config; resumes from `uploads/`.
- **Track** — every application is logged to `application-tracker.csv` with proof of
  submission. Status `Applied` requires a real confirmation artifact — no fabrication.

---

## Supported sites

Each lives under `sites/<name>/` (a `feed.py` for sourcing and/or a `NOTES.md` apply recipe).
Beyond the ATSes with bespoke recipes below, the generic form engine (`sites/_common/scripts/
atsform.py`) drives many other standard ATS forms via label-based field matching.

**Job boards** (source postings, and apply where supported):

| Board | Notes |
|---|---|
| LinkedIn | sourcing + **Easy Apply** |
| Indeed | sourcing (`indeed.com`) |
| Reed | sourcing + apply (`reed.co.uk`) |
| Welcome to the Jungle | sourcing + **in-platform apply** (`welcometothejungle.com`) |
| Civil Service Jobs | sourcing + apply (`civilservicejobs.service.gov.uk`) |
| Adzuna | sourcing via API (`adzuna.co.uk`) — needs a **free** `app_id`/`app_key` from [developer.adzuna.com](https://developer.adzuna.com) |
| The Dots | sourcing (`the-dots.com`) |
| Totaljobs | sourcing (`totaljobs.com`) — StepStone family; **apply is account-gated** (login wall) |
| CWJobs | sourcing (`cwjobs.co.uk`) — Totaljobs/StepStone sibling, same adapter; tech/IT roles |
| Guardian Jobs | sourcing + **direct apply** (`jobs.theguardian.com`) — Madgex; on-page form (name/email/CV), reCAPTCHA-gated |
| CharityJob | sourcing (`charityjob.co.uk`) — charity/third-sector digital & comms roles |
| CV-Library | sourcing (`cv-library.co.uk`) — major agency board; apply is account + chooser-gated |
| NHS Jobs | sourcing (`jobs.nhs.uk`) — gov/health digital & service-design; apply account-gated (native or Trac hand-off) |
| MI5 / MI6 (SIS) | sourcing (`applicationtrack.com`) — intelligence-agency vacancies; ⛔ **apply is user-completed** (security-vetted, no auto-fill) |
| Hackney Council | sourcing + apply (`recruitment.hackney.gov.uk`) |
| MoJ / HMCTS | apply wizard (`jobs.justice.gov.uk`) |
| SEEK | **Australia/NZ only** (`seek.com.au` / `seek.co.nz`) — no UK site; vestigial for a London search |

**ATS platforms** (application forms the drivers can fill + submit):

| ATS | Domain |
|---|---|
| Ashby | `jobs.ashbyhq.com` |
| Greenhouse | `boards.greenhouse.io` / `job-boards.greenhouse.io` |
| Lever | `jobs.lever.co` |
| Workday | `*.myworkdayjobs.com` |
| Workable | `apply.workable.com` |
| SmartRecruiters | `jobs.smartrecruiters.com` |
| Recruitee | `*.recruitee.com` |
| HiBob (Bob Hiring) | `*.careers.hibob.com` |
| Lumesse TalentLink | hosted recruitment platform |
| Application Track (MI5/MI6) | `recruitmentservices.applicationtrack.com` — VacancyFiller ATS, UK public sector incl. **MI5 & MI6/SIS** (see the ⛔ integrity note in `sites/applicationtrack.com/NOTES.md`) |

---

## Requirements

- **Python 3.8+** (standard library only — no pip installs for the core).
- **A browser automation backend** exposing the REST API the drivers expect (an anti-detect
  browser such as camoufox behind a small REST server on `http://localhost:9377`; a separate
  Playwright/Chromium endpoint is used for verification). The drivers talk to it via
  `sites/_common/scripts/cfx.py` / `cfx.sh` using `CFX_KEY`, `CFX_TAB`, `CFX_USER` env vars.
  A reference Docker stack is in **`compose.example.yaml`** (copy to `compose.yaml`, set your
  own paths/secrets via `camofox-browser.env.example` → `camofox-browser.env`). The camofox
  image itself is built from a separate project not included here — see the compose comments.
- Job-board accounts for the boards you want to use (stored in a gitignored credentials file).

This repo does **not** ship the browser backend — point the `CFX_*` env vars at your own.

---

## First-time setup

1. **Create your profile** (the single source of truth the agent answers as):
   ```bash
   cp references/applicant-profile.example.md references/applicant-profile.md
   $EDITOR references/applicant-profile.md      # fill in your real details
   ```
   Keep the first line as `# Applicant Profile — <Your Name>` (a preflight check requires it).

2. **Fill the answer/contact config** used to auto-fill common ATS fields:
   ```bash
   cp sites/_common/apply-defaults.example.json sites/_common/apply-defaults.json
   $EDITOR sites/_common/apply-defaults.json     # name, email, phone, links, city…
   ```

3. **Set your target roles** — the title families the agent screens every job against.
   **Required:** `check_title.py` reads this to decide eligibility; without your own copy it
   falls back to the generic example (fine to start, but tailor it to what you actually want):
   ```bash
   cp references/target-roles.example.md references/target-roles.md
   $EDITOR references/target-roles.md         # keep the "## N. … (Tier A)" + "- title" format
   ```

4. **(Optional) Per-role-family resume positioning** for tailored resumes/cover letters:
   ```bash
   cp sites/_common/family-bases.example.json sites/_common/family-bases.json
   $EDITOR sites/_common/family-bases.json
   ```
   *(Also optional: `references/resume-assets.md` — free-form notes about which resume file
   suits which role. Not read by any script; create it only if you want to keep such notes.
   It's gitignored like the rest of your personal data.)*

5. **Add your board credentials** (gitignored — never committed):
   ```bash
   # ats-credentials.csv, columns: site,email,password,date
   printf 'site,email,password,date\n' > ats-credentials.csv
   ```
   Most boards use a login (email/password). **Adzuna is API-based** — register (free) at
   [developer.adzuna.com](https://developer.adzuna.com) for an `app_id` + `app_key`, then either
   `export ADZUNA_APP_ID=… ADZUNA_APP_KEY=…` or add a row `adzuna-api,<app_id>,<app_key>` to
   `ats-credentials.csv`.

6. **Add your resumes** as PDFs in `uploads/` (also gitignored).

7. **Point at your browser backend** and export the env the drivers read:
   ```bash
   export CFX_URL=http://localhost:9377
   export CFX_KEY=...        # backend access token
   export CFX_USER=...       # your browser session user
   export CFX_TAB=...        # a tab id from POST /tabs
   ```

8. **Verify the core is healthy:**
   ```bash
   python3 -m pytest tests/test_core.py -q
   ```

Then hand the agent `SKILL.md` and let it drive. Everything you filled in above stays on
your machine; the agent reads it locally.

---

## Browser backend (Docker Compose)

The drivers talk to a browser over a network REST/WebSocket endpoint — they don't launch one
themselves. A reference stack is provided as **`compose.example.yaml`** (a template; no real
secrets or paths). Copy and fill it in:

```bash
cp compose.example.yaml compose.yaml
cp camofox-browser.env.example camofox-browser.env   # then set CAMOFOX_ACCESS_KEY / VNC_PASSWORD
$EDITOR compose.yaml                                  # set your uploads path + (optional) VPN
docker compose up -d
```

The bundle defines (trim to what you need):

| Service | Port | What it is |
|---|---|---|
| `playwright` | 3006 | Playwright run-server — used for verification / PDF render |
| `camofox-browser` | 9377 (REST), 6080 (noVNC) | anti-detect Camoufox browser + REST API the skill drives (**this is `CFX_URL`**) |
| `chrome-cdp` | 9222 | *(optional)* headless Chromium CDP endpoint |
| `vpn-sidecar` + `playwright-vpn` | 3007 | *(optional)* egress VPN + a VPN-routed Playwright |

Notes:
- The **`camofox-browser` image is built from a separate `camofox-browser/` project** (Dockerfile,
  `server.js`, Makefile) that is **not included in this repo** — point the build context at your
  own copy, or delete that service and run only the plain `playwright` server if you don't need
  the anti-detect browser.
- Your real `compose.yaml`, `camofox-browser.env`, and any `*.ovpn` are **gitignored** — only the
  `*.example` versions are committed.
- After it's up, point the drivers at it:
  ```bash
  export CFX_URL=http://localhost:9377
  export CFX_KEY=$(grep CAMOFOX_ACCESS_KEY camofox-browser.env | cut -d= -f2)
  ```

---

## Hardcoded defaults you may want to edit

Most personal values live in the gitignored config (`apply-defaults.json`, `applicant-profile.md`).
A few **seed defaults** ship in code as a starting point — the committed versions are neutral
placeholders (`"Prefer not to say"`, `Jane Doe`, `you@example.com`), so review and adjust them:

- **`sites/_common/scripts/screener.py` → `_SEED`** — the screener answer bank (right-to-work,
  sponsorship, relocation, notice period, years-of-experience, demographics). On first use it is
  written to `screener-answers.csv` (gitignored); after that, **edit the CSV, not the seed**. The
  committed seed answers demographics as `"Prefer not to say"` — set your real preferences in the CSV.
- **`scripts/amazon_apply.py` → `ANSWERS`** — the amazon.jobs answer map (salary, relocation,
  education, etc.). Edit for your profile.
- **`sites/_common/apply-defaults.example.json`** and **`family-bases.example.json`** — copy to the
  non-`.example` names and fill in (see setup).

Tests assert on the *matching behaviour* of these, not on any personal value, so they pass with the
neutral placeholders and with your real answers alike.

---

## Repository layout

```
SKILL.md                     the agent's full operating manual (read this)
sites/                       per-board recipes: feed.py (source) + NOTES.md (ATS quirks)
  _common/scripts/           shared drivers: cfx.py (browser REST), atsform.py (form engine),
                             screener.py, precheck.py, pipeline.py, tailor.py, …
  _common/*.example.json     placeholder configs you copy + fill (see setup)
scripts/                     top-level entry drivers (per-ATS orchestrators)
references/                  hard-won ATS/board technique notes (how each form actually works)
tests/test_core.py          regression tests for the deterministic logic
templates/                   example form specs
```

---

## What's kept out of git

Your personal data is gitignored and stays only on your disk (see `.gitignore`):

- **Identity & profile** — `references/applicant-profile.md`, `sites/_common/apply-defaults.json`,
  `sites/_common/family-bases.json`, `references/target-roles.md`, `references/resume-assets.md`
- **Application artifacts** — the entire `applications/` folder (cover letters, statements,
  resumes, confirmation screenshots) and `uploads/` (your resume PDFs)
- **Run state** — `application-tracker.csv`, `apply-stats.csv`, and the other run CSVs/JSONLs
- **Credentials & sessions** — `ats-credentials.csv`, `*cookies*.txt`, all `.jobenv*`/env files,
  your real `compose.yaml` / `camofox-browser.env` / `*.ovpn`

A first-time user regenerates their own from the committed `*.example` templates.

> **📌 Note on `.gitignore`** — this file is what keeps your personal data private, so a few
> rules matter:
> - **Don't remove the personal-data entries.** They're grouped and commented at the top of
>   `.gitignore`; deleting one would start tracking that file on the next `git add`.
> - **Keep personal values in the gitignored configs, never hard-coded in tracked code/docs.**
>   The tooling reads your details from the ignored files (`apply-defaults.json`, etc.) by design.
> - **Directories use the `dir/*` + `!dir/.gitkeep` form** (e.g. `applications/*`) so the empty
>   folder survives a clone while its contents stay ignored — don't change it back to a bare `dir/`.
> - **The pre-commit guard is a `.git/hooks/` symlink and does NOT travel with a clone.** After
>   cloning, re-install it: `ln -sf ../../scripts/check-no-pii.sh .git/hooks/pre-commit`.

### How it stays private over time

- **Runtime writes go to gitignored paths.** As the agent works it writes your applications to
  `applications/`, logs to `application-tracker.csv`, seeds answers to `screener-answers.csv`, etc.
  — all gitignored. So normal use never puts your personal data into git.
- **A guard catches accidental leaks.** `scripts/check-no-pii.sh` reads your real details from your
  gitignored config and fails if any of them appear in a **tracked** file. Run it before you push:
  ```bash
  bash scripts/check-no-pii.sh
  ```
  Wire it as a pre-commit hook so you can't forget:
  ```bash
  ln -sf ../../scripts/check-no-pii.sh .git/hooks/pre-commit
  ```
- **The only way PII re-enters git** is if you (or an agent) hard-code a personal value into a
  *tracked* code/doc file. The guard above is there to catch exactly that — keep personal facts in
  the gitignored config, referenced by the code, not pasted into it.

---

## Ground rules the tooling enforces

- **On-profile only** — roles are screened against your profile before applying; off-profile
  roles are skipped, not forced.
- **No fabrication** — answers are drawn from your profile; a `Applied` row requires a real
  submission-confirmation artifact (screenshot/text). Un-confirmed attempts are logged
  honestly (`Applied?` / `Blocked`), never as `Applied`.
- **You are the authority on your own facts** — the profile is truthful by construction; the
  agent never invents an employer, metric, certificate, or date that isn't in it.

---

## A note on responsible use

This automates *your* applications with *your* accounts and *your* truthful information.
Respect each site's terms of service and rate limits (the drivers pace themselves and honor
per-board cooldowns), only apply to roles you'd genuinely take, and never misrepresent
yourself. Automating dishonest or spammy applications is out of scope and unsupported.
