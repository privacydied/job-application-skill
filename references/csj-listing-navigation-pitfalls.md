# CSJ search-results listing navigation pitfalls (verified 2026-07-15)

When you WIDEN the CSJ search to find exact-fit non-senior postings (e.g. run
`what=User Researcher` to surface a genuine fit like UK Export Finance ref 468252,
a non-senior London User Researcher at £48.7–59.5k), the **search-results page is
fragile to drive by hand** — do NOT try to extract jcodes from the listing DOM.

## Symptoms observed live (2026-07-15)
- Clicking a result listing opens the detail **inline via a `#expand` anchor** —
  it does NOT navigate to a stable `csr/jobs.cgi?jcode=<id>` detail page. The page
  body just grows; no jcode URL appears in the address bar, and `feed.py`-style
  `jcode=` href scans return NONE (CSJ uses JS `onclick`, not anchor hrefs).
- The listing `<a>` carries `aria-describedby="dref-<ref>-<vac>"` and the vac id is
  embedded in `href`'s base64 SID (`joblist_view_vac=<ID>`). BUT the **ref→vac
  pairing is OFFSET**: ref `468252` (the genuine non-senior UK Export Finance User
  Researcher) maps to vac `2004914`, yet `csr/jobs.cgi?jcode=2004914` actually opens
  the **SENIOR HMRC** listing (ref 468791, £58.5–72.7k). Trusting the
  `aria-describedby` pair misroutes you to an off-profile senior role.

## Verified workaround
1. Navigate the detail **directly** via the stable URL
   `https://www.civilservicejobs.service.gov.uk/csr/jobs.cgi?jcode=<ID>` (works for
   valid vac IDs; the `#expand` inline route is unnecessary and yields no jcode).
2. To get the CORRECT jcode for an exact-fit posting, **source via `feed.py`** — its
   stdout carries the stable `jobs.cgi?jcode=<id>` URLs with the right mapping,
   unlike the results-page `aria-describedby` pairs.
3. If you must hand-pick from the results page, open `csr/jobs.cgi?jcode=<vac>` and
   **READ the H1 + department + salary** to confirm it's the non-senior posting you
   intended before applying — never trust the ref↔vac mapping from the listing.
4. The genuine non-senior exact-fit postings in the London pool are **Business
   Analyst / User Researcher ONLY** (per `csj-tal-eform-notes.md` §profile-bounded);
   the rest of a "User Researcher" search is senior (£56k+) and off-profile for Jane.
