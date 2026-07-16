# Indeed — cooldown expiry ≠ fresh postings exist; dead-advert & day-rate traps

Two traps burned a full run on 2026-07-14 when chasing "100 more" past an earlier
same-day pass had already drained the fresh inventory.

## 1. Cooldown lifting does NOT mean new postings exist

`board-cooldown.csv` marks a board+query dry for 12h when a pass yields 0 fresh.
After the cooldown passes you are allowed to re-source — but for **low-volume UK
niche inventories** (design / UX / junior-mid DevOps in London) the daily posting
count is tiny and the earlier same-day run already captured essentially ALL of it.
Re-sourcing then returns **0 fresh even with `--force`**, because every current
posting's ID is already in `application-tracker.csv` (the dedup is by stable job
key, not by cooldown state).

**Do NOT conclude "engine broken" from a 0-fresh re-source.** Verify in ONE call:
```bash
python3 sites/indeed.com/scripts/feed.py --nav \
  "https://uk.indeed.com/jobs?q=%22Product+Designer%22&sort=date&fromage=3&l=London" \
  --scrolls 3 --force
# it DOES emit cards (e.g. "Lead Product Designer" @ JPMorganChase) but their
# data-jk IDs are all already in the tracker. 0 "fresh" = already tracked, NOT a
# dead engine or a wall.
```
If `feed.py` emits cards but the run reports 0 fresh → the board is genuinely
**exhausted for today's inventory** (data scarcity, not a mechanism wall). Rotate
to another board or WAIT for the next posting cycle (LinkedIn/Indeed refresh
windows open ~04:00–05:00 BST; the saved alternate queries at
`/tmp/feed/alt_urls.txt` catch titles the bundled OR-query missed once new
postings land).

## 2. SThree "expression-of-interest" dead adverts slip past title precheck

SThree posts a recycled "DevOps Engineer / Platform Engineer / Site Reliability
Engineer — London, £250–£850 a day" advert that is an **expression of interest,
NOT a live vacancy**. The JD body literally says:

> "Please note the content of this advert does not represent a live vacancy."

It carries a normal title (`DevOps Engineer`) so `precheck.py` KEEPS it — but it
is unapplyable. The same recycled advert appeared under multiple `data-jk` IDs
across the alternate-query passes. **Before counting an Indeed DevOps/Platform/SRE
role as applyable, open the JD and drop it if it contains "does not represent a
live vacancy" / "expression of interest".** These dominate the "fresh" hits on
SThree-heavy queries and inflate the candidate count deceptively.

## 3. Agency day-rate / contract posts look on-profile but are off-target

Agency posts (Hays, SThree, Reed, Randstad, Aquent, …) often show as
`Senior Service Designer — Hays — £300–£450 a month` or `£250–£850 a day`. That's a
**contract / day-rate / fixed-term** arrangement, not the permanent junior→mid
target. The title passes precheck but the engagement + agency repost make it
off-profile. **Hard-exclude agency names AND day-rate/contract phrasing in
screening** (`a day`, `per day`, `£[0-9]+ ?- ?£[0-9]+ a day`, `fixed term
contract`, `freelance`) — do not let them count toward the applyable pool.

Combined effect on 2026-07-14: 624 sourced candidates screened to ~6 title-kept,
of which the 5 "DevOps/Platform" were ALL SThree recycled dead adverts + the
"Service Designer" was Hays agency/contract — leaving a real applyable pool of
~4–5 direct-employer, permanent, London roles. Always open-and-verify the JD for
liveness + engagement before crediting a posting as applyable.
