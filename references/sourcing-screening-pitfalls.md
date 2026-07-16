# Sourcing & screening pitfalls — re-mining, live-check, location (2026-07-14)

Strategic lessons from a run that *under-counted* the applyable pool, then
over-counted it, before landing on the truth.

## 1. Precheck over-drops good candidates — RE-MINE the raw set
`precheck.py` + the title pre-filter correctly drop senior/agency/off-location cards,
but card **metadata is junky**: titles like `Service Designer - London - Indeed.com`
have an EMPTY company field, and agency names (Hays, SThree) only appear on the JD
page, not in the feed metadata. Result: genuinely on-profile direct-employer roles
get dropped. **After the normal pipeline, re-mine the raw candidate set
(`all_results.json`) for direct employers:**

```python
KEEP = re.compile(r'product designer|ux ?designer|ui ?designer|user researcher|'
  r'interaction designer|service designer|design technologist|front.?end|web developer|'
  r'web designer|digital designer|content designer|it support|service desk|desktop support|'
  r'devops|site reliability|platform engineer|cloud support|ux writer|usability|prototyper|'
  r'support analyst|technician', re.I)
AGENCY = re.compile(r'sthree|hays|reed|randstad|aquent|oscar|burnett|protocol|spencer|'
  r'argyll|brook|idg|harvey nash|trussle|search partners|recruitment|consultancy|'
  r'crossing hurdles|quik hire|hire feed|jobgether|dataannotation|talenthub', re.I)
SENIOR = re.compile(r'\b(senior |sr\.? |lead |head of|principal|staff|director|chief|'
  r'deputy|manager)\b', re.I)
BADENG = re.compile(r'\b(asic|fpga|semiconductor|geotechnical|civil|building services|'
  r'structural|mechanical|electrical|hardware|firmware|embedded|vlsi|traffic|automotive|'
  r'chemical|aerospace|ic design|product design engineer|design engineer)\b', re.I)
```
Keep `KEEP` ∧ ¬`AGENCY` ∧ ¬`SENIOR` ∧ ¬`BADENG`, then verify each survivor is LIVE and
London/remote (§2). This recovered ~11 fresh candidates the first pass had dropped.

## 2. Verify LIVE-status and JD LOCATION per candidate — metadata lies
- **Dead / expression-of-interest adverts:** SThree's "DevOps Engineer" postings are
  recycled *expression-of-interest* ads — the JD says *"the content of this advert
  does not represent a live vacancy"*. They look like real roles, aren't applyable.
  Check: navigate, assert body text does NOT contain `does not represent a live vacancy`.
- **Location is in the JD, not the card.** Many "Digital Designer" / "Web Designer"
  roles are in **Liverpool / Watford / non-London** (e.g. Connect Internet Solutions
  Web Designer = Liverpool L2 6SG). Jane will NOT relocate within the UK — these fail
  the location rule. Read the posting's actual location line, not the search-card city.
- **MI5 / Security Service** roles: clearance is NOT a skip reason — SC/DV vetting is
  granted THROUGH the role post-offer, not held beforehand. APPLY and answer the
  clearance question honestly (no current SC/DV, holds enhanced DBS, eligible + willing
  to be vetted). Only skip on a genuine bar (no driveable apply form, or an explicit
  must-already-hold-active-clearance day-one requirement).
- **Field-based / "retail stores" IT roles** need a full driving licence; Jane holds
  provisional only → skip.
- **"Team Leader" / "Manager"** in title = people-management scope → off-profile
  (junior→mid only).

## 3. Scaling to a large target ("100 more") — the pool drains within a day
A single day's earlier run drains LinkedIn/Indeed two ways: **tracker-dedup** (every
id already in `application-tracker.csv` is filtered) and **board-cooldown** (exhausted
queries auto-marked ~12h). So a same-day "100 more" cannot be met from the bundled
queries alone. To reach a big number:
1. **Wait for cooldowns to lift** (~12h; next morning) then re-source with the
   alternate queries (wider title vocab, remote+London filter, `--force`).
2. **Expand to new boards** when in-scope is exhausted: RemoteOK's SPA *failed to
   load* via camofox (returned no job links — don't assume it works; try Hacker News
   "Who is hiring", Wellfound, or specific company career pages instead).
3. Re-mine (§1) before declaring scarcity — the first precheck pass is conservative.

## 4. Don't re-report the same blocker
The skill already says: on repeated "continue", take a *different* technique (re-mine,
widen query, expand board, rotate to a logged-in board) rather than re-emitting the
identical stop-and-ask summary. Scarcity is real only after §1 re-mine + §2 live/location
checks come up empty across all boards.
