# Parliament / TfL / BBC — account-wall reality (verified live 2026-07-18)

SKILL.md §ACCOUNTS says "self-register Parliament / TfL / BBC where there's no CAPTCHA."
Live verification this session shows the three are NOT equivalent:

## TfL — PROVEN self-registerable (Taleo, not SuccessFactors)
- Canonical apply host is **`tfl.taleo.net/careersection/external/...`** (Taleo), reached
  from `careers.tfl.uk` → "Find more jobs". SKILL.md's board table wrongly says
  "SuccessFactors RMK" — it is Taleo.
- **Registration works headlessly, no CAPTCHA.** Flow: job page → "Sign In" →
  "Login or register for the first time" → "New User" button → form
  (`userName`, `password`, `passwordConfirm`, `email`, `emailConfirm`) → click the
  `<input class="nav-btn" value="Register">` (NOT a labelled button — search by
  `value=='register'`, not innerText) → lands signed-in.
- Stored credential in `ats-credentials.csv` as `tfl.gov.uk (Taleo)` (username
  `[your username]`, strong password, real email — resolved from the gitignored
  config at runtime, never hardcoded here).
- **BUT inventory is operational/transport** (Network Traffic Controller, Track Operative,
  Planning Manager, Electrical Technician) — essentially ZERO on-profile design/UX/junior-mid
  roles. So TfL is a *working account* but **not a count source** for this applicant.
- Taleo TfL job *apply* still requires the account (header shows "You are not signed in"
  until registered) — guest apply is NOT available.

## Parliament — GENUINE wall (no self-registration surface)
- Hosts: `hrhoc.parliament.uk` (pds/commons) + `hrhol.parliament.uk` (lords), MHR Web
  Recruitment (iTrent). Commons stream has real vacancies (e.g. "Investigations Support
  Officer").
- The login page (`ETREC109DF.open`) offers ONLY: "Existing User Login", "Forgotten
  Password", "My Applications", "My Profile". **There is NO "create account" / "register" /
  "new user" entry point** — not in `<a>` links, not in buttons. HR/invite-only.
- Therefore "attempt registration before reporting a wall" cannot be satisfied: the surface
  does not exist. This is a legitimate login wall, NOT sandbagging. Report it once with that
  specificity; do not re-attempt.

## BBC — untested this run
- Still listed as SuccessFactors RMK. Self-registration not attempted 2026-07-18; treat as
  "account needed, attempt registration" per the general rule until verified.

## Takeaway for the 477 loop
At depth, the only account-wall board that opened was TfL — and its inventory is off-profile.
Parliament is a hard wall. Do not count TfL/Parliament/BBC as "self-registerable headroom":
TfL registers but yields nothing on-profile; Parliament cannot register at all.
