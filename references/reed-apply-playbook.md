# Reed.co.uk Apply Playbook (condensed)

Driver: `scripts/reed_apply.py <job_id> [<job_id> ...]` (run with `CFX_TAB` pointed at
a live tab; Jane must be logged in to Reed — verify via `reed.co.uk/account/jobs/applications`).

## Sourcing
`python3 sites/reed.co.uk/scripts/feed.py --nav "https://www.reed.co.uk/jobs/ux-designer/london"`
→ ~25 fresh UX/design jobs (JSON: id, url, title, location).
On-profile = UX / UI / Interaction / Service Designer, Trainee / Junior.
Exclude = Lead / Senior / Architect / Developer / Manager + fashion-Print / Graphic (off-profile for Jane).
**Screen by TITLE, not salary** — Reed JD `salary_mentions` mixes related-job bands (a "UX Designer" posting showed £50-80k that included sibling listings).

## Apply flow (verified 2026-07-15)
1. Nav to `https://www.reed.co.uk/jobs/ux-designer/<id>`.
2. Click **Apply now** → button class `btn btn-primary`, text exactly "Apply now" (two exist: page + sticky; take the first matching).
3. Modal opens. Two shapes:
   - **Screening question(s)** e.g. "2yrs in a UX Design/Interaction Design role?",
     "Experience within the public sector with GDS?" → click **Yes** radio + **Continue**.
     May be several in sequence. Truthful answers: Jane ~6yrs UX; NHS/UKHSA + GOV.UK Design
     System ⇒ Yes is truthful for the GDS question.
   - **About you** summary (prefilled from session: name/email/phone/location + CV) + **Submit application** (often below the fold).
4. Click **Submit application**.

## Two traps
- **Post-submit 404 is BENIGN.** After Submit, URL becomes `…?jobId=<id>` then redirects to
  a "Oops, page not found" 404. The application registered — do NOT treat the 404 as failure.
  **Verify at `https://www.reed.co.uk/account/jobs/applications`** (the "Applications" badge
  count increments; the role shows "Applied 15/07/2026"). That list is the ONLY proof.
- **Snapshot ref-click 500s.** `cfx.sh click eN` on the Apply-now / Submit buttons intermittently
  returns HTTP 500 and the modal won't open. **Always click via a minimal `cfx.evaluate` DOM-click:**
  ```js
  [...document.querySelectorAll('button.btn-primary')].find(x=>x.innerText.trim()==='Apply now').click()
  // Submit:
  [...document.querySelectorAll('button,input[type=submit]')].find(x=>(x.innerText||x.value||'').trim()==='Submit application').click()
  ```
  The a11y snapshot also often fails to capture the Submit button (below fold) — query the DOM directly.

## Bulk-reconcile from the live badge (use after ANY big apply batch)
Do NOT trust per-batch hand-dedup — a loose tracker-regex (`re.search(r'reed\.co\.uk/jobs/[^/]+/(\d+)')` misses bare-URL rows and silently drops IDs (seen live: 2 applied roles fell through the dedup and the "new" list re-included already-applied IDs). Instead, reconcile from the source of truth:
1. Scrape ALL applied IDs from `https://www.reed.co.uk/account/jobs/applications?page=N` (≈26/page, paginate to last). Robust extraction (slug OR bare):
   ```js
   [...document.querySelectorAll('a')].map(a=>a.href).filter(h=>/reed\.co\.uk\/jobs\/.*?(\d+)(?:\?|$)/.test(h))
   ```
   Collect into a set, dedup, write `/tmp/reed_applied_all.txt`.
2. `grep -c` each candidate id against `application-tracker.csv`; append only the missing rows (match title/company from the `feed.py` JSON, not by re-scraping each JD).
3. **Never `echo >>` the tracker by hand** — use `log-application.py` or one `csv.writer` `with`-block. A `open(path,'w')` that throws AFTER truncation zeroes the file (hit before: 288→0 rows; recovered only committed 74 via `git HEAD`).
4. The badge number (e.g. 105) is the real completed count; the tracker is the record. Report both. After a ~99-role batch the badge went 10→105 and the tracker 128→227 — that is the audited proof, not the fragmentary batch logs.
- Some roles (e.g. "UX Writer") **loop-end** in the driver: the modal needs a CV re-upload step
  it doesn't handle. Skip those; apply manually if on-profile.
- Reed's Applications page paginates — the badge count is the real total; only the first ~2 cards show per screenshot.
- The driver's `answer_yes_and_advance()` clicks the first "Yes" label/radio and then Submit-if-present-else-Continue, looping up to 8 steps — sufficient for the observed 1-3 screening questions + About-you.
