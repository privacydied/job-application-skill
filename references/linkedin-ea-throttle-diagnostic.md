# LinkedIn Easy Apply Throttle — Definitive Diagnostic

When a LinkedIn re-source returns only `NO_BUTTON`/`"promoted"` cards across every
query family (analyst, UR, frontend, junior-design, national), do NOT conclude
"pool exhausted" on the strength of `feed.py` counts alone. Prove WHICH failure
mode it is before reporting a ceiling — there are three distinct causes with three
different remedies:

| Symptom | Cause | Remedy |
|---|---|---|
| Fresh feed = only promoted/blank-title cards; real EA postings never appear | **Account EA inventory throttled** (platform-level) | Time / account recovery. Nothing drivable via this identity. |
| `feed.py` says cooldown-exhausted before fetching | Board cooldown gate | `--force` re-source, or wait out the 12h window |
| Session shows "Sign in" / "Me" missing | Stale/dead LinkedIn session | Re-login (login wall) |

## The throttle proof (run this before declaring the channel dead)

Re-open a posting Jane **successfully applied to in a prior run** (grab 2-3 ids
from `application-tracker.csv` where Source = "LinkedIn Easy Apply", e.g.
`4438002753`, `4439912041`, `4437685944`). For each:

```python
import sys, time
sys.path.insert(0, 'sites/_common/scripts')
import cfx
def read(e):
    for _ in range(12):
        try:
            r = cfx.evaluate(e)
            if r is not None: return r
        except Exception: pass
        time.sleep(1.0)
    return "R?"
cfx.navigate(f'https://www.linkedin.com/jobs/view/{jid}/')
time.sleep(11)
f = read("document.body.innerText.replace(/\\s+/g,' ').trim()")
btn = read("""[...document.querySelectorAll('button')].map(b=>(b.innerText||b.getAttribute('aria-label')||'').trim().toLowerCase()).filter(t=>t=='easy apply'||t=='apply').join('|')||'NONE'""")
print(jid, "real_btn=", btn, "promoted=", ('promoted' in f.lower()))
```

**Interpretation:**
- A previously-drivable posting now shows `real_btn=NONE` + `promoted=True` => the
  account's Easy Apply capability is **throttled at the platform level**. The
  session is fine (nav shows Me/Jane/Jobs/Easy Apply); the *inventory* is gone.
- Verified live 2026-07-15: three postings applied earlier in the same effort all
  flipped to promoted-only. Confirms it is NOT a search-query, cooldown, or session
  issue — re-sourcing (London or national, any family) cannot surface drivable EA
  postings.

## Why this matters

The `apply_ea.py` `NO_BUTTON` fast-fail is **correct**, not a false negative — the
"Easy Apply" text is present on promoted cards but there is no clickable
`<button>` (it is a search-results anchor). Do NOT "fix" the detector or hand-click;
the posting genuinely has no job-apply button. The throttle is the root cause.

## What to report

Once the throttle is proven (previously-applied postings now promoted-only), state
the single true unblock ONCE: *LinkedIn's Easy Apply is platform-throttled for this
account; no re-sourcing or technique recovers it.* Then stop re-emitting it. The
data-scarcity ceiling for LinkedIn EA is real when (a) the throttle diagnostic is
positive AND (b) CSJ's on-profile pool is also drained AND (c) WTTJ (the 3rd
headless channel) lacks credentials. Do not pad the count with off-profile roles.

See also: `linkedin-ea-exhaustion-curve.md` (the 83->111 curve + re-source-yields-0
anti-pattern), `linkedin-promoted-cards.md` (promoted-card shapes),
`volume-driver-pitfalls.md` (the `APPLY_TARGET` DONE-gate + `--refresh` daily-cap
gotcha).
