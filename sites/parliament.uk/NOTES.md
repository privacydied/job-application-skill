# UK Parliament — `hrhoc.parliament.uk` / `hrhol.parliament.uk` (MHR Web Recruitment)

Parliament recruits on **MHR Web Recruitment (iTrent)**. Not Oleeo, not Hireserve, and not
`workforus.parliament.uk` — that host is **NXDOMAIN**, as is `careers.parliament.uk`. The
canonical human entry point is `parliament.uk/about/working/jobs/`, which fans out to three
separate boards.

## Three boards, one app, three WVIDs

`ETREC179GF` is the search app; the `WVID` ("web view id") selects the employer stream.
Lords is on a **different host and instance path** (`hrhol` / `ce0913li`) — not just a
different WVID.

| stream | host + path | WVID |
|---|---|---|
| **pds** | `hrhoc.parliament.uk/ce0912li_webrecruitment` | `6744175kYE` |
| **commons** | `hrhoc.parliament.uk/ce0912li_webrecruitment` | `3402965kYE` |
| **lords** | `hrhol.parliament.uk/ce0913li_webrecruitment` | `7744073cYW` |

**PDS = Parliamentary Digital Service** — Parliament's in-house design/UX/engineering arm,
and the on-profile stream (§1/§3/§12). It is also the smallest: **a PDS pass returning 0 is
normal**, not a broken feed. Check `commons` before concluding anything is wrong (measured
2026-07-17: pds 0, commons 10, lords 5).

## Sourcing — camofox required

```bash
python3 sites/parliament.uk/scripts/feed.py --list-tenants          # no browser
CFX_KEY=… python3 sites/parliament.uk/scripts/feed.py               # all 3 streams
CFX_KEY=… python3 sites/parliament.uk/scripts/feed.py --tenant pds --what designer
```

**There is no HTTP route and no JSON endpoint.** Plain GET returns a shell; the vacancy list
is rendered client-side and **fires no XHR at all** (results are computed in-page from
embedded data), so there is nothing to intercept. POSTing the search form — replaying every
signed `%.`-prefixed hidden field and the `USESSION` token — returns a bare "Search for jobs"
page with an empty `.Mhr-jobSearchJobs` container. Rendering is the only route; the feed
exits 2 without `CFX_KEY`.

- Cards: `.Mhr-jobSearchJobs > *`, each with a stable `vac-id`.
- Fields: `.Mhr-jobDetailEntry` label/text pairs → *Apply by*, *Location*, *Salary*, *Basis*.
- **Cards render on load — do NOT click "Find jobs".** That click times out (~30s): it fires
  a re-render Playwright waits on, the documented click-hang pattern. A JS `.click()` fires
  but changes nothing, because no request is made.
- The board's keyword box is client-side, so `--what` filters titles in the feed rather than
  driving its UI.

## Canonical URL

```
<base>/ETREC179GF.open?WVID=<wvid>&VACANCY_ID=<vac-id>
```

Verified to deep-link straight to the job profile, **session-free**.

⚠️ **Do not use the card's `bu-send` attribute.** It points at `ETREC148GF` — the *apply*
screening flow, not the profile — and carries a `USESSION` token that expires. Without the
session it renders "Screening Questions" with no vacancy context; the vacancy title isn't
even on the page.

The job profile opens **in place** (the SPA never changes `location.href`), so there is no
per-vacancy URL to scrape from the DOM — the canonical form above is constructed, not read.

## Apply

Account-gated: MHR candidate account ("Existing user login" / "My applications" /
"My profile"). Sourcing is open; submission needs that account, which is **not** in
`ats-credentials.csv`. `ats_hint` is `mhr-webrec`. Treat as a login wall, never as a
data-scarcity ceiling.
