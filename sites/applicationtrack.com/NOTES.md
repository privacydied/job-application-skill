# applicationtrack.com (VacancyFiller / "Application Track") — verified site notes

A UK public-sector ATS. **All THREE UK intelligence agencies recruit here on this ONE
platform** (MI5, MI6/SIS, **and GCHQ** — corrected 2026-07-17, GCHQ 3780 submitted here),
each as a separate `appcentre`/`brand` tenant — the ATS mechanics + the ⛔ integrity rules
below are IDENTICAL across them; only the tenant path differs:

| Org | Careers site | Tenant (job board) | Verified |
|-----|--------------|--------------------|----------|
| **MI5** (Security Service) | mi5.gov.uk | `appcentre-a18` / `brand-5`, `.../jobboard/vacancy/1`; vacancy `.../so/pm/1/pl/4/opp/<ref>` | 2026-07-16 |
| **MI6 / SIS** (Secret Intelligence Service) | **sis.gov.uk** (`/careers/`) | `appcentre-2` / `brand-2` job board `.../appcentre-2/brand-2/candidate/jobboard/vacancy/2`; vacancy `.../appcentre-2/brand-6/xf-<hash>/candidate/so/pm/1/pl/5/opp/<ref>` | 2026-07-17 |
| **GCHQ** | gchq-careers.co.uk | `appcentre-3` / `brand-7`, board `.../appcentre-3/brand-7/user-<id>/candidate/jobboard/vacancy/3`; **apply-start URL = `.../opp/<REF>/apply/en-GB`** (the detail page has NO visible Apply button — the action is a hidden form; navigate straight to `…/apply/en-GB`) | 2026-07-17 |

**⚠️ ONE candidate account spans all three** — the `ats-credentials.csv` MI5 applicationtrack
row (email in that gitignored file) **logs into GCHQ's tenant too** (lands on
`appcentre-3/brand-7/user-<id>`, with the applicant's name in the welcome header). Do NOT
self-register a GCHQ account or treat GCHQ as an "account wall" if the MI5 row exists. (Parliament / TfL / BBC are
DIFFERENT ATS vendors — those do need their own accounts.) Other public-sector orgs use their
own `appcentre-<id>`.

## ⚙️ camofox `/evaluate` gotcha (cost a prior agent ~5 firings — do NOT relearn it)
`cfx.evaluate` / `cfx.sh eval` runs the JS as an **EXPRESSION**, like a devtools one-liner.
A bare `return x;` or a multi-statement `var … ; …` block returns `{"error":"Internal server
error"}` — a FALSE failure repeatedly misblamed on "camofox crashing on reflective setters."
Wrap statements in an IIFE that returns: `(function(){ …; return x; })()`. The reflective
native value-setter works reliably in expression form. Litmus: if `1+1` evaluates but your
real eval 500s, you have a `return`/multi-statement outside an IIFE — not a camofox limit.

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

## Applying (MI5 / MI6-SIS) — agent fills it; user watches via noVNC + consents to submit

**User-authorised, standing (2026-07-16/17):** fill these applications like any other — from the
applicant's **legitimate profile** (`references/applicant-profile.md`), with the applicant
watching live via noVNC and giving the final go before submit. Same flow as MI5 Cyber Research
Engineer (below) and the NHS/Reviva applications. The only hard rule is the skill-wide one:
**everything must be true** — use the profile's real facts; never invent a certificate, employer,
metric, grade, or clearance the applicant doesn't hold. Competency/"why" answers are drafted
grounded in the applicant's real experience (the applicant reviews them in noVNC before submit).

Operational facts to fill honestly:
- **Account required per tenant** (email-verified; MI5 and MI6 accounts are separate — a MI5
  login does NOT carry to MI6). Creds in the gitignored `ats-credentials.csv`; treat first-time
  sign-up like any login gate.
- **Clearance screener, answered truthfully:** British citizen; current SC/DV as the applicant
  actually holds (usually none); DBS status as held; **willing to undergo Developed Vetting** —
  DV is granted THROUGH the role, not required on day one.
- **Eligibility:** British citizen (sole/dual varies by role — read the vacancy); largely
  office-based (London/Manchester; limited remote); the agencies ask applicants to keep the
  application **confidential** and apply from a **private connection** — honour that.
- **Final submit:** the applicant gives the go via noVNC (they can eyeball the drafted answers).

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
- **⛔ THE SUBMIT BUTTON ONLY RENDERS WHEN EVERY SECTION VALIDATES** (verified 2026-07-17, MI5
  SRE 3772 — this cost hours). Page 7 (Submit) normally shows ONLY `back_button`. Once all
  sections are complete it also renders **`button[name=submit_button]`** ("Submit") — native
  `.click()` it and you get "Thank you, your application has been submitted". **If the submit
  button is absent, do NOT hunt for a hidden control / jump-link / `save_and_goto_location` —
  a SECTION IS INCOMPLETE.** Filling+saving page 7 (memorable word/declaration persist fine)
  is NOT the submit; status stays `Incomplete` until every section passes.
