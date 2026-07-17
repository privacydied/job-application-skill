# musicbusinessworldwide.com/jobs ("MBW Jobs") — site notes

The music industry's main job board, and the applicant's **standout lane**. Verified live
2026-07-17: ~47 live roles, ~16 in London.

## Why it's on-profile
This is the one board where both differentiators compound instead of competing: he is half of
a West London alt-hip-hop duo and has built music-tech products, so a design / product /
digital role at a label, publisher or distributor reads as domain fluency, not a hobby.
Inventory is the industry itself — Spotify, Kobalt, BMG, Believe, The Orchard, Live Nation,
Nettwerk, Three Six Zero, Y Royalties — and **none of it appears on any aggregator in this
repo**. Roles skew commercial (marketing, rights, A&R, finance), so the design/product slice
is thin but uncontested; source the whole board and let precheck filter.

## Sourcing: `scripts/feed.py [--what marketing] [--where London] [--all] [--force]`
- MBW runs **WP Job Manager**, which ships a structured RSS `job_feed`. The feed uses it in
  preference to scraping the Avada/Fusion HTML on `/jobs/`. No browser, no key, no login.
  ```
  https://www.musicbusinessworldwide.com/jobs?feed=job_feed&posts_per_page=100
  ```
- **`posts_per_page` is the page-size lever that works.** The feed otherwise honours WP's
  10-item RSS cap, and `posts_per_rss` / `showposts` are both silently ignored (10, 10).
  `posts_per_page=100` returns the whole board (47) — which is why the feed needs no
  pagination at all (`search_url` returns `None` for page>1).
- `search_keywords` and `search_location` filter server-side: `marketing` → 33,
  `designer` → 4, `zzzznonsense` → 0, `search_location=London` → 16.
- Each `<item>` carries the `job_listing:` XML namespace — `company`, `location`, `salary`,
  `job_type`, `job_category` as real fields, so nothing is selector-guessed. Job URL is
  `/jobs/job/<ID>/`; `<ID>` is the tracker id.
- `/jobs/listings/` is the human-facing filter page and is AJAX-driven (`job_manager_ajax_filters`);
  it carries no static job links. `/jobs/` (the landing page) does, but the RSS is cleaner.

## Apply — on-site, but gated by an emailed one-time password
The JD's **Apply** button opens an Avada off-canvas panel (`href="#awb-oc__…"`) holding a
**Gravity Form (id 14)**, posting to `/jobs/job/<ID>/#gf_14`. Fields:

| field | name | required |
|---|---|---|
| LinkedIn | `input_12` | no |
| Email | `input_3` | **yes** |
| One-Time Password | `input_10.1` (6-digit, `pattern="\d{6}"`) | **yes** |
| First / Last name | `input_7` / `input_8` | **yes** |
| Phone | `input_4` | no |
| CV upload | file field | no |
| Privacy consent | `input_6.1` | **yes** |

The OTP is **emailed to the address entered** — so applying needs live mailbox access, not
just a filled form. Postings are flagged `ats_hint="mbw-gform-otp"` so the apply stage expects
the round-trip. No MBW account is required beyond that.

## Quirks
- Locations are free text and often blank or non-UK (`Los Angeles, United States`); precheck
  must not assume a UK location.
- Salary is free text (`$80,000.00 USD - $100,000.00`, `Competitive`); `Competitive` /
  `Undisclosed` / `DOE` are normalised to `""`.
- `job_category` is a comma-joined list (`Artist Management, Marketing / Digital Marketing`).
