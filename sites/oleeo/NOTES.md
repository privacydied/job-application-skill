# Oleeo (`*.tal.net`) — probe notes, no driver yet

Oleeo (formerly WCN / World Careers Network) is the UK public-sector ATS behind a whole row of
police and government employers. **Sourcing is plain-HTTP fetchable with no account, and apply
starts anonymously** — the most drivable of the three ATSes probed. No driver is written yet;
this is the probe record.

> ⚠️ **Oleeo is `*.tal.net`, NOT `*.oleeo.com`.** `oleeo.com` is the vendor's marketing site;
> tenant subdomains under it do **not** exist (`metpolice.oleeo.com`, `nca.oleeo.com`, … all
> NXDOMAIN — and there is no wildcard, a bogus control is NXDOMAIN too).
> `tal.net` **does** wildcard-resolve, so DNS proves nothing there — a tenant is only real if
> HTTP answers (a non-existent tenant returns curl code **000**, not 404).
> Do not confuse with **TalentLink** (Lumesse, `*.recruitmentplatform.com`, already in this
> repo at `sites/recruitmentplatform/`) — different vendor, similar-looking name.

## Who uses it — HTTP-VERIFIED live 2026-07-17

| tenant | org | London? |
|---|---|---|
| `policecareers.tal.net` | **Metropolitan Police** ("Police Careers (MET)") | ✅ |
| `cityoflondonpolice.tal.net` | City of London Police | ✅ |
| `btp.tal.net` | British Transport Police | ✅ (HQ) |
| `thamesvalleypolice.tal.net` | Thames Valley Police | — |
| `asp.tal.net` | Avon and Somerset Police | — |
| `policescotland-spacareers.tal.net` | Police Scotland | — |
| `oleeo-jobs.tal.net` | Oleeo's own careers site (clean reference instance) | ✅ |

Oleeo's own logo wall also names GOV.UK, NHS, Nottinghamshire County Council, Amazon, Morgan
Stanley, Bank of America, BlackRock, Evercore, ONR.

### ⛔ Corrections to `build-audit.md` (its Oleeo roster is partly stale)
- **`workforus.parliament.uk` is NXDOMAIN** — the Parliament host named there is dead.
  `parliament.uk/about/careers/` 403s to curl; Parliament's current ATS is **unconfirmed**.
- **BBC is NOT Oleeo.** `careers.bbc.co.uk` is **jobs2web / SAP SuccessFactors**
  (`bbctechsupt4.valhalla2.stage.jobs2web.com`). No Oleeo/WCN marker anywhere on it.
- **`metpolice.tal.net` is a decommissioned tenant** — it loads, but the page body reads
  *"The System you are trying to enter has been scheduled to be DELETED."* The Met's live
  Oleeo is **`policecareers.tal.net`**. Do not target `metpolice.tal.net`.
- ONR is **Hireserve**, not Oleeo (`platform.hireserve.com/icamsbase/`, `var Hireserve`,
  `hs_apply.css`, search action `/utf8/ic_job_feeds.feed_engine`) — a separate ATS if ever wanted.

## URL shape

```
https://<tenant>.tal.net/vx/[lang-en-GB/][mobile-0/]appcentre-<N>/[brand-<N>/][xf-<hash>/]candidate/...
```
- **Vacancy search**: `…/candidate/jobboard/vacancy/<boardId>/adv/`
  (Met: `https://policecareers.tal.net/vx/appcentre-3/candidate/jobboard/vacancy/1/adv` → 200,
  **25 `/opp/` links**, server-rendered, no login.)
- **Vacancy detail**: `…/candidate/so/pm/1/pl/1/opp/<ID>-<Slug>/en-GB`
- **Atom feed** (present on some tenants, absent on the Met board):
  `…/candidate/jobboard/vacancy/<boardId>/feed` → `application/atom+xml`, one `<entry>` per
  vacancy with `title`, `published`, and a `content` block of `Title:/Team:/Location:`.
