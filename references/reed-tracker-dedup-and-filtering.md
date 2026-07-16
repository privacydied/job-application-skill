# Reed: tracker dedup + off-profile filtering (learned 2026-07-16)

Two traps that cost a full 15-pass wrong "exhausted" conclusion. Both are
reusable; the first is the root cause of falsely declaring a board dead.

## 1. Tracker dedup-regex trap (ROOT CAUSE of false "exhausted")

`application-tracker.csv` Reed rows are written with **bare URLs**
(`https://www.reed.co.uk/jobs/<ID>` — no slug), NOT slug form
(`/jobs/<slug>/<ID>`). Any dedup that assumes the slug form MISSES
them:

```python
# WRONG — only matches slug-form URLs, misses bare /jobs/<ID>
m = re.search(r'reed\.co\.uk/jobs/[^/]+/(\d+)', u)

# RIGHT — bulletproof: slug OR bare, with a 6-8-digit id fallback
m = (re.search(r'/jobs/[^/]+/(\d+)', u)
     or re.search(r'/jobs/(\d+)', u)
     or re.search(r'(\d{6,8})(?:\?|$)', u))
```

This bit in TWO places:
- **Manual dedup** in ad-hoc `execute_code` (missed ~99 already-applied
  rows → "NEW on-profile: 148" was wrong; correct dedup = 100 already
  in tracker).
- **`feed.py`'s own `load_seen`** — it reported "0 already tracked"
  on a re-source even though my 8 applied IDs WERE in the tracker. The
  `load_seen` regex in `feed.py:51`
  (`r"reed\.co\.uk/jobs/[^/,\s]+/([0-9]+)"`) is slug-form only, so
  bare-URL tracker rows never match → every re-source looks 100% fresh.
  **Fix:** change `feed.py:51` regex to the bulletproof form above, OR
  always cross-check a re-source's emitted ids against the tracker with
  `grep -c "<id>" application-tracker.csv` before crediting any card as NEW.

**Consequence:** a `--pages 1` harvest + slug-only dedup made Reed look
"fully harvested" for 15 passes. With `--pages 4 --all` it returned
**588 unique / 326 on-profile / 102 precise-Jane-profile UNapplied** jobs.
Pagination + correct dedup is a HARD precondition for any exhaustion claim
(see SKILL.md §UNDER-AUTOMATED-RE-INJECTION pass #2).

## 2. Off-profile leakage through loose PROFILE regex

A broad keyword allowlist pulls roles Jane is NOT (a mid UX/Service
Designer/BA with ~8 yrs experience, NOT a new grad, NOT a developer,
NOT a senior/lead):

```python
# WRONG — matches "graduate sales", "senior product designer",
# "AI service designer (SC cleared)", "product owner (SAP/Cloud/AI)"
PROFILE = re.compile(r'\b(ux|user experience|service design|...|graduate|product owner)\b', re.I)
```

- `graduate` → Graduate Sales / Planner / Recruitment Consultant / Software
  Developer — OFF profile (Jane isn't a new grad).
- `product owner` → matches "AI Product Owner", "SAP Product Owner
  S/4 HANA", "Cloud Product Owner", "eDiscovery Product Owner" —
  tool-specific PO, OFF profile.
- `service designer` → matches "AI Service Designer (SC cleared)" —
  senior/cleared, OFF profile.
- `product designer` → matches "Senior Product Designer" — OFF profile.

**RIGHT — explicit allowlist + explicit exclude (allowlist wins, then drop):**

```python
ALLOW = re.compile(r'\b(ux designer|user experience designer|service designer|'
    r'interaction designer|product designer|content designer|ux/ui designer|'
    r'ui/ux designer|user researcher|ux researcher|ux writer|'
    r'business analyst|product owner|agile business)\b', re.I)
EXCLUDE = re.compile(r'\b(senior|sr\.?|lead|principal|head|director|manager|'
    r'ai service|sc cleared|graduate|trainee(?!\s+business analyst)|'
    r'developer|engineer|software|freelance|founding|interim|'
    r'power bi|salesforce|fix|api|reinsurance|mortgage|iam|'
    r'legacy|regulatory|data management)\b', re.I)
# keep only: ALLOW match AND no EXCLUDE match AND london/remote
```

Then manually drop the 2-3 tool-specific POs that slip through
(eDiscovery / Bullhorn / Purview / SAP / Cloud Product Owner).

**Rule:** never derive on-profile from a single broad keyword. Build an
explicit allowlist, exclude senior/ai/graduate/developer, then eyeball the
result list for tool-specific POs. The skill's no-fabrication rule means a
loose filter that applies off-profile roles is a HARD FAIL even if Reed's
UI "Submit" fires.

## 3. NO_APPLY_BUTTON = external/premium route (not a wedge)

When `reed_apply.py` prints `NO APPLY BUTTON (none)` for a role that
clearly has an Apply button, it means the posting is an **external/agency
route** (no in-Reed apply modal) — NOT a camofox wedge. These
can't be applied through Reed; they route to employer/agency sites that
need separate credentials. Don't loop on them — skip. (Contrast: a real
wedge returns HTTP 500 on the click and the page stays unchanged; a
NO_APPLY_BUTTON means the button genuinely isn't an in-Reed apply.)
