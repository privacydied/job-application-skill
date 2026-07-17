# jobsgopublic.com (Jobs Go Public) — verified site notes

The public-sector **employer** board: London boroughs, housing associations and charities.
Biggest single source for the "one-person digital team" family (§14) and IT support (§13) —
digital officer, applications analyst, GIS officer, web content, service desk. Council and
housing employers under-advertise on LinkedIn/Indeed, so this is additive reach, not a
re-run of the aggregators. Feed slug `jgp`.

⚠️ **`sites/lgjobs.com/` is the same index.** LGjobs is a local-government-only *view* of
this board — same operator, same backend, same numeric ids and slugs. Proven 2026-07-17: for
`digital`/London all **42/42** LGjobs ids are in this board's 271. Running both for one query
is duplicated work; both feeds share one `seen_pattern` so it cannot become a duplicate
application.

## Sourcing (VERIFIED live 2026-07-17)
- **Platform: Jobiqo** — Next.js over a Drupal/Apollo GraphQL backend
  (`backend.jobsgopublic.jobiqo.com/graphql`). Plain curl works; no browser, key or login.
- The SSR page embeds the full result set in `__NEXT_DATA__`, so the GraphQL POST is
  unnecessary — `GET /jobs?search=<terms>&geo_location=<place>, UK&page=N` is enough.
  25 rows/page; `result_count` holds the true total.
- Job rows are found by **shape** (`__typename == "Job"`) via `deep_find`, not by path: the
  Apollo path (`props.pageProps.data.jobs.pages`) is a build artifact and its sibling key is
  literally a serialised GraphQL query string, so it moves between deploys.
- ⚠️ **`deep_find`'s default `limit=5000` is too small here.** The limit counts every node
  popped — scalars included — and the blob is ~570KB, so the default runs out *before* the
  job rows and yields ZERO with no error. The feed passes `limit=200_000`.
- Cooldown key = the `search` term.

### ⚠️ The geo filter is a LABEL match, not a radius
`geo_location` is the **only** param that filters, and it needs the Google-Places-style
`"<place>, UK"` label. Everything the UI also emits — `lat`, `lon`, `radius`, `locality`,
`locationType`, `country`, `location` — is accepted and then **ignored**:

| URL | result_count |
|---|---|
| `search=digital` | 675 |
| `…&geo_location=London` (no `, UK`) | **0** |
| `…&geo_location=London,%20UK` | **271** |
| `…&geo_location=London,%20UK` + *Manchester* lat/lon | 271 (still London jobs) |
| `…&geo_location=London,%20UK&radius=1` vs `radius=200` | 271 either way |
| `…&lat=…&lon=…&radius=8` (no `geo_location`) | 675 (geo ignored) |
| `…&geo_location=NOTAPLACE,%20UK` | 0 (so it is a real filter) |

So the feed sends the label alone. A bare place name silently returns **0**, which reads as
"board is dry" — it is not; it is a malformed query.

- `address` is a **list**: multi-site public-sector roles list every location and the filter
  matches *any* of them (a "Manchester, UK" search legitimately returns rows whose first
  address is Bristol). The feed joins up to 3 rather than taking `[0]`.

## Apply path reality — always an external ATS, and the JD names it
Every row observed carries `applicationWorkflow: "external"`: JGP is a shopfront, never the
applicant system. The JD page's `__NEXT_DATA__` exposes the exact destination in
**`applicationLink`** (plus `body`, `applicationRequireCv`, `applicationRequireCoverLetter`,
`applicationQualifyingQuestions`) — so the apply target is resolvable over plain HTTP without
rendering.

Destinations are per-employer and varied. Sampled 6 London digital roles:

| ATS behind apply | count |
|---|---|
| `ars2.equest.com` (eQuest) | 2 |
| `jobs.southwark.gov.uk` (council-own) | 1 |
| `jobs.harrow.gov.uk` (council-own) | 1 |
| `lqgroup.engageats.co.uk` (EngageATS) | 1 |
| `fa-evng-saasfaprod1.fa.ocs.oraclecloud.com` (Oracle Fusion Recruiting) | 1 |

Each destination is its own account gate. `ats_hint` is set to `"external"` to record the
hand-off; it does not name the ATS because the search page does not know it.

## Quirks
- JD pages return HTTP 200 with an **empty `<title>`** (Next.js SPA shell) — presence of the
  job must be checked via `__NEXT_DATA__`, not the title.
- `salaryRangeFree` (min/max/currencyCode/salaryUnit) carries pay; `salaryRange` is `[]` on
  every row observed. Values are strings like `"34206.000000"` — `httpfeed.money()` copes.
  The feed appends the unit when it is not `YEAR`.
- No CAPTCHA on the sourcing path.
