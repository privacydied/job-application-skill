# lgjobs.com (LGjobs) — verified site notes

The local-government slice of **Jobs Go Public**: councils only. On-profile for gov digital
(§14) and IT support (§13) — digital officer, applications analyst, GIS officer, service
desk. Feed slug `lgjobs`.

## ⛔ LGjobs is a strict SUBSET of jobsgopublic.com — zero unique vacancies

Same operator, same Jobiqo backend, same index, **same numeric job ids and slugs**. LGjobs is
a council-only *view*, not a separate board.

Verified 2026-07-17 (`--what digital --where London`, full enumeration of both):

| board | result_count | ids fetched | ids absent from the other |
|---|---|---|---|
| jobsgopublic.com | 271 | 271/271 | — |
| lgjobs.com | 42 | 42/42 | **0** |

All 42/42 LGjobs ids are jobsgopublic ids. Its value is **precision, not reach**: 42
council-only rows vs 271 mixed public-sector rows, so it is a cheaper, higher-signal pass
when you specifically want local government. **Running both boards for one query is
duplicated work** — pick one.

### How the duplicate-application risk is contained
The vacancy behind an LGjobs URL *is* the jobsgopublic vacancy, so both feeds:
- share one `seen_pattern` — `(?:jobsgopublic|lgjobs)\.com/job/(?:[^/,\s]*-)?(\d+)` — which
  spans both hosts, so applying via either marks it seen for both; and
- emit the same **`source: "jgp"`** (Jobs Go Public operates both hosts, so this is literal,
  not a fudge), giving one tracker identity.

This mirrors how `sites/reed.co.uk/` folds its scraper and API feeds onto one identity.

## Sourcing (VERIFIED live 2026-07-17)
Identical to `sites/jobsgopublic.com/` — **read that NOTES.md for the Jobiqo quirks**, in
particular:
- `geo_location="<place>, UK"` is the only geo param that filters; a bare place name returns
  **0**, and `lat`/`lon`/`radius` are accepted then ignored.
- `deep_find` needs an explicit large `limit` (the 5000 default silently yields zero).

`GET /jobs?search=<terms>&geo_location=<place>, UK&page=N`, 25 rows/page. The feed imports
`sites/jobsgopublic.com/scripts/feed.py`'s parsers rather than forking ~50 lines of Jobiqo
quirks that would drift out of sync; only the host and cooldown slug differ.

Cooldown key = the `search` term, tracked separately from `jgp` (so the narrower pass can be
run on its own cadence).

## Apply path reality
The same external hand-off as jobsgopublic: every row is `applicationWorkflow: "external"`,
and the JD page's `__NEXT_DATA__` carries the real destination in `applicationLink`.
Council-run instances dominate here (`jobs.<council>.gov.uk`, eQuest, EngageATS, Oracle
Fusion). Each is its own account gate.
