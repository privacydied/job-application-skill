# designweek.co.uk/jobs ("Design Week Jobs") — site notes

The UK design industry's trade title. Small board — ~19 live, ~6 London — but high-quality and
squarely on the applicant's primary lane (§14). Verified live 2026-07-17.

## Why it's on-profile
Brand / graphic / digital / UX studio roles, plus creative-sector recruiters (a1 people et al.)
who place juniors. Worth a pass precisely *because* it's small: a full sweep is one request,
and the inventory doesn't overlap the aggregators.

## Not Madgex — it's WP Job Manager
Design Week is **not** a Madgex board, so the jobs.theguardian.com pattern (`.lister__item`,
`/job/<numeric-id>/`, `?Keywords=`) does **not** transfer — there is no `lister__item` in the
DOM. It runs **WP Job Manager**, the same plugin as MBW and Dezeen Jobs.

## Sourcing: `scripts/feed.py [--what designer] [--where London] [--pages N] [--all] [--force]`
The listing page is JS-gated ("JavaScript must be enabled in order to view listings"), but the
plugin's AJAX endpoint is plain JSON over HTTP — **no browser, no key, no login**:

```
https://www.designweek.co.uk/jm-ajax/get_listings/?search_keywords=&per_page=100&page=1
→ {"found_jobs":bool,"max_num_pages":int,"html":"<li class=\"post-<ID> job_listing…"}
```

**Why jm-ajax and not the RSS `job_feed`** (which MBW's feed uses): Design Week's RSS
*ignores/breaks* `search_keywords` — `designer`, `brand` and `zzzznonsense` **all** return 0
items while the unfiltered feed returns 19. jm-ajax filters correctly on the same install
(`designer` → 11, `brand` → 4, `zzzznonsense` → `found_jobs:false`). Keyword search is only
trustworthy through jm-ajax. `search_location` works on both (`London` → 6).

Selectors, verified against the live payload:

| field | selector |
|---|---|
| card | `li[class*="post-<ID> job_listing"]` |
| link | `a[href="https://www.designweek.co.uk/job/<slug>/"]` |
| title | `h3` |
| company | `.company strong` |
| location / salary / type | `li.location` / `li.salary` / `li.job-type` |
| date | `li.date > time[datetime]` |

### Two traps worth keeping
- **`id` is the URL slug, not the WP post id.** The tracker stores the URL, and the URL carries
  no numeric id (`/job/a1-people-london-full-time-interior-design-consultant/`). Keying on the
  post id would make seen-dedup silently never match.
- **The card regex must not end at `</li>`.** Cards *contain* `<li>` meta rows, so a non-greedy
  `.*?</li>` truncates at `li.job-type` and silently drops location/salary/date (observed:
  19 postings, all three fields empty). Boundary is the next `li.post-…` card.

## Apply — email, no account
The JD's `.application_details` reads *"To apply for this job email your CV and cover letter
to &lt;address&gt;"*. The address is **Cloudflare email-obfuscated**:
`a.job_application_email[href="/cdn-cgi/l/email-protection#<hex>"]` wrapping
`span.__cf_email__[data-cfemail="<hex>"]` — hex-XOR encoded (first byte is the key). There is
no `mailto:` href to scrape; jd.py must decode `data-cfemail`. Postings are flagged
`ats_hint="email-apply"`. No Design Week account is needed to read a listing or apply.

## Quirks
- The site carries a **Hadrian paywall** (`api2.hadrianpaywall.com`) on editorial and a
  member/recruiter login, but job listings and JD bodies are not gated — verified: a JD fetched
  anonymously returns HTTP 200 with the apply block intact.
- WP core lives under `/standfirst/` (`/standfirst/wp-admin/admin-ajax.php`), but the
  JM-specific route is the site-root `/jm-ajax/%%endpoint%%/` rewrite — use that.
- Salary is free text (`30-50k OTE GBP / Year`); `Competitive`/`Undisclosed`/`DOE` → `""`.
