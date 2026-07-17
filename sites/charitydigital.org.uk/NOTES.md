# charitydigital.org.uk (Charity Digital Jobs) — ⛔ VERIFIED-DEAD, do not build a feed

**There is no feed here on purpose.** Charity Digital's job board is dead: the domain that
hosted every listing no longer exists. `charitydigital.org.uk/jobs` still returns **HTTP 200**
and still renders a "Latest Jobs" list, which makes it look alive — it is not. This is the
same trap as DWP Find a Job (200 + a body reading "This site is now closed").

## The evidence (VERIFIED 2026-07-17)

`charitydigital.org.uk/jobs` is a **marketing shell**. It hosts no job detail pages of its own;
every listing links out to **`charitydigitaljobs.org`**:

```
job-link hosts on /jobs:  {'charitydigitaljobs.org': 8, 'charitydigital.org.uk': 1}
                                                          ^ just the /jobs page linking to itself
```
e.g. `https://charitydigitaljobs.org/job/3110/head-of-digital-product/`

**`charitydigitaljobs.org` does not resolve — NXDOMAIN, confirmed on four resolvers:**

| resolver | result |
|---|---|
| local (192.168.1.2) | NXDOMAIN |
| 1.1.1.1 | NXDOMAIN |
| 8.8.8.8 | NXDOMAIN |
| Cloudflare DoH | `{"Status":3}` (NXDOMAIN), authority = `org` SOA — no delegation |

Control, same DoH endpoint, same moment: `charitydigital.org.uk` → `{"Status":0}`, resolves to
`99.81.213.83` / `18.202.1.207`. So the failure is the domain itself, not the network.

HTTP confirms it: `https://charitydigitaljobs.org/`, `https://www.charitydigitaljobs.org/` and
`http://charitydigitaljobs.org/` all return **000** (no connection).

## No replacement board exists on-site
- `/jobs/search` → 200 but serves the **same template** with the **same 8 dead links** (it is a
  catch-all: `/jobs/1` and `/jobs-board` both 404).
- `/job` → 404. `robots.txt` sitemaps list news only, no jobs path.

## Verdict
**VERIFIED-DEAD.** Sourcing yield is structurally zero — not "hard to scrape": every advert
points at a domain that has been allowed to lapse. Any feed written against `/jobs` would emit
rows whose `url` is unreachable, poisoning the tracker with unapplyable postings.

The charity-digital lane is already covered by live siblings:
`sites/charityjob.co.uk/` (CharityJob), `sites/jp.thirdsector.co.uk/` (Third Sector Jobs),
`sites/escapethecity.org/` (Escape the City).

**Re-check before ever building this:** confirm `charitydigitaljobs.org` resolves *and* that
`/jobs` links to a host that answers. If Charity Digital relaunches on a new partner domain,
that new host — not `charitydigital.org.uk/jobs` — is what a feed should target.
