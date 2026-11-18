# adzuna.co.uk ("Adzuna") — site notes

Job-board aggregator, usually reached as a hop mid-flow — e.g. LinkedIn's external
"Apply" redirected here before handing off to the real destination ATS (Workable, in
the Solirius Reply / User Researcher case, 2026-07-13). Adzuna's own "Easy Apply" /
"ApplyIQ" features require a logged-in Adzuna account.

## Login: EMAIL/PASSWORD (you@example.com) — NOT Google OAuth. Site-specific exception to the general Google-first rule.
**Verified 2026-07-13, do not change without re-verifying live.** SKILL.md's general
rule is to prefer Google OAuth when a site offers it — **this site is the confirmed
exception.** Adzuna's ApplyIQ apply form validates the application's email field
against whatever account is logged in, and **refuses any value that doesn't match**
("This doesn't match your log in email address"). Logging in via Google OAuth signs
the session in as `you@example.com`, which then blocks the real applicant email
(`you@example.com`) from ever being entered. **Always use the email/password account**:
`you@example.com` / `[REDACTED — see ats-credentials.csv]` (current, working, in `ats-credentials.csv` row
`adzuna.co.uk` — an earlier password on that row was wrong and has been replaced; if
login fails, the credential itself is the first thing to check, not OAuth as a
fallback). If already logged in via Google from a prior session, click **Logout**
(top-right) and log back in with email/password before applying.

## Apply flow — Solirius Reply / User Researcher (4438932407), verified live 2026-07-13
Reached via LinkedIn: Apply → `linkedin.com/safety/go/?url=...adzuna.co.uk...` → Adzuna
job page → "Apply for this job" → ApplyIQ (email/password gate above, not a direct
Workable handoff).
- **"Apply for this job" on the job *details* page is a no-op via `click-follow`**
  (`outcome: no_change`) — navigate directly to the `/apply?...` URL instead (extract it
  from the `href` of the link matching `jobs/details/.../apply`).
- **reCAPTCHA v2 (checkbox AND image-grid) is present on the ApplyIQ form and auto-solves
  under the skill's standing permission (not a per-posting opt-in):**
  - checkbox → `sites/_common/scripts/recaptcha.py click` (frame-piercing click on
    `#recaptcha-anchor`) — returned `PASSED` with a green checkmark. If `click` reports
    `CHALLENGE` (an image grid opened), run `recaptcha.py solve-grid`, read the cropped
    challenge screenshot with vision, then `recaptcha.py solve-grid --tiles "<idx>"`.
  - invisible badge → no checkbox to click; run `recaptcha.py wait-token` right after the
    real Submit to confirm the token populated.
  Before Submit, **verify the green checkmark (or solved grid) via screenshot** — the JS
  `g-recaptcha-response` token is not reliable on its own. A leftover `api2/bframe`
  iframe can make `recaptcha.py detect` report `challenge open: True` even when only
  the checkbox is showing (expired verification, not a real re-challenge) — trust a
  screenshot over the raw JS state before assuming it needs re-solving. Turnstile (now auto-solved via `turnstile.py`) /
  hCaptcha stay a hard stop.
- A persistent **cookie-settings banner** makes `click-follow` report `unhandled_dialog`
  and can appear to intercept Submit clicks — usually harmless (submit still goes
  through underneath it), but if a click seems swallowed, dismiss the banner first (no
  plain "Accept" button in the DOM — it's a non-blocking banner, just click past/around
  it) and retry.
- Confirmation heading after submit: `Application submitted: <Role>`.

## Native ApplyIQ driver — `scripts/apply.py` (verified live 2026-10-23: Mercor x2, Square One)
- Two Adzuna apply link shapes on `/details/<id>`: `.../details/<id>/apply?aztt=…` = NATIVE
  ApplyIQ form (drivable); `/jobs/land/ad/<id>?aztt=…` = external redirect to the employer /
  CV-Library / Reed / jobs-in-football etc. (follow it, then use that board's driver — Reed is
  excluded). `apply.py <id>` reports `EXTERNAL` for the latter and never drives it.
- `apply.py <id> [--cv family-design.pdf] [--answers a.json] [--portfolio dz-portfolio.pdf]
  [--submit]`: without `--submit` it fills + lists every field/answer and STOPS; with it, solves the
  reCAPTCHA checkbox (`recaptcha.py click`), uses a TRUSTED click on "Submit Application"
  (a JS `.click()` bounced), waits for `Application submitted`, writes `confirmation.txt`, and
  logs `Applied` with proof. Saved CVs live in the Adzuna account (`select[name=cvId]`), picked
  by filename — no per-application upload.
- Unknown employer screeners are never guessed: the driver prints `UNRESOLVED` and exits 7.
  Opinion/personal essays ("3 words that describe you", "how has AI changed your work"), SC/DV
  vetting questionnaires and nationality-history blocks are the applicant's own — log Blocked/Skipped.
