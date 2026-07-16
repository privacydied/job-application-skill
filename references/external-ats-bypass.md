# External-ATS bypass — "Apply on company site / website" (Indeed & LinkedIn)

Both Indeed and LinkedIn surface two apply buttons per posting:
- **"Apply with Indeed" / "Easy Apply"** — the board's own ATS. Indeed's binds the
  logged-in email (gmail SSO → wrong application email; needs email/password login).
  LinkedIn's Easy Apply is shadow-DOM — drive with `sites/linkedin/scripts/easyapply.py`.
- **"Apply on company site" / "Apply on company website"** — routes to the employer's
  **external ATS** in a new popup tab. **No board login needed for the application
  itself** once the session is logged in (gmail SSO is fine — the application email is
  entered on the external form as you@example.com, not bound to the board account).

## Why this matters for "reach 10"
Indeed/LinkedIn *browsing* is guest; *applying* via "Apply with Indeed" needs login. But
**"Apply on company site" roles are fully applyable with only a logged-in (even gmail
SSO) session** — they bypass the email/password requirement entirely. Prefer them when
you need applications without an email/password board login. (2026-07-14: this got the
run from 6→8 applied via SThree's sthree.com ATS, no Indeed email login.)

## Flow (verified)
1. On the JD, click the **"Apply on company site"** link (Indeed: a real `<button>`,
   text "Apply on company site (opens in a new tab)"; LinkedIn: a link "Apply on company
   website", often `@e23` in the snapshot — NOT the sidebar "Easy Apply" cards).
2. The external ATS opens in a **popup tab** — find it with `cfx.sh find-popup` (filter
   out `about:blank` and the board's own URLs). Re-point `CFX_TAB` to it.
3. Drive the external ATS directly: upload CV (hidden `input[type=file]` → `/upload`
   endpoint with `selector:"input[type=file]"`), fill fields by id/name via `cfx.evaluate`
   (set `.value` + dispatch `input`/`change` events), submit.
4. Verify success by URL/confirmation text, then `log-application.py`.

## Per-ATS findings (2026-07-14)
- **SThree / sthree.com** — 2-step: (1) Upload CV dropzone (`input[type=file]`,
  `dz-hidden-input`), (2) details: `forename`,`surname`,`email`,`telephone`,`mobile`,
  `postalcode`,`city`, native `country` `<select>` (addressable — set by option text),
  `privacyagree` checkbox. Submit button text **"Apply"**. Success URL `…/apply/thanks/`.
  **Duplicate-jk trap:** SThree serves the SAME advert under several Indeed jks (UI
  er000736 + UX er000426 each appeared as 2–3 jks); all jks open the same ATS URL →
  apply ONCE. Indeed `feed.py` dedups by jk only, not content — check the ATS URL matches
  before applying a 2nd jk.
- **micro1.ai** — **UNSTABLE / AVOID.** Form state corrupts on every re-render: typed
  values land in the wrong fields (First name got "w.linked", Email got the phone digits),
  resume upload doesn't survive a "Next" click. Treat as Blocked, not retriable.
- **Hiresome (yohrconsultancy.hiresome.ai)** — stable text fields + resume upload work,
  BUT the **phone country is a react-select stuck on +91 (India)** that won't open via
  `click-xy` (same unaddressable-handle wall as MoJ's Country `<select>` — see
  SKILL.md §MoJ + CAPABILITY-GAPS). Required phone can't be set to +44 → Blocked.

- **Free-Work (free-work.com)** — login-gated: the "Apply" button is inert until you
  Sign in / Create account (no guest apply). On signup with `you@example.com` it
  returned **"This value is already used"** — the account already exists from a prior
  session but the password was never recorded in `ats-credentials.csv`. **Escalate,
  don't recreate:** you cannot make a 2nd account with the same email, and you can't
  sign in without the password. Fix = user resets the password (email access) or
  supplies the existing one. **When creating ANY ATS account, immediately append
  `site,email,password,date` to `ats-credentials.csv`** (SKILL.md pre-approves
  email/password signup with you@example.com) so a later session isn't blocked the same
  way. If signup says the email is taken and no cred is on file, treat as a hard stop
  needing user input — NOT a retry-able create.

## ⛔ Indeed "Apply with Indeed" → SmartApply = Cloudflare Turnstile WALL (HARD BLOCKER)
Do NOT attempt Indeed's own ATS. Clicking **"Apply with Indeed"** routes to
`smartapply.indeed.com/beta/indeedapply/...` (Indeed's SmartApply multi-step wizard:
resume-selection → questions → review → submit). On camofox this lands on Indeed's
**"Additional Verification Required"** page (Cloudflare Turnstile interstitial —
`document.title == "Just a moment..."`, body reads "Additional Verification Required"
+ a Ray ID). **This is the SAME unsolvable-via-camofox Turnstile the memory note
warns about.** It is a HARD BLOCKER:
  * Log the role `Blocked` with reason "Indeed Cloudflare Turnstile — unsolvable via
    camofox (user device needed)".
  * Do NOT loop/retry — fast retries compound the risk score (see SKILL.md Turnstile
    cooldown note).
  * Notify the user: these 5 roles (Digital Content Editor / DevOps / Cloud Native
    DevOps / Platform Engineer / IT Technician, all `uk.indeed.com/viewjob?jk=...`)
    need to be applied **on their own device**, then I log them.
This is DIFFERENT from "Apply on company site" (which is fine — external ATS, no
Indeed ATS involved). The split matters: when Indeed postings surface, prefer
"Apply on company site" roles; treat "Apply with Indeed" as a wall, not a flow to
automate. (LinkedIn Easy Apply is the volume path; Indeed SmartApply is not.)

## Operational pitfall — clicking "Apply on company website" on LinkedIn
The JD page has MULTIPLE buttons; a naive `cfx.click_and_follow(ref=...)` (or
`cfx.evaluate` matching the first `<button>`) can hit the **account/user menu button**
at top instead of the apply control, opening the account dropdown instead of the ATS.
The real apply control is the `link` (not `<button>`) labelled "Apply on company
website" — usually `@e23` in the snapshot, distinct from the sidebar "Easy Apply"
cards. Target it specifically: snapshot, grep for `apply on company website`, take its
ref, then `click_and_follow(ref=that_ref)`. On Indeed the control is a real `<button>`
with text "Apply on company site" — same care (find by exact text, not first button).

## Coordinate-click technique (last resort for unaddressable controls)
When a control gets **no `@eN` ref** in the snapshot and `cfx.evaluate` chokes on its node
(heavy `<select>`, react-select), try: `cfx.sh shot` → vision-locate the control's (x,y)
→ `cfx.sh click-xy <x> <y>` to open it → `shot` again → click the option by coordinate.
This bypasses the ref/evaluate walls. **Caveat:** react-select *country pickers* often
ignore synthetic coordinate clicks (Hiresome failed) — it's a last resort, not a guarantee.

### Definitive "this control is truly unaddressable, stop" diagnostic
Do NOT loop on a click-xy that silently misses. Proof it's a real wall, not a flake:
probe a **nearby small element** with the SAME `evaluate` call shape
(`getBoundingClientRect()` / `.value`). If the nearby element evaluates fine but the
target node returns **None**, the target is `display:none` / detached / hidden behind a
styled sibling widget (e.g. MoJ Country `select[name=19308]`, Hiresome phone `+91`
react-select) — NOT a backend/REST flake. The real trigger is a sub-element (flag icon
/ caret) the box-coordinate misses. **Stop, mark `Blocked`, route to VNC.** Both the
HMCTS MoJ Country wall and the Hiresome phone wall were genuinely unaddressable and each
cost a long stuck run when re-attempted programmatically.
