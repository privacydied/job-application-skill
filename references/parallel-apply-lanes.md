# Parallel apply lanes — safe multi-tab driving (verified 2026-08-17)

SKILL.md says **"SERIALIZE ALL BROWSER WORK ON ONE TAB"**, and that rule earned itself: two
processes sharing ONE tab corrupt each other's page state. But the constraint that was
actually load-bearing is *one process per tab*, not *one tab per machine*. With the
**active-tab registry** in `cfx.py` (`claim_tab` / `active_tabs` / `release_tab`), several
drives can run concurrently on tabs of their own.

Measured this session: **3–4 concurrent Greenhouse lanes, ~4× throughput, zero wedges**, with
the engine reporting `activeTabs: 5` and `consecutiveFailures: 0` throughout.

## Why it was unsafe before the registry

`prune_tabs(keep=…)` protects exactly ONE tab — the caller's. Every other process's tab is
fair game and, being older, is reaped FIRST. So any `ensure_tab` (a feed self-healing, a shell
`cfx.py init`, a second agent) silently killed a live drive's tab, surfacing several steps
later as `HTTP 404 Tab not found`. The registry makes "in use" observable across processes:
a driver claims its tab with its pid, `_tab()` refreshes the claim on every REST call, and
prune skips any claim whose owner is alive and recently active.

## The pattern

```bash
# one tab per lane, claimed so nothing reaps it
T=$(python3 -c "import sys;sys.path.insert(0,'sites/_common/scripts');
import cfx;t=cfx.open_tab('about:blank');cfx.claim_tab(t,'lane2');print(t)")

# the lane runner: CFX_TAB is per-lane, everything else is the shipped driver
CFX_TAB="$T" timeout 700 python3 -u sites/greenhouse/scripts/gh_apply.py "applications/_cfg/$c.json"
```

Rules that make it safe:

1. **One config in flight per lane.** Lanes are serial internally; only lanes are parallel.
2. **Partition by COMPANY, never round-robin.** Two lanes driving the same employer race on the
   shared OTP mailbox — verified: two Capital on Tap applications minutes apart, the first
   consumed code `9JKczrWf` and submitted, the second reported `CODE_MISSING` and a correct
   application was logged `Blocked`. `fetch_verification_code`'s consumed-code ledger now stops
   the *wrong* code being used, but the second lane still stalls waiting for its own email.
   Keep an employer's postings in ONE lane.
3. **Stay under the tab budget.** The backend wedges above ~8 live tabs (`TAB_BUDGET = 7`).
   4 lanes + a sourcing tab + a screening tab already reaches 6.
4. **Close the tab when the lane ends** — a finished lane's tab is NOT reclaimed automatically;
   its registry claim expires (dead pid) but the tab stays open and counts toward the budget.
   This session drifted to `activeTabs: 10` that way, one short of the wedge. End every lane with
   `cfx.close_tab("$TAB")`.
5. **Sourcing gets its own tab too** (`pipeline.py --own-tab`, or an explicit claimed tab).
   Feeds navigate whatever `CFX_TAB` points at, so an unclaimed sourcing run walks an apply tab
   away mid-application.

## Cleaning up leaked tabs safely

The registry makes this a one-liner that cannot kill a live drive:

```python
import cfx
live = set(cfx.active_tabs())                    # pid alive AND heartbeat fresh
for t in [x['tabId'] for x in cfx.list_tabs()]:
    if t not in live:
        cfx.close_tab(t)
```

## What this does NOT change

- The **single-serial-tab rule still holds per drive**. Never point two processes at one tab id.
- A **CAPTCHA halt is still a full halt** — parallelism does not license continuing on other
  lanes through a non-sanctioned CAPTCHA.
- Per-posting attempt caps are unchanged (2 real attempts, then `Blocked`).
