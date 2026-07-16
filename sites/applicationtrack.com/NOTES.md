# applicationtrack.com (VacancyFiller / "Application Track") — verified site notes

A UK public-sector ATS. **MI5 (the Security Service)** recruits here under
`appcentre-a18` / `brand-5`. Other orgs use their own `appcentre-<id>`.

## URLs
- **Job board:** `https://recruitmentservices.applicationtrack.com/vx/lang-en-GB/mobile-0/appcentre-a18/candidate/jobboard/vacancy/1`
  — all current vacancies, with a **Department** filter (Admin, Analysis, Cyber, Engineering,
  Technology Roles, Information Assurance, Intelligence, Maths & Cryptography, etc.). Job
  titles link to a detail page.
- **Vacancy detail:** `.../candidate/so/pm/1/pl/4/opp/<ref>-<slug>/en-GB` (public — no login).
- **Apply / Login / Register:** applying requires a **candidate ACCOUNT** (top-right
  "Login or Register"). You cannot reach the application form without one.

## Sourcing
The board is server-rendered; scrape vacancy titles/`opp/<ref>` links from the jobboard page.
Filter by Department for on-profile roles. There is no public JSON feed — HTML only.

## ⛔ MI5 (and any security-vetted employer): DO NOT auto-complete the application

MI5/SIS/GCHQ recruitment is **not** a normal ATS fill. Hard rules:

1. **A candidate account is required** and creating it needs the real applicant (email
   verification; a security service may add checks) — the agent cannot register/verify it.
   Treat this like a 2FA login: open a browser and let the user register/sign in.
2. **The application must be completed PERSONALLY and truthfully.** Motivation, competency,
   and "why MI5" answers require the candidate's own genuine words. **Never auto-generate
   application content for a security-vetted role** — MI5 vetting is built on personal
   integrity, so a fabricated or AI-written application is a serious integrity risk that can
   end the candidacy (and it violates the skill's no-fabrication rule regardless).
3. **What the agent MAY do (only with the user driving the account):** fill FACTUAL /
   eligibility fields from the profile — name, contact, nationality/right-to-work, and the
   clearance screener **answered honestly**: British citizen; no current SC/DV; holds an
   enhanced DBS; **willing to undergo Developed Vetting (DV)** — DV is granted THROUGH the
   role, not required on day one. Do NOT claim clearance the applicant doesn't hold.
4. **Eligibility to note per role:** British citizen (sole/dual varies by role — read the
   vacancy), primarily **office-based** (London/Manchester; limited remote), and MI5 asks
   applicants to keep the application **confidential** and apply from a **private connection**.

Net: for MI5, the agent's job is to (a) surface on-profile roles and (b) assist the user with
the factual fields once THEY have registered/logged in and written the personal content — not
to submit an application autonomously.
