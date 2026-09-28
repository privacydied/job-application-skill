# current-vacancies.com ("Networx Recruitment" ATS) — site notes

Every instance lives at `<subdomain>.current-vacancies.com` (e.g. `vam.current-vacancies.com`
for the V&A Museum). Reached both as a direct board listing and as an "apply on company
website" redirect (e.g. from an Adzuna listing for Bank of China via IT Centre Europe).
Multi-step wizard with a left sidebar (Contact Details → Application Details → Equal
Opportunities → Declaration → Submit & Review), each step gated behind a green
**"SAVE AND CONTINUE"** button (raw text, all caps — match by exact innerText).

## Account creation + email verification (real gate, real fix)
Self-registering an account (email + generated password → `ats-credentials.csv`) works with
no CAPTCHA. But **Submit & Review is blocked until the email is verified** — hitting it early
shows "Unable to Submit the Application… You are unable to submit any applications until your
account is verified", with a "Click here" **button** (not `<a>` — query by innerText across
all leaf elements, not `querySelectorAll('a')`) to resend the link, and a modal confirming
"A verification email has been sent to: <address>".

**This is a real, fixable gate — not a hard stop.** Networx emails a **verification LINK**
(not a short code) to the real applicant mailbox:
- From: `"<company contact>" <donotreply@networxrecruitment.com>`
- Subject: `Please verify your email address`
- Link shape: `https://<subdomain>.current-vacancies.com/OneAccount/Account/CandidateVerification?Token=<uuid>&CandidateID=<id>&cid=<n>`

`scripts/fetch_verification_code.py --link` did NOT catch this link — its `_VERIFY_LINK`
regex only matches URLs whose query string contains one of a fixed set of param names
(`verificationCode`, `verify_token`, `magic`, `confirm_token`, `login_token`, `auth_token`,
`UsersPasswordQueueID`, `CandidateGUID`, `reset_token`, `resetpassword`). Networx's param is
**`Token`** (bare), which isn't in that list, so `--link`/`--token` return `NO_CODE` here even
though the email is genuinely in the mailbox. Worked around this session with a direct IMAP
read (`email_ingest._connect()` + manual `href=` regex scan for `verify`/`confirm`/`token` in
the raw HTML body) rather than waiting on a code-box UI that doesn't exist on this ATS.
**TODO for a future session:** add `Token=` (bare, case-sensitive as Networx sends it) to
`_VERIFY_LINK` in `scripts/fetch_verification_code.py` so `--link` catches this ATS directly.

**Recipe:**
1. Fill and save through to Submit & Review; hit the "Unable to Submit" gate.
2. Click the "Click here" button (button, not anchor) to (re)send the verification email.
3. Pull the link from the mailbox (IMAP; `ats-credentials.csv` has an `imap...` row) — scan
   the raw HTML body for `href="..."` containing `verify`/`confirm`/`token`, case-insensitive.
4. `cfx.goto()` the link directly (no login/session needed — the token in the URL is the
   auth). Lands on "Confirm Your Account" → "Thank you for verifying your email address. You
   can now submit applications…" with a "My Account" button.
5. Navigate back to the in-progress application (its `ApplicationDetails/<id>?cid=<n>` URL,
   or via My Account → the job's saved/in-progress application) and retry Submit & Review.

## Form mechanics
- Radio/select values are set via native-setter + `input`/`change` dispatch, same pattern as
  every other ASP.NET-flavoured ATS in this repo — plain `.click()` on a radio works fine
  (verified: `Are you a current employee?`, `Commutable distance?`, `disability`, `caring
  responsibilities`, `still employed here?` all responded to a simple `.click()` on the
  correct-labelled `input[type=radio]` inside its question block).
- ⚠️ **Substring/prefix block-matching for radio questions is fragile when a CONDITIONAL
  question shares option text with its parent** (verified live, V&A Content Designer,
  2026-09-28): "Are you a current V&A employee?" (Yes/No) sits directly above a conditional
  "Have you successfully passed your probation?" (Yes/No) that only renders when the parent
  is "Yes". A `pick(qtext, opt)` helper walking up from each radio to find the nearest block
  whose `innerText` STARTS WITH the question text, then picking the option by label inside
  that block, mis-fired and set the PARENT to "Yes" (should have been "No") when both
  questions were driven in one batched call — almost certainly because the conditional
  question's fresh render shifted which ancestor `<div>` scored as the "nearest" match.
  **Fix that verified clean:** drive ONE radio-group question at a time, screenshot after
  each, and for a stubborn mis-click use `document.elementFromPoint(x,y).click()` against the
  exact on-screen coordinates read off the screenshot rather than trusting a second
  substring-match pass.
- Two separate "Education" mini-forms can appear on Application Details: a repeatable
  School Name/Start-End/Qualification Name/Type/Result/Date-Obtained block (`Add
  Education`/`Add Qualification` buttons, fields named like `SchoolName0`, `StartDate0`,
  free-text `mm/yyyy`), AND a separate single free-text summary block ("highest level of
  Education" select + native `<input type=date>` start/finish + a "Qualification and Grades"
  textarea) — fill both; they are not the same data.
- Work History: `Company Name` / `Are you still employed here?` (Yes/No) / `Start Date` /
  `End Date` (free-text `mm/yy`, NOT `mm/yyyy` here) / `Job Title` / `Responsibilities /
  Duties` / `Reason for leaving`, plus a repo-wide required "tell us about any significant
  gaps in your employment history" textarea below the `Add Employment` button.
- Equal Opportunities page has one two-level ethnicity control that LOOKS cascading (a broad
  group `<select>` plus two more narrowly-scoped `<select>` elements with tiny option lists
  like "Black Scottish or Black British" / "Any other ethnic group | Arab") but verified live
  that picking the broad group (e.g. "Mixed Other") is sufficient — the other two selects are
  unrelated/inactive for that branch and can be left alone; don't force-fill them blind.
- Declaration step needs BOTH a "The information given is complete and accurate" checkbox AND
  a separate native `<input type=date>` "Date of Declaration" AND a second, unrelated
  "I have finished answering this section" checkbox at the bottom — three separate widgets,
  easy to miss the date field since it renders with placeholder `mm/dd/yyyy` like an empty
  required text field.
