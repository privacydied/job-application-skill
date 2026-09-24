# cv-library.co.uk — verified site notes

Major UK agency board — strong design/BA/digital inventory (Adzuna's design "Apply" links
often redirect here). Wired in `pipeline.py FEEDS` as `cvlibrary`. See also the older
`references/cv-library-*.md` for the apply-side blocker history.

## Sourcing (VERIFIED live 2026-07-17)
- JS-rendered + **bot-walled to plain curl** (curl returns a challenge shell) — source via camofox.
- Search is **SEO path-based**: `/<role-slug>-jobs-in-<location>` (e.g. `/ux-designer-jobs-in-london`).
  Cooldown key parsed from that path (`_query_from_nav`).
- Cards carry **stable `data-qa` hooks**: `job-title-link` (a[href] `/job/<ID>/<slug>`),
  `company-name-link`, `job-card-location-N`, `job-card-salary-N`. The card wrapper class is
  hashed (CSS modules) so DON'T select on it — walk up from the title link until the ancestor
  holds BOTH location+salary hooks (company sits in a smaller inner container).
- Easy Apply badge → `ats_hint: cvlibrary-easyapply`.

## ⛔ Apply is account + chooser-gated (sourcing only here)
On-site "Easy Apply" needs a CV-Library account AND its CV upload is **chooser-gated** (the
`<input type=file>` only mounts after clicking "Select file from device" → needs
`atsform.upload_chooser` via the `/uploadViaChooser` camofox route + a container restart).
Treat as a login+chooser gate; source freely, apply with the user's authenticated session.

## CAPTCHA
⛔ Per `references/captcha-policy.md`: full halt for any CAPTCHA except the two sanctioned
reCAPTCHA-v2 auto-solves.

## ⛔ STALE ABOVE (partially) — 1-Click Apply works with a logged-in account (verified 2026-09-04, Hays Technology "IT Support")
With `ats-credentials.csv` creds and a fresh `cfx.goto()` nav (Jane Doe visible in the
header = logged in), the "1-Click Apply" button on a with-CV-on-file posting submits
immediately — no modal, no upload step, page flips straight to "Applied" / "Apply Again".
**But `cfx.click_selector()` on that button reliably TIMES OUT (30s, "action timed out",
confirmed via camofox-browser's own server log — not a strict-mode violation this time,
element is visible/unobstructed/`elementFromPoint` resolves to the exact button).** Fix:
skip the Playwright click endpoint entirely and fire a plain JS `.click()` via
`cfx.sh eval "document.querySelector('.JobViewOneClickButton_oneClickApplyButton__<hash>').click()"`
(grab the exact class name for the live page — it's CSS-modules-hashed and changes per
build) — this worked on the first try where 3+ Playwright-click attempts across 2 postings
all timed out identically. Also remove the OneTrust cookie-consent overlay first if present
(`document.querySelector('#onetrust-consent-sdk')?.remove()`) — it can eat the first
real-mouse click attempt even when off in the viewport. Not yet root-caused why the native
click endpoint specifically hangs here (works fine on totaljobs/other boards) — treat as a
board-specific quirk, use the JS-click fallback first rather than retrying the native click.
