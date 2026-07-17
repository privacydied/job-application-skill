# GCHQ — `gchq-careers.co.uk`

The SIGINT/cyber intelligence agency. Completes the UK intelligence set alongside MI5 +
MI6 (both on `applicationtrack.com`). Densest public-sector inventory for the DevOps/Linux
(§5) and cybersecurity (§6) families, plus in-house design/UX and IT.

## Eligibility — read before screening anything out

Roles require **DV vetting and sole UK nationality**. He is a British citizen, and vetting
is a **post-offer** process, so GCHQ roles are **on-profile**. "Needs DV" is not a
disqualifier (SKILL.md standing rule: clearance-required roles are on-profile).

Careers site is `www.gchq-careers.co.uk` — **not** `gchq.gov.uk/careers/*`, which 404s.

## Sourcing

React SPA over a private JSON API (found in `/dist/bundle.js`):

| endpoint | method | Cloudflare | notes |
|---|---|---|---|
| `/api/roles` | GET | open | department facets, e.g. `1745 IT`, `1664 Technical Roles` |
| `/api/locations` | GET | open | `1570 London`, `1553 Cheltenham`, … |
| `/api/search` | POST | **challenged** | `{Q, Departments[], Locations[], Start, Max}` → `{searchResult:[…]}` |

The two GETs answer plain HTTP (`feed.py --list-facets` needs no browser). **`POST
/api/search` is Cloudflare-gated** — curl gets the "Just a moment..." interstitial. It
answers normally from a real page context, so `feed.py` issues the POST via an in-page
`fetch()` inside camofox, where the tab already holds Cloudflare clearance. Hence this feed
requires `CFX_KEY`; without it the feed exits 2 with that explanation.

```bash
python3 sites/gchq-careers.co.uk/scripts/feed.py --list-facets              # no browser
CFX_KEY=… python3 sites/gchq-careers.co.uk/scripts/feed.py --what devops --where London
```

Response field casing varies between deploys, so `normalize()` probes several spellings per
field (`id`/`Id`/`jobId`, `title`/`Title`/`name`, …). If a deploy renames them wholesale the
symptom is zero rows from a non-empty `searchResult` — re-check the shape, don't assume the
board is dry.

## Apply

GCHQ's own portal behind a **candidate account** — sourcing is open, submission is not.
Same model as MI5/MI6: the agent fills the form and the user watches via noVNC. No account
exists in `ats-credentials.csv` yet; create one before a submission run.

Never treat the account wall as a data-scarcity ceiling — it is a login wall.
