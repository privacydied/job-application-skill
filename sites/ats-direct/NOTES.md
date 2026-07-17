# ATS-direct — employers' own boards, no aggregator in the middle

Not a job board. This feed reads the **public listing API of each employer's own ATS**, for
the six ATSes that accept an application with **no candidate account**: Greenhouse, Lever,
Ashby, Workable, SmartRecruiters, Recruitee.

## Why it exists

Every aggregator channel (Adzuna / WTTJ / The Dots) sources fine and then dies at the
**downstream employer-ATS account wall** — you find the job, click Apply, hit a login for an
ATS you have no account on. This inverts that: it sources *from the ATSes the skill already
drives*, so each row is submittable in principle and `ats_hint` names the exact driver
(`sites/greenhouse|lever|ashbyhq|workable|smartrecruiters|recruitee/`). It's also fresher —
a role hits the company's ATS days before it propagates to LinkedIn/Indeed.

## Usage

```bash
python3 sites/ats-direct/scripts/feed.py                       # every watched company, London
python3 sites/ats-direct/scripts/feed.py --what "designer OR ux" --where London
python3 sites/ats-direct/scripts/feed.py --sector music,design # filter by companies.csv tag
python3 sites/ats-direct/scripts/feed.py --ats greenhouse      # one ATS only
python3 sites/ats-direct/scripts/feed.py --remote              # remote-only
python3 sites/ats-direct/scripts/feed.py --verify              # probe every slug, report dead
python3 sites/ats-direct/scripts/feed.py --list-companies
```

No browser, no credentials — plain HTTPS GETs, ~68 companies concurrently in ~3s. Runs from
cron/CI. Yield: ~1,430 London postings / ~3,200 unfiltered.

## Endpoints (all keyless)

```
greenhouse       boards-api.greenhouse.io/v1/boards/<slug>/jobs?content=false
lever            api.lever.co/v0/postings/<slug>?mode=json
ashby            api.ashbyhq.com/posting-api/job-board/<slug>
workable         apply.workable.com/api/v1/widget/accounts/<slug>?details=true
smartrecruiters  api.smartrecruiters.com/v1/companies/<slug>/postings
recruitee        <slug>.recruitee.com/api/offers/
```

## companies.csv

`slug,ats,name,sector`. **One row per company** — several firms answer on two ATSes
(Skyscanner, Wayve, TooGoodToGo, Peak), and listing both double-sources the same job under
two ids. A test enforces this. Re-check with `--verify`; a dead slug is skipped with a
warning, never a hard failure.

To add a company: find its careers page on one of the six ATSes, take the slug from the URL,
then `feed.py --verify --companies <slug>`.

## ⚠️ Sourcing ≠ submitting

The account-less premise holds for **sourcing**. It does **not** mean the submit goes
through — each ATS gates its submit button differently:

- **Greenhouse ✅** submits (reCAPTCHA v2 = sanctioned; `recaptcha.py`). Proven end-to-end.
- **Lever ⛔** hCaptcha, **Ashby ⛔** spam-flags valid forms, **Workable ⛔** Turnstile.
- SmartRecruiters / Recruitee: untested.

**Route submissions to Greenhouse first**; treat other rows as sourced-only until proven.
Some employers additionally require an **anti-AI attestation** (Canonical) — never tick it.
Full detail: `references/ats-apply-surface.md`.

## searches.csv

**Exactly one row** (`atsdirect,all families,`). pipeline's arg-builder only receives `nav`,
never `query`, so per-family rows can't pass a `--what` — five family rows just re-fetch all
68 companies five times for the same result. One pass returns everything; precheck screens.
