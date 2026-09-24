# jobserve.com (JobServe) — verified site notes

One of the largest UK IT inventories — **6,735 live hits for a bare "support" / London**
query. Heavily **contract/agency-skewed**, which is the point: day-rate 1st/2nd-line,
deskside and infrastructure contracts are the §13/§14 support+devops lanes and turn over far
faster than perm. Distinct recruiter inventory vs the aggregators. Wired in `pipeline.py
FEEDS` as `jobserve`. Plain HTTP — no browser, no key, no login.

## ⚠️ The search is POST-only — this is the whole trick of this board

JobServe has **no keyword query param**. Each search is stored **server-side** behind a
20-hex `shid` handle; only then are results GET-able and pageable. Verified live 2026-07-17:

- `GET /gb/en/mob/jobsearch?JobSearch.Keywords=support` → **164-byte body** (the MVC action
  is `[HttpPost]`; query-string model binding is rejected).
- `GET /gb/en/JobSearch.aspx?shid=&q=support` → **400** → `/gb/en/Errors/InvalidRequest.aspx`.
- The desktop form posts to `JobServeHome.aspx` as **ASP.NET WebForms** (viewstate) — avoid.

So `feed.py` does a **two-step**:

1. **POST** `JobSearch.Keywords` / `JobSearch.Location` (+ `LocationID=0`,
   `IncludeRemoteWorking=false`, `SearchMode=QuickSearch`, `ChangeMode=false`,
   `ClearMode=false`) to the **mobile MVC endpoint** `/gb/en/mob/jobsearch`.
   **No cookies, no viewstate, no login needed** — the cookie jar comes back empty and the
   search still works. The response body carries the new `shid`.
2. **GET** `/gb/en/JobListing.aspx?shid=<shid>&page=N` for results.

**The mobile-minted `shid` works on the desktop listing** (verified). That cross-surface
reuse is deliberate — see below.

## Why the desktop listing, not the mobile one

The mobile results page (`/gb/en/mob/jobsearch/results/<shid>`) is 16 KB and 25 jobs/page vs
the desktop's ~250 KB and 20 — but the **mobile card omits the company entirely**. The
desktop card carries it as an `Employment Agency` / `Employment Business` detail row. Company
matters for precheck and the tracker, so the feed pays the bytes.

Company on the mobile surface only exists on each JD's `ld+json` — an N+1 fetch per job.
Not worth it; the desktop listing has it inline.

## Parsing (VERIFIED live 2026-07-17)

- Card: `<div class="jobListItem …" id="<JOBID>">` — **the `id` IS the stable job id**
  (18-hex), and it's the same id that terminates the canonical URL.
- Title + canonical URL: `a.jobListPosition` →
  `/gb/en/search-jobs-in-<place>/<SLUG>-<JOBID>/`.
- Detail rows are `<label class="jobListLabel …">Name</label><span …>value</span>`.
  Labels in use: `Location`, `Rate`, `Type`, `Industry`, `Employment Agency`,
  `Employment Business`, `Posted Date`, `Start Date`, `Duration`, `Permalink`.
- `Rate` is often `Negotiable`/`Competitive` → mapped to `""`.
- **Page size is a stored session preference** — `&pp=100`, `&ovrpp=100`, `&jpp=100` are all
  ignored (still 20). Use `--pages N`.
- Pagination `&page=N` (337 pages on a broad query). Verified: 3 pages → 60 unique ids, no
  overlap.

## `--nav` and the shid (subtle — don't break this)

`httpfeed.run()` hands `--nav` to **page 1 only** and calls `search_url()` for pages 2+.
Without care, page 2 would mint a **fresh, empty** search and silently return the wrong
inventory. `feed.py` captures the nav's `shid` inside `query_from_nav()` — the one Board hook
that receives `nav` — and reuses it for every page. Verified: `--nav …?shid=… --pages 2` →
40 unique rows from *that* search.

## Apply — the posting agency's ATS

`ats_hint` is left empty; it only resolves on the JD page. Most rows are recruiters, so apply
lands in an agency ATS after a JobServe interstitial.

**robots.txt:** `/gb/en/JobListing.aspx` and `/gb/en/mob/jobsearch` are both **allowed**. The
per-job apply link `/gb/en/W<ID>.jsap` is **disallowed** (`Disallow: /*.jsap`) — the feed
never emits it; `.url` is the crawlable canonical listing URL instead.

## ⛔ Apply is GUEST — do NOT register a JobServe account first (verified live 2026-09-24)

Clicking the JD page's "Apply" button while NOT signed in does **not** actually require an
account, even though the page header always shows "Sign In/Register" as if it does. The
real flow:

1. From the JD, click **"Apply"**. This opens `FastTrackJobApplication.aspx?jobid=<ID>&ACN=…`
   — a plain guest form, no login/session needed.
2. Fill directly by field `name` (ASP.NET WebForms, native-setter + `input`/`change` events —
   no react-select/combobox tricks needed): email (`…rptAppMand$ctl00$Ques$Q0006_ans`),
   first/last name, address (a `<textarea>`), phone, notice period (select, e.g. "Immediate"),
   desired rate band (select), travel-distance band (select), a UK-work-status select
   ("UK Citizen" / "Indefinite Leave to Remain" / "EU Citizen" / …). Field IDs (`Q0001_ans`
   etc.) are stable Q-numbers, not per-posting random ids — reusable across postings on this
   board once mapped once.
3. Upload the CV to `input[name="ctl00$main$filCV"]` (the shared `/tabs/<tab>/upload` REST
   call with `selector`, not a snapshot `ref` — both work, `selector` is simpler here since
   the field name is stable).
4. Submit via `input[name="ctl00$main$btn2NoJS"]` (the bottom "Apply" button; there's a
   duplicate top one too, `btn1NoJS` — either fires the same submit).
5. Success text: **"Your application has been submitted."**, followed by an OPTIONAL
   "would you like to register a Job Seeker account" upsell — decline it (or ignore; it
   doesn't gate the already-submitted application).

**Do NOT waste time pre-registering a `Job Seeker` account via `/Candidate/Registration.aspx`
first** — two attempts (2026-09-24) filled the form cleanly (all fields verified via readback,
including the two required "communications preference" selects easy to miss —
`sel3RD`/`selMKT`, "Send me job opportunities on behalf of recruiters" / "…marketing emails")
and got no error banner, yet `/Candidate/Login.aspx` with the same credentials immediately
after returned "Either the email address or password is invalid" both times — the
registration silently doesn't create a working login (no confirmation email arrived via IMAP
either, ruling out an unconfirmed-account explanation the agent could self-serve). This is a
genuine, unresolved wall in the ACCOUNT path — but it is irrelevant, because the apply path
never needed the account in the first place. Treat "Sign In/Register" in the header as
decorative on this board; go straight for the JD's "Apply" button.
