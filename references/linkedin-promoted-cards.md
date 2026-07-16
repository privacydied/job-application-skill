# LinkedIn "Hire Feed" promoted cards — recovering the real title

**Verified 2026-07-13 (Hermes camofox run).**

`feed.py`'s ENUM reads the title from `a.job-card-container__link` /
`a[href*="/jobs/view/"]` and company from `.job-card-container__primary-description`.
The **promoted "Hire Feed"** card style — a real company logo, the word "Hire Feed",
and "Promoted by hirer · Responses managed off LinkedIn" — renders with **empty**
`title` AND `company` in the search-results DOM. So `feed.py` returns rows like:

```json
{"id": "4439797021", "url": "https://www.linkedin.com/jobs/view/4439797021", "title": "", "company": ""}
```

The cheap title pre-filter can't screen these (nothing to screen) — they look like
blank rows. They are real postings, not junk.

## Recovery — the title is inside the JD, not the card

Open the posting (`/jobs/view/<id>`). The title does **NOT** exist as an `h1` —
`document.querySelector('h1')` returns a skip-link heading ("0 notifications"), not the
job title. The title only appears as inline text in the About-the-job body, on a line
beginning `Role: <title>`, e.g. `Role: UI/UX Designer - AI Products (Remote)`.

```python
import re
txt = cfx.evaluate("(()=>document.body.innerText||'')()")
m = re.search(r'Role:\s*(.+)', txt)
title = m.group(1).strip() if m else '(role line not found)'
```

Once recovered, the normal cheap pre-filter still applies — seniority words
(Senior / Principal / Lead) also appear in the `Role:` line and must be dropped on
sight per the junior→mid screen.

## What these cards actually are

The ones seen this run were **agency contract posts**: the JD says "We are hiring for
one of our clients, seeking a UI/UX Designer…" with pay given as an hourly range
(`$22 - $70/hour`) and `Job Type: Contract`. This is a **legitimate contract
application**, not a stale repost of another company's JD and not a staffing-agency
repost (which IS a skip reason). Apply normally once a working apply path exists.

## Apply path: "Apply on company website" (no LinkedIn Easy Apply)

**Corrects a wrong claim previously here.** This button is not a dead end — it opens a
real "Share your profile?" consent dialog before the ATS handoff, which camofox's own
infrastructure was silently auto-closing (root cause + fix in `CAPABILITY-GAPS.md`).
`python3 cfx.py click-follow <ref>` now clicks through it automatically and lands on the
real destination (these "Hire Feed" postings route to `jobs.micro1.ai`). Only log
`Blocked` on a genuine `no_change`/`unhandled_dialog` after that.

## feed.py runtime on the Hermes terminal path

`python3 sites/linkedin/scripts/feed.py --nav "<url>" --scrolls 5` with default
human_pause pacing takes **>180s** (5 scrolls × ~1–9s pauses + nav dwell). A foreground
terminal call with a 180s cap **times out**. Run it **in the background**
(`terminal(background=True, notify_on_complete=True)`) and poll the output file: JSON
goes to stdout, the `FRESH` / `EXHAUSTED` summary to stderr.

See also: `SKILL.md` → Browser Engine → Hermes bootstrap (env + tab setup).