- Some employers add a REQUIRED unnamed `input[type=file]` (Costello Medical "portfolio of work –
  if a file, upload here") whose label is empty ("Please choose a file for"). `--portfolio` attaches
  `uploads/dz-portfolio.pdf` to it, but Costello still bounced "Please review the required fields"
  after the attach (2 attempts) — left Blocked; likely needs a human-trusted file pick.
- The screener bank answered `salary expectation` with 65000 for a £28–33k Digital Designer role:
  pass the advertised band in `--answers` rather than trusting the bank on pay questions.

## `/jobs/land/ad/<id>` needs its `?aztt=` query + AWS-WAF-style human check (2026-11-17, localhost camofox)
- Stripping the query from a `/jobs/land/ad/<id>?aztt=…` href lands on **"Page not found"** — always
  follow the FULL href (query included), never `href.split('?')[0]`.
- ~14 back-to-back land/ad navigations in one process tripped an orange **"Let's confirm you are
  human — Begin"** interstitial (AWS WAF CAPTCHA style; no Turnstile/reCAPTCHA iframe). It is NOT on
  the sanctioned auto-solve list → hard halt + VNC. Pace land/ad follows (one per posting, inside
  that posting's drive), don't bulk-classify them.
- Classify native vs external from the `/details/<id>` page instead (no WAF hit there): native
  ApplyIQ = `/details/<id>/apply` link; external = `/land/ad/<id>?aztt=…`. 2 of 16 queue rows were
  native (JUARA IT, Zipwater) — those need the Adzuna website login, and there is currently NO
  `adzuna.co.uk` row in ats-credentials.csv (only `adzuna-api`). Adzuna verification mail must go to an
  IMAP-readable mailbox (only the gmail `imap` row is live; the outlook row is disabled).


## 2026-11-17 run learnings (Jane)
- Most queue rows' "Apply for this job" link is `/jobs/land/ad/<id>?aztt=...` — an EXTERNAL redirect (CV-Library, devitjobs.uk, etc.), not native ApplyIQ. `apply.py` reports NOFORM and lands on the third-party board; those need that board's own account/driver.
- Only `/jobs/details/<id>/apply?aztt=...` is the native ApplyIQ form; it requires a logged-in Adzuna session (email/password account, not Google SSO).
- Live JD can contradict queue metadata: 5964344754 was tagged "London, UK" but landed on a Greenhouse req in **London, Ontario, Canada** — always read the destination before driving.
## 2026-11-18 apply-run recoveries (localhost Camofox)
- **CFX_USER must NOT be unset when non-empty.** `.jobenv.run` carries `CFX_USER=<profile id>` (a browser-profile id, not a remote host) and `CFX_URL=http://localhost:9377`. Running `unset CFX_URL CFX_USER` after `source` makes `cfx.sh` fall back to `job-apply`, so `list-tabs` returns `[]` and every eval says `Tab not found` even though `/health` shows `activeTabs:1`. Only unset *empty* values.
- **reCAPTCHA v2 frame click can report false fingerprint-distrust.** `recaptcha.py click` returned `NO-CHANGE … hand to the user`, but a trusted coordinate click on the anchor iframe (iframe rect x+28, y+39, after `window.scrollBy`) populated a 2489-char token. Try a trusted coordinate click (`cfx.sh click-xy`) before calling it a wall.
- **The "no adzuna.co.uk credential row" Blocked reason is STALE.** `ats-credentials.csv` now has that row, and the ApplyIQ form is logged in as the real applicant email. Do not re-log that reason without a live probe.
- Native `/details/<id>/apply?aztt=` form may have **no saved `select[name=cvId]`** — only `input[name=cvFile]`. `apply.py` now uploads a PDF staged in `uploads/` and fills `firstName`/`lastName` from `apply-defaults.json` (the old lowercase lookup keys never matched camelCase form names).
- WAF trip confirmed again at ~7 sequential `land/ad` follows: orange "Let's confirm you are human — Begin" interstitial (no Turnstile/reCAPTCHA iframe) → non-sanctioned CAPTCHA, full halt. Classify from `/details/<id>` pages, which are clean.
- **BRC eploy registration wall (2026-11-18, row 5965576907):** British Red Cross `brcweb.eploy.net/vacancies/<id>` Apply opens a same-origin `registration.aspx?...&modal=true` iframe. Two full fill+submit attempts (all required fields set, snapshot verified before click) still returned ASP.NET "required field"/"email invalid" errors — the postback does not bind values set via native setters in the modal. Logged `Blocked` after the 2-attempt cap. The declaration is only "information is accurate" (not a binding wall); there is no CAPTCHA. Do not keep re-driving this board without a real fix.

