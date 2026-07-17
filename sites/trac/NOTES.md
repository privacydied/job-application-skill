# Trac (`trac.jobs` / `healthjobsuk.com`) — probe notes, no driver yet

Trac (a **Civica** product) is where NHS trust applications actually happen — `sites/jobs.nhs.uk/`
is now a pure aggregator that hands off to the trust's own ATS, and Trac is one of the common
targets (alongside Jobtrain / Oleeo / TalentLink).

**Both headline facts are bad:** sourcing is **Cloudflare bot-walled** (not merely "403 to
plain curl"), and apply is **account-walled with a reCAPTCHA on registration**. No driver is
written yet; this is the probe record.

## ⛔ Headline 1 — sourcing is CAPTCHA-walled, and that CAPTCHA is a FULL HALT

`https://www.trac.jobs/search/vacancies` returns 403 to plain curl. **Better headers do not fix
it** — they just reroute:

| URL | plain curl | full browser header set (UA + Accept + Sec-Fetch-* + `--compressed`) |
|---|---|---|
| `www.trac.jobs/search/vacancies` | 403 | 200 but **redirects to `apps.trac.jobs/`** (the login portal) — the search route is gone |
| `www.trac.jobs/` | 403 | **403**, 107 KB body |
| `healthjobsuk.com/` (public board) | — | **200** — landing page only |
| `healthjobsuk.com/job_list/ns?JobSearch_q=digital` (search **results**) | — | **403** |
| `healthjobsuk.com/job/UK/London/…/-v8079394` (a job **detail**) | — | **403** |

Every 403 body is the same interstitial:
> "Site unavailable — **Trac Security check**. Please complete the security check to access
> Trac: Enable JavaScript and cookies to continue. Why do I have to complete a CAPTCHA?"

with `/cdn-cgi/`, `__cf_chl` and `Cloudflare` markers. Reproduced on repeat attempts — not a
transient. So:
- **Only landing pages are HTTP-reachable.** The search results page *and* every job detail page
  are challenged. There is nothing to scrape over HTTP.
- **→ sourcing is NEEDS-BROWSER.** But note what that implies: a Cloudflare managed challenge is
  **not** one of the two sanctioned exceptions in `references/captcha-policy.md` (which are
  reCAPTCHA v2 and CSJ's ALTCHA *only*). Per policy, encountering it = **⛔ FULL IMMEDIATE HALT
  of the whole loop** — not a retry, not a "log Blocked and move on". Any Trac sourcing attempt
  must be treated as likely to trip that halt. Do **not** hammer it: fast retries compound the
  Cloudflare risk score, and `cfx.sh check-cooldown trac.jobs` / `record-captcha-fail` exist for
  exactly this.

The public search form is otherwise trivial (`GET /job_list/ns`, one field `JobSearch_q`, job
URLs `/job/UK/<region>/<city>/<trust>/<specialty>/<specialty>-v<ID>` where `v<ID>` is the id) —
the wall is the whole problem, not the markup.

## ⛔ Headline 2 — apply requires a Trac account

`apps.trac.jobs` is the candidate portal, and it states the gate plainly:
> "Trac powers the recruitment for a large proportion of the UK's public sector workforce.
> **Create an account to apply for jobs** and track the progress of your applications
> including employment checks, appointments and more."

- **Sign in** form `FrmCoreLogin-CandidateSignIn` → `FrmCoreLogin-CandidateSignIn_Email`,
  `FrmCoreLogin-CandidateSignIn_Password`.
- **Create account** form `StartRegistration` → `StartRegistration_emailaddress`, plus
  **"Please confirm you are not a robot (required)"**.
- Both carry hidden `_tr` / `_ts` / `_ct` / `_gt` / `_gt2` tokens (per-render; must be replayed).
- Employer side is `admin.trac.jobs` — irrelevant here.

This matches `sites/jobs.nhs.uk/NOTES.md`'s existing note ("it too needs a (separate) Trac
account"). One Trac account covers the Trac-hosted trusts; store it in the gitignored
`ats-credentials.csv` (via `httpfeed.creds_row`), never env.

## CAPTCHA summary (two different ones — only one is sanctioned)
| where | vendor | policy |
|---|---|---|
| sourcing (`healthjobsuk.com` search + detail, `www.trac.jobs`) | **Cloudflare** managed challenge | ⛔ **NOT sanctioned → full halt** |
| account creation (`apps.trac.jobs`) | **reCAPTCHA**, `data-sitekey="6LeuMgITAAAAAHgU6j_DDWMZeN74PyUptT5jffvk"` | v2 family → **sanctioned exception 1**, auto-solve via `sites/_common/scripts/recaptcha.py` |

## Trac's own public job boards
`healthjobsuk.com` ("Job Search" from the portal), `nursingnetuk.com`, `nhsjobs.com` — all Trac
front-ends, all behind the same Cloudflare posture.

## Apply form shape — ⚠️ NOT verified
`build-audit.md` claims "Trac apply is a plain multi-step form — very drivable", and
`sites/jobs.nhs.uk/NOTES.md` describes it as "a server-rendered multi-page eform, same CLASS as
TalentLink / applicationtrack (VacancyFiller): native-DOM fills work, a real button `.click()`
advances pages, dates are 3 selects."

**This probe could not confirm any of that** — the account wall plus the Cloudflare challenge
mean no application form was reached over HTTP. Whether `atsform.py`'s label matching drives
Trac is **unverified**; the TalentLink-class claim is inherited, not re-tested here. Treat it
as a hypothesis until someone reaches a real Trac eform with an authenticated browser session.

## Build verdict
**Lowest priority of the three ATSes probed.** Sourcing is browser-only *and* runs into a
non-sanctioned CAPTCHA that halts the loop by policy; apply needs an account behind a
reCAPTCHA. Meanwhile `sites/jobs.nhs.uk/` already sources NHS adverts freely and un-walled —
so the only thing a Trac driver buys is the *apply* leg, and only for trusts that route to Trac
rather than Jobtrain. Prefer **Oleeo** (`sites/oleeo/NOTES.md`: HTTP sourcing, anonymous apply
start) before investing here.
