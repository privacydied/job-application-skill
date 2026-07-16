# Reed deep-harvest engine wedge (verified 2026-07-16)

## Symptom
`feed.py --pages 20 --all` across 12 families stalls: ~6 of 12 `.json`
files land, then the loop hangs ~10 min on one family with
`tcsetattr: Inappropriate ioctl for device` in the process output. The
camofox backend is being rate-limited / wedged by the volume of
sequential page fetches (240 pages in one shell loop).

## Proven-safe ceiling
**12 pages × 12 families** = the verified upper bound. This returned
**588 unique / 326 on-profile / 102 precise-Jane-profile UNapplied**
jobs and completed cleanly. Anything beyond ~12-15 pages per family
buys near-zero marginal inventory (pages 13-20 are rate-limited
AND off-profile — the 20-page run surfaced only 9 "new", all
tool-specific POs / "Technical" BA, i.e. nothing on-profile).

## Detect the wedge BEFORE sinking 10 min
Watch the output dir while the loop runs:
```
ls -1 /tmp/deep_*.json 2>/dev/null | wc -l   # stalls at 6 of 12
```
If the count freezes for >2 min while the family index hasn't advanced,
the engine is wedged — KILL the loop (`process action=kill`) and
proceed with whatever files landed. Do NOT wait it out; it will not
recover within a useful window and the tcsetattr error means the
browser session is degrading.

## Why this matters for the exhaustion claim
A wedged deep harvest can be mis-read as "Reed has nothing new"
if you only check the final file set. Always diff the PARTIAL
files against the tracker — the 6 families that DID land are real
inventory. The 20-page run's value was the 6 completed families,
not the stalled remainder.

## Recovery
After a wedge: idle the backend ~90s (don't restart — `cfx.restart_engine()`
may be a no-op if the NOPASSWD sudoers rule is absent), then
`open-tab "about:blank"` + explicit `nav`. The 12×12 harvest
does not wedge; use it as the canonical "prove Reed exhausted" pass.