- **Login** `…/candidate/login` · **Register** `…/candidate/register`
- `appcentre-<N>` and the jobboard id **vary per tenant** (Met = `appcentre-3`/`vacancy/1`;
  Oleeo's own = `appcentre-1`/`vacancy/1`; Avon & Somerset and City of London use `vacancy/14`).
  Discover them from the tenant's `/candidate` landing page rather than hardcoding.
- **The `xf-<hash>` path segment is NOT required.** It is a per-response token; stripping it
  returns the same 200 and the same content (verified: 11,926 vs 11,938 bytes). Do not try to
  harvest/replay it for sourcing.

## Sourcing: ✅ HTTP-fetchable, no account
Server-rendered HTML, no Cloudflare challenge, no login gate. The JD page exposes the full
advert to an anonymous fetch — title, Job type, Contract type, Country, Region, Location,
Salary, and the full description body. A feed here needs **no browser**.

## Apply: starts ANONYMOUSLY — not account-walled at the door

This is the important finding, and it is the opposite of Trac/Stonefish.

The JD page carries a real apply form (not a link):
```html
<form action=".../candidate/so/pm/1/pl/1/opp/<ID>/apply/en-GB" method="post" class="apply-form">
  <input type="hidden" name="__vxXSRF_Token" value="<40-hex>" />
  <input type="submit" name="submit_button" value="Apply" />
</form>
```
POSTing it with a fresh cookie jar + the page's live `__vxXSRF_Token`, **while logged out**,
returns 200 and lands on:
```
/vx/lang-en-GB/mobile-0/appcentre-1/brand-2/user-37058/xf-<hash>/candidate/eform/64138/page/1
```
— an **"Eligibility Pre-Screen" eform, page 1**, with a `user-<N>` auto-provisioned for an
anonymous visitor (the register form carries `__AUTO_REGISTRATION_FLAG__=1`, i.e. Oleeo
supports register-as-you-apply). The nav still shows Login/Register.

⚠️ **Verified only as far as page 1.** Whether the *final* submit forces account creation
(likely, via the auto-registration flag) was **not** probed — no application was submitted.
Do not record "apply needs no account" as settled; the honest claim is: **the application
eform opens and is fillable without pre-registering.**

### Apply eform shape — `atsform.py` should drive it natively ✅
Page 1 fields:
```html
<label for="form_<uuid>_datafield_18133_1_1">Are you free to remain and take up employment in the UK? *</label>
<select id="form_<uuid>_datafield_18133_1_1" name="datafield_18133_1_1" aria-required="true">
  <option>Select</option><option>Yes</option><option>No</option>
</select>
```
- **`<label for>` is byte-identical to `<select id>`** (verified programmatically) → `el.labels[0]`
  resolves → `atsform.py`'s `select("<label substring>", "Yes")` works with **no Oleeo-specific
  code**. `select()` also prefers an exact option match, so `"Yes"` cannot mis-hit a
  `"Yes, …"` option.
- Field **names are `datafield_<N>_1_1` — random per posting**, which is exactly the case
  `atsform.py` exists for (label-targeting, not name/id).
- Multi-page: "Table of Contents" / "Progress Tracker" nav, pages at `…/candidate/eform/<N>/page/<P>`,
  plus `/instructions` and `/print`. A ≤10MB file upload and a `Submit` sit on the eform.
- Applicant-relevant: the pre-screen asks right-to-work and sponsorship — both clean **Yes/No**
  for a British citizen (see `references/applicant-profile.md`).

## Register / login shape (if the final submit does force an account)
- **Register** `…/candidate/register` — proper `<label for>` pairs:
  `First Name`, `Last Name`, `E-mail`, `Confirm E-mail`, `Choose Password (min 12 characters)`,
  `Confirm Password`. Hidden `__vxXSRF_Token`, `formtt_uuid`, `__AUTO_REGISTRATION_FLAG__`.
  Also offers LinkedIn / Facebook SSO.
- **Login** `…/candidate/login` — labels `Email` / `Password`.
- Credentials belong in the gitignored `ats-credentials.csv` (via `httpfeed.creds_row`), never env.

## CAPTCHA
**reCAPTCHA is present on `/candidate/register`** (`recaptcha/api.js`, `recaptcha_register_wrapper`).
It is the **reCAPTCHA v2 family → sanctioned exception 1** in `references/captcha-policy.md`,
auto-solvable via `sites/_common/scripts/recaptcha.py`. Not present on login, and **not on the
sourcing path at all**. Any *other* CAPTCHA here is still a ⛔ full halt.

## Build verdict
Highest-value of the three: one driver covers the Met + City of London Police + BTP (all
London), sourcing is browser-free, and the eform is already `atsform.py`-shaped. Next probe
steps: confirm what the **final** eform submit demands, and enumerate the page sequence beyond
the Eligibility Pre-Screen.
