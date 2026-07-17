# Stonefish (`*.stonefish.co.uk` / `jobs.<uni>.ac.uk`) — probe notes, no driver yet

Stonefish Software's eRecruitment is the ATS behind most UK university vacancy portals — the
downstream apply target for much of `sites/jobs.ac.uk/` (whose `feed.py` already points here).
Relevant because every London university hires the §14 "one-person digital team" family plus
§13 IT/AV support, slowly and under-competed.

**Sourcing is HTTP-fetchable with no account. ⛔ Apply requires an account — stated by the
site itself.** No driver is written yet; this is the probe record.

## Who uses it — HTTP-VERIFIED live 2026-07-17

| host | org | London? |
|---|---|---|
| `jobs.royalholloway.ac.uk` | Royal Holloway, University of London | ✅ (incl. Bedford Sq / Senate House / Stewart House campuses) |
| `jobs.uel.ac.uk` | University of East London | ✅ |
| `aub.stonefish.co.uk` | Arts University Bournemouth | — |
| `jobs.soton.ac.uk` | University of Southampton | — |

Also named by the vendor / uni docs: Bath, Worcester, Edge Hill. Two host conventions exist —
the uni's own `jobs.<uni>.ac.uk` (white-labelled) and `<tenant>.stonefish.co.uk`. Both are the
same product.

### Vendor fingerprint (how to confirm a portal is Stonefish)
```html
<meta name="Generator" content="Stonefish Software Web Builder" />
<meta name="author"    content="Stonefish Software Ltd - https://www.stonefish.co.uk/" />
```
Plus the `.aspx` route set below. Note the string `stonefish` appears **only in these meta
tags** — grepping page *body* text for it finds nothing, so fingerprint on the meta/routes.

## URL shape (ASP.NET WebForms)
| route | purpose |
|---|---|
| `/vacancies.aspx?cat=-1` | **full list of all current vacancies** — the sourcing URL |
| `/vacancies.aspx?cat=<N>` | category browse (Academic / Professional Services / Research / …) |
| `/Vacancy.aspx?ref=<REF>` | vacancy detail; `<REF>` e.g. `0726-227` = the stable id |
| `/rss.aspx` | **all-jobs RSS**; `/rss.aspx?cat=<N>[&type=<N>]` per category/location/department |
| `/AdvancedSearch.aspx` | search UI |
| `/Logon/` · `/Registration/` | login · register (**not** `/Register.aspx` — that 404s) |

## Sourcing: ✅ HTTP-fetchable, no account, no browser
Server-rendered. Royal Holloway live check:
- `vacancies.aspx?cat=-1` → 200, **15 vacancy refs** with titles inline
  (`vacancy.aspx?ref=0726-227` → "Communications and Campaigns Officer").
- `rss.aspx` → 200, `text/xml`, **15 `<item>`s** matching, each with `link`
  (`/rss/click.aspx?ref=<REF>`), `description`, `pubDate`, `category`.

⚠️ **Two gotchas for a future feed:**
1. **Refs are mixed-case in the markup** — the list emits lowercase `vacancy.aspx?ref=…` while
   the "latest" block emits `Vacancy.aspx?ref=…`. A case-sensitive regex silently finds 3 of 15.
   Match case-insensitively.
2. **Keyword search is a WebForms POST**, not a GET — the box is
   `ctl00$rightContentPlaceHolder$ctl00$txtSearch` and needs `__VIEWSTATE`/`__EVENTVALIDATION`.
   Don't fight it: fetch `cat=-1` (the whole board is small) and filter locally — precheck.py
   screens anyway.

## ⛔ Apply requires an account — the site says so outright

From Royal Holloway's own "How to Apply" page (`display.aspx?id=1253&pid=0&tabId=230`):

> "If you are interested in a post, click the Apply Online button within the job advert and
> **you'll be asked to register and set up an account on the site**"

This is a **hard stop for unattended apply**: every Stonefish university is a *separate*
account (separate host, separate credential row). There is no anonymous/auto-registration path
of the kind Oleeo has. Budget one registration per university before any application is
possible, and store each in the gitignored `ats-credentials.csv`.

## Apply mechanics
- **"Apply Online" is not a link** — it is an ASP.NET postback:
  `javascript:__doPostBack('ctl00$mainContentPlaceHolder$vacDetails$btnApplyLink$btnLink')`.
  A real browser click works (a synthetic `.click()` on an `<a href="javascript:…">` fires the
  href), but a pure-HTTP driver would have to replay `__VIEWSTATE` + `__EVENTTARGET` by hand.
  **→ apply needs a browser** (`atsform.py` via cfx), even though sourcing does not.
- A site-wide **cookie interstitial** ("Accept Cookies") gates interaction, and the login box
  carries its own `chkAcceptCookies` checkbox — accept it before touching the form (same class
  of gate as the NHS Jobs cookie interstitial).

### `atsform.py`'s label matching WILL work ✅ — but not for the reason you'd expect
The registration form has **zero `<label for=…>` attributes**, which at first looks fatal for
label-based resolution. It isn't: Stonefish uses **implicit (wrapping) labels** —
```html
<p><label> <b>Forenames</b> <span class="redHilite">*</span><br />
     <input name="ctl00$mainContentPlaceHolder$txtFirstnameNew" type="text" />
</label></p>
```
14 such `<label>`s on `/Registration/`. A wrapping `<label>` still populates `input.labels`
per the HTML spec, so `atsform.py`'s `_resolve` (`el.labels[0].innerText`) resolves
`fill("Forenames", …)` → `[name="ctl00$mainContentPlaceHolder$txtFirstnameNew"]` with **no
Stonefish-specific code**. Field names are WebForms `ctl00$…` mangles — exactly why targeting
by label is right here.

Registration fields (all wrapping-labelled): `Title` (select), `Forenames`, `Surname`,
`Email address`, `Confirm Email address`, `Password`, `Confirm Password`, plus checkboxes
`chkTermsNew` (terms) and `chkAcceptCookiesNew`.

⚠️ One label quirk: the `Title` label wraps its `<select>`, so its `innerText` includes **every
option** ("Title * Mr Mrs Miss Ms Dr Professor Baron…"). Harmless for `select("Title", "Mr")`,
but don't match short substrings against it blindly.

## CAPTCHA
**reCAPTCHA v2 on `/Registration/`** — `g-recaptcha` + `data-sitekey="6Lc_ZPQqAAAAAGr0l0A1O5OCeZDkXxq7MOh6Lc2D"`
(Royal Holloway; expect a per-tenant key). v2 → **sanctioned exception 1** in
`references/captcha-policy.md`, auto-solvable via `sites/_common/scripts/recaptcha.py`.
None on login or the sourcing path. Any *other* CAPTCHA here is still a ⛔ full halt.

## Build verdict
Sourcing is easy and browser-free (`cat=-1` or `rss.aspx`), and `jobs.ac.uk` already surfaces
these adverts — so a Stonefish **feed** adds little over the existing `jobsac` board. The value
is the **apply driver**, and its real cost is the per-university account wall, not the form:
the form itself is standard and `atsform.py`-shaped. Prioritise the London hosts
(`jobs.royalholloway.ac.uk`, `jobs.uel.ac.uk`) and register once each.
