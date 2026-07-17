# cybersecurityjobsite.com (CyberSecurityJobsite / Madgex) — verified site notes

The specialist UK cyber board. Small — **~87 live jobs board-wide** — but every posting is
in the security lane, so junior SOC / security-analyst rows surface without fighting an
aggregator's noise. On-profile via the cybersecurity Level 1 + the §14 devops/soc family.
Wired in `pipeline.py FEEDS` as `cybersecjobsite`.

A **Madgex** board — same platform as `jobs.theguardian.com` (`analytics.madgex.com`,
`cybersecurityjobsite-rs.madgexjb.com` assets confirm it).

## Sourcing (VERIFIED live 2026-07-17) — plain HTTP, no browser

**Unlike Guardian, listing pages are NOT bot-walled.** Plain `curl` with a normal Chrome UA
returns full server-rendered HTML, so `feed.py` is `fetch="http"` — no camofox, no key.
(Don't copy Guardian's cfx approach here; it's unnecessary cost.)

- Free-text search: **`?Keywords=`** → `/jobs/?Keywords=<terms>`. Pagination `&page=N`,
  **20 cards/page** (pages 1-3 verified: 20 each, zero id overlap).
- **No location filter exists.** `Location=` and `radialtown=` are accepted and silently
  change nothing (identical result counts). `/jobs/london/` is a browse path, not a filter.
  `feed.py` therefore ignores `--where` by design (`default_where=""`) and precheck.py does
  the London/remote screening.
- Cards: `<li class="lister__item cf" id="item-<ID>">` — **the `id` attribute is the stable
  job id** and matches the `/job/<ID>/<slug>/` URL.
- ⚠️ The title href contains **literal newlines and tabs inside its quotes**
  (`href=" \n\t/job/5543096/… \n"`). `httpfeed.clean()` collapses them — don't hand-roll a
  strict `href="(/job/[^"]+)"` match expecting a tidy value.
- Meta rows: `li.lister__meta-item--location|--salary|--recruiter`; posted age is
  `li.job-actions__action.pipe` ("10 days ago"). `--recruiter` is the company.
- Salary is frequently the literal string **"Competitive"** — `feed.py` maps that to `""`
  so precheck doesn't read it as a figure.

## Apply — Madgex on-page form, needs a browser

Apply URL is **`/apply/<ID>/<slug>`** (linked from the JD as
`/apply/<id>/<slug>?LinkSource=JobDetails`). It returns HTTP 200, but the static HTML
contains **no `<form>` and no file input** — the form is JS-rendered. So:

- **Sourcing = HTTP. Applying = camofox.** `ats_hint` is `madgex-direct`.
- Expect the same shape as Guardian's `guardian-direct` form (name / email / CV upload /
  optional cover). Guardian's notes are the closest reference — including its Sourcepoint
  consent + reCAPTCHA warnings, which have **not** been re-verified on this board.
- Some listings are recruiter-posted and redirect off-site to the agency's own ATS instead.

## Quirks

- The board is genuinely small; a broad query like `analyst` still only paginates a few
  pages. Expect the cooldown to mark it exhausted quickly — that's correct, not a bug.
- Result set includes non-job promo rows (e.g. "Cyber Security Expo | Cheltenham 2026" with
  salary "Excellent - Find out on the day"). They parse as normal cards; precheck screens them.
