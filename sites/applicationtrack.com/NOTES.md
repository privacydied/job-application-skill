# applicationtrack.com (VacancyFiller / "Application Track") — verified site notes

A UK public-sector ATS. **Both UK intelligence agencies recruit here on this ONE platform**,
each as a separate `appcentre`/`brand` tenant — the ATS mechanics + the ⛔ integrity rules
below are IDENTICAL across them; only the tenant path differs:

| Org | Careers site | Tenant (job board) | Verified |
|-----|--------------|--------------------|----------|
| **MI5** (Security Service) | mi5.gov.uk | `appcentre-a18` / `brand-5`, `.../jobboard/vacancy/1`; vacancy `.../so/pm/1/pl/4/opp/<ref>` | 2026-07-16 |
| **MI6 / SIS** (Secret Intelligence Service) | **sis.gov.uk** (`/careers/`) | `appcentre-2` / `brand-2` job board `.../appcentre-2/brand-2/candidate/jobboard/vacancy/2`; vacancy `.../appcentre-2/brand-6/xf-<hash>/candidate/so/pm/1/pl/5/opp/<ref>` | 2026-07-17 |

(GCHQ is NOT here — it runs its own careers ATS; see CAPABILITY-GAPS if added later.) Other
public-sector orgs use their own `appcentre-<id>`.

## URLs (substitute the tenant from the table above)
- **Job board:** `https://recruitmentservices.applicationtrack.com/vx/lang-en-GB/mobile-0/appcentre-<id>/candidate/jobboard/vacancy/<N>`
  — all current vacancies, with a **Department** filter. MI6's departments (2026-07-17): Admin,
  Analysis, Apprentices & Interns, Mission Enablers, **Cyber, Engineering, Technology Roles**,
  Intelligence, Languages, **Maths & Cryptography**, Trades & Services, Security Officers,
  Specialist Roles, Building Support Services. (MI5's set is near-identical.) Job titles link to
  a detail page. On-profile departments for a design/DevOps/cyber applicant: **Technology
  Roles / Cyber / Engineering** (e.g. MI6 Technical Risk Adviser Ref. 3793, Solutions
  Architect Ref. 3726 — senior/architect tier).
- **Vacancy detail:** `.../candidate/so/pm/1/pl/<4|5>/opp/<ref>-<slug>/en-GB` (public — no login).
- **Apply / Login / Register:** applying requires a **candidate ACCOUNT** per tenant (a MI5
  account does NOT carry to MI6 — separate registration/email-verification each). You cannot
  reach the application form without one.

## Sourcing
The board is server-rendered; scrape vacancy titles/`opp/<ref>` links from the jobboard page.
Filter by Department for on-profile roles. There is no public JSON feed — HTML only. Same feed
approach works for either tenant — just swap the `appcentre`/`brand`/`vacancy/<N>` path.

## ⛔ MI5 / MI6-SIS (and any security-vetted employer): DO NOT auto-complete the application

**Applies equally to MI5 and MI6/SIS** (same platform, same rules) and any security-vetted
role. Intelligence-agency recruitment is **not** a normal ATS fill. Hard rules:

1. **A candidate account is required** and creating it needs the real applicant (email
   verification; a security service may add checks; MI5 and MI6 accounts are separate) — the
   agent cannot register/verify it. Treat like a 2FA login: open a browser, let the user sign in.
2. **The application must be completed PERSONALLY and truthfully.** Motivation, competency,
   and "why MI5/MI6" answers require the candidate's own genuine words. **Never auto-generate
   application content for a security-vetted role** — intelligence vetting is built on personal
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

## ✅ VERIFIED full flow (2026-07-16, MI5 Cyber Research Engineer — submitted, "Under review")

Server-rendered classic forms (no React) — native DOM APIs work; the traps are elsewhere:

- **Login** (`/candidate/login`): fields `input[name=user]` + `input[name=password]` (fill via
  `/type`), then **press Enter in the password field** — the LOGIN control is an `<a>` whose
  click handler doesn't reliably fire headlessly; Enter submits.
- **⛔ `form.submit()` only re-saves the page** — the Submit **button's** handler sets hidden
  `next_page_num`/`next_destination` fields, so advancing requires a **native `.click()` on the
  button** (`b.click()` works — no React here). `form.submit()` lands back on `save_page`.
- **Two eforms per vacancy**: a short Eligibility pre-screen eform; completing it native-click
  unlocks the main "Application For <role>" eform (sections: Personal Details → Minimum
  Eligibility → OOI → Adjustments → Security Vetting → Equal Opportunities → Submit). Later
  sections use proper `SAVE AND CONTINUE` buttons; the tracker's section links navigate.
- **Yes/No questions are a MIX of radios and `<select>`s** — enumerate per page; don't assume.
  Conditional follow-ups (e.g. the residence sub-questions) hide when the parent answer makes
  them moot; only fill what's visible.
- **Address line forbids commas** ("Please do not use commas") — strip them or the page
  silently fails to complete.
- **Dates are 3 selects** (Day `01`, Month `July`, Year `1995`) sharing a name prefix.
- **⚠️ The Progress Tracker icons are unreliable** — a section can show complete while a field
  is unanswered (hit live: the OOI disability select). Verify by re-visiting each section and
  reading values before the final submit.
- **Final Submit section is USER-ONLY**: a memorable word (phone-security secret the agent
  should not know) + hint + the "true and complete" declaration + submit.
- **MI5's own guidance explicitly permits AI in the written application parts** (not online
  tests/interviews) — the form makes you confirm you've read it. The integrity rule above
  still stands: factual fields from the profile, personal declarations user-confirmed
  per-question, submission by the user.
- Proof: post-submit banner "Thank you, your application has been submitted" + dashboard row
  status "Under review" (screenshot both).
