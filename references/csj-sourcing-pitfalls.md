# CSJ Sourcing Pitfalls (verified 2026-07-15)

Civil Service Jobs (`civilservicejobs.service.gov.uk`) is the skill's big-target
volume lever (hundreds of London postings), but sourcing it has three traps that
are NOT obvious from `feed.py` alone.

## 1. The search-context SID EXPIRES — regenerate it before sourcing

`searches.csv` `csj` row's `nav` URL is a base64 SID carrying a **timestamped
`reqsig`**. It goes dead. Symptom: `feed.py --nav <csj sid>` prints
`ERROR: not on a CSJ results page (title='Civil Service job search ...')` / "the
search-context SID ... has EXPIRED". Re-running `feed.py --nav` on the same dead
SID just re-fails — you must mint a FRESH SID.

### Regeneration recipe (drive the form via `cfx.evaluate`, not the CLI)

```python
import sys, time
sys.path.insert(0, 'sites/_common/scripts')
import cfx
# tab must be a live job-apply tab (CFX_TAB)
cfx.evaluate("location.href='https://www.civilservicejobs.service.gov.uk/csr/index.cgi?pageaction=search'")
time.sleep(3)
cfx.evaluate("""(() => {
  const w = document.getElementById('what');          # type=search keyword field
  const l = document.getElementById('whereselector'); # type=text location (NOT 'where')
  if (w) { w.value='analyst'; w.dispatchEvent(new Event('input',{bubbles:true})); }
  if (l) { l.value='London';  l.dispatchEvent(new Event('input',{bubbles:true})); }
  const s = document.getElementById('submitSearch');   # type=submit, value "Search for jobs"
  if (s) s.click();
  return 'submitted';
})()""")
time.sleep(5)
fresh_sid_url = cfx.evaluate("location.href")   # -> index.cgi?SID=<fresh base64>
```

Then write `fresh_sid_url` into the `csj` row of `searches.csv` **via Python**
(not by pasting into a terminal — the base64 is long and a paste will corrupt it):
```python
lines = open('searches.csv').read().split('\n')
for i,l in enumerate(lines):
    if l.startswith('csj,'):
        p=l.split(','); p[2]=fresh_sid_url; lines[i]=','.join(p)
open('searches.csv','w').write('\n'.join(lines))
```
Note: `cfx.evaluate` intermittently 500s on a *complex* JS expression but works on
`document.title` / simple expressions — if a big fill returns 500, split it into
smaller evaluates (set keyword, then location, then click, as separate calls).

## 2. The keyword field does NOT support boolean OR

A query like `"analyst OR support OR tester"` (the style used in `searches.csv`
LinkedIn bundles) returns **"0 Search results"** on CSJ — its `what` field is a
plain text box, not a boolean query parser. Use a **single keyword**:
`what=analyst` -> 31 results; `what=support` -> many; etc.

To sweep several role families, run the search **once per keyword** (each yields
its own SID you capture and log), OR rely on the bundled `london-search` query and
accept its title-eligibility filter. Don't OR-bundle in the CSJ keyword box.

## 3. `feed.py` captures only page 1 (~6 of 31) — pagination gap

`feed.py --all-pages` stops after page 1 even when the results title says
"31 Search results". Cause: CSJ renders pagination as **numbered links ("1 2")**
and the real "next" is JS-driven. `feed.py._next_page()` only matches anchors whose
text starts with `next` (regex `^next\s*`), so the "2" link (text just `"2"`) is
missed -> stderr shows `no 'next' control after page 1 — end of results` and only
~6 cards are emitted.

Until `feed.py` is fixed (see code note below), recover the rest manually:

- The page-2 SID DOES exist in the DOM after the page renders — capture it:
  ```python
  hrefs = cfx.evaluate("[...document.querySelectorAll('a[href*=SID]')].map(a=>a.href)")
  # find the one whose decoded base64 contains 'page=2' (decode: base64 + '='*(-len%4))
  ```
- Then run `feed.py --nav "<that page-2 SID url>" --force` to enumerate cards 7-12,
  and repeat for `page=3`, etc. (CSJ search results are ~17 pages for a broad query).

### Code fix for `feed.py._next_page()` (when you touch it)
Also match numbered page links and SID hrefs containing `page=N`:
```python
a = links.find(x => /^\d+$/.test(txt(x)) && /[?&]page=\d+/.test(x.href))
```
or click the numbered link and re-enumerate. Bumping `page=N` in the decoded SID
and re-encoding also works if the link isn't in the DOM.

## 4b. The Developer/DevOps/Digital family is mostly EXTERNAL-ATS (beapplied), not CSJ-TAL

Sweeping the `Developer` / `DevOps` / `Digital` / `Web Developer` / `Software
Engineer` keywords (Jane has genuine frontend/Linux/Node/Docker skills) surfaces
16+ London vacancies, but the **non-senior ones route to `app.beapplied.com`**, NOT
the CSJ-TAL eform (`cshr.tal.net`). Symptom on the advert: the apply control reads
**"Apply at advertiser's site"** with `href` `https://app.beapplied.com/apply/<id>`
(rather than a `cshr.tal.net` eform). Example: Software Developer, MHCLG
(vac 2005256, GBP44,004-47,444, London) -> beapplied.

- `tal_eform.py` / `tal_sec2.py` **cannot drive these** — they only understand the
  TAL eform flow. A beapplied posting needs **account registration + a bespoke
  multi-step form**, i.e. an external-ATS flow (see `references/external-ats-bypass.md`)
  requiring a MODEL-stage tailored resume, not a headless `tal_eform.py` run.
- The beapplied URL's page `<title>` contains "... Applied" — that is the **product
  name** ("when submitting your application Applied will ask you to upload a CV"),
  NOT an application status. Do not misread it as already-applied.
- Senior Developer postings (Cabinet Office Ruby Dev GBP57k+, GDS iOS/Android GBP57k+,
  HMRC Lead Dev GBP58k+) are correctly skipped as off-profile/senior.
- Including the Developer family in CSJ sourcing is worthwhile for discovery, but
  expect genuine non-senior fits to fall into the external-ATS bucket — budget them
  as `needs_model` (tailored resume) + registration, not instant `tal_eform.py` wins.

## 4. Title-only precheck under-counts CSJ — open borderline JDs

`check_title` eligibility is title-phrase-based; CSJ's London set is ~98% senior/
policy titles, and the **grade field lives in the JD, not the card**. A `precheck`
returning ~1 `keep` does NOT mean CSJ is exhausted. Open borderline JDs with
junior-mid salary bands (GBP37k-GBP45k) and read the "Job grade" row — an **EO/HEO**
posting is on-profile even with a senior-sounding title word. (Mirrors the existing
CSJ board note; repeated because it's the #1 reason a CSJ volume run looks empty.)