- **✅ Read the REAL per-section status from the tracker link's PARENT class** (the icons/
  innerHTML are empty — that's why they seemed "unreliable"):
  `a.jump-to-page` → `parentElement.className` = `tracker_stat_complete` /
  **`tracker_stat_incomplete`** / `tracker_stat_mandatory_complete`. This pinpoints the
  blocking section instantly — use it BEFORE anything else when Submit won't appear.
- **⛔⛔ ANTI-PATTERN — NEVER chase a `display:none` field. RUN `diagnose.py` FIRST.**
  Encoded as a tool: **`python3 sites/applicationtrack.com/scripts/diagnose.py`** (read-only;
  needs `CFX_TAB` on the eform). It prints per-section status + the site's own
  `a.eform-jump-to-field` culprits for each incomplete section, with each culprit's
  type/options — so you fill named fields from the profile instead of guessing.
  Verify the detector itself any time with **`diagnose.py --selftest`** (injects a synthetic
  incomplete-section + hidden-trap DOM and asserts the probes catch both; no live app needed).
- **✅ For the full unblock, drive it with `autofill.py`** —
  **`python3 sites/applicationtrack.com/scripts/autofill.py`** (needs `CFX_TAB` on the eform).
  The STRUCTURAL fix: it walks the section tracker as its work-list (re-read each pass), fills
  the site-named culprits from a profile ruleset (citizenship / age / UK-residency /
  apprenticeship / jobshare / bankruptcy / willing-to-be-vetted), **skips every `display:none`
  field by construction**, and **cannot loop** — a progress guard stops the instant a pass
  fills nothing new on the same incomplete set. It **never submits and never fabricates**:
  unmatched culprits and the user-only final page (memorable word + hint + declaration) are
  reported as `needs_human` and handed back. `--dry` classifies without changing anything;
  `--selftest` proves all four guarantees against a mock (no live app). Extend its `RULES`
  ONLY with facts verifiably true from `references/applicant-profile.md`.
  **Why this exists (GCHQ 3780, 2026-07-17):** a prior agent (Hermes) spent *five firings*
  concluding a hidden field (`datafield_17712`, grandparent `display:none`) was a
  "provably unreachable VacancyFiller form bug" and declared the whole application
  unsubmittable. **Every part of that was wrong.** The Equal Opportunities section holding
  17712 was *already complete*; the real blockers were three OTHER sections
  (Personal Details / Minimum Eligibility / Security Vetting), each missing ONE plain
  eligibility answer (British-citizen / over-17 / UK-7-of-10-yrs / agree-to-vetting). It
  submitted in minutes once the section tracker was read. **Rules, non-negotiable:**
  (1) A field whose computed `display` is `none` (walk up ~6 ancestors) is **NEVER the
  blocker** — VacancyFiller hides fields whose reveal condition doesn't apply, and no human
  could fill a hidden field either. (2) The blocker is ALWAYS a *section* marked
  `tracker_stat_incomplete`; its `a.eform-jump-to-field` anchors name the exact visible
  fields to fill. (3) If a genuinely-needed field is hidden, the fix is upstream (set the
  parent select whose value REVEALS it, then re-scan) — never force `display:block`
  (VF's render loop reverts it) and never `execCommand`/synthetic-key a hidden input.
  (4) Spend **at most one** pass looking at any hidden field, then go back to `diagnose.py`.
  "Provably unreachable field" is almost always "wrong section — I never read the tracker."
- **⚠️ Hidden conditional required fields** — selecting **Ethnic Origin = "Mixed - Other"**
  reveals a required free-text **"Please specify"** (`datafield_17697_1_1`) that does NOT
  appear in a first field scan and silently keeps Equal Opportunities `incomplete`. Re-scan a
  section AFTER setting its selects.
- **⚠️ Label mis-detection on Personal Details**: `datafield_31846_1_1` is the **POSTCODE**
  (needs CAPITALS, e.g. `[postcode]`) even though naive label-walking reads it as "Email". The
  form-wide "There is a problem" banner is generic — resolve the real field via the
  `a.eform-jump-to-field` link's `href="#datafield_…"` anchor, which names the exact culprit.
- Buttons per page: pages 1–6 = **`continue_button`** ("Save and continue"; NOT "Submit" —
  searching for "submit" matches nothing and the page silently never advances); page 7 =
  `back_button` + `submit_button` (the latter only when complete).
- **Final Submit section is USER-ONLY**: a memorable word (phone-security secret the agent
  should not know) + hint + the "true and complete" declaration + submit.
- **MI5's own guidance explicitly permits AI in the written application parts** (not online
  tests/interviews) — the form makes you confirm you've read it. The integrity rule above
  still stands: factual fields from the profile, personal declarations user-confirmed
  per-question, submission by the user.
- Proof: post-submit banner "Thank you, your application has been submitted" + dashboard row
  status "Under review" (screenshot both).
