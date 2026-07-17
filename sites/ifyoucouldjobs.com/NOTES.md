# ifyoucouldjobs.com ("If You Could Jobs") — site notes

It's Nice That's job board, and the highest-signal London design board in this repo for the
applicant's primary lane (§14). Inventory is studios and in-house creative teams — Dusted,
Crown Creative, Intermission Film, Apolitical, Honest Mobile, Talent Studio — hiring
Junior→Director. Small (~61 live), zero aggregator noise, roles sit for weeks. Verified live
2026-07-17.

## Why it's on-profile
Every card carries an explicit **Level** field (Junior / Midweight / Senior / Director) and a
**Location** with a work-pattern tag (`London [Hybrid]`, `London [On-site]`, `Remote`), so
precheck grades seniority and geography off the index — no JD fetch needed. The feed passes
`level` and `contract` through on the posting for exactly that reason.

## Sourcing: `scripts/feed.py [--what "design"] [--all] [--force]`
- Plain server-rendered HTML over HTTP. No browser, no key, no login.
- **The whole board is ONE page** — there is no pagination (`?page=2` returns the same 61
  cards). `search_url` returns `None` for page>1, so one GET is a complete pass.
- `?search=<terms>` **is** server-side: `?search=design` → 30/61, `?search=music` → 1.
- **No server-side location filter.** The "Region or city" box is client-side only
  (`?location=London` and `?region=London` both return the full 61), so `--where` is accepted
  and ignored rather than faked. precheck does London/remote.
- Cards: `article.job-item` wrapping `a.job-link[href="/jobs/<ID>"]` (numeric ID = tracker id).
  Title `h2.heading-2`, company `h3.subtitle-2`, and a `<dl>` of
  `<dt>Location|Level|Contract Type|Salary</dt><dd>value</dd>` pairs.
- `Salary: Undisclosed` is normalised to `""` rather than passed through as prose.

## Apply
Off-site per employer, **no If You Could account needed**. Each JD carries either a `mailto:`
to the employer's careers address (e.g. `careers@dusted.com`) or a link to the employer's own
site/ATS (e.g. `edgecomply.com/jobs/<role>?ct=ifyoucould`, `sites.google.com/…/apply/…`).
`ats_hint` is left empty — it only resolves on the JD page, which jd.py surfaces.

## Quirks
- Job ids are large and non-sequential (`2497670873`) — they are opaque, not timestamps.
- The index renders ~61 `article.job-item` cards but ~75 distinct `/jobs/<id>` hrefs appear in
  the HTML; the surplus are duplicate links inside the same card (logo + title both link out).
  Dedup is by id in the runner's pool, so this is already handled.
