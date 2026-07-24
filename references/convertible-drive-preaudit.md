# Convertible-drive pre-audit (run BEFORE driving any `convertible` row)

The `convertible` class from `scripts/convertible_pool.py` is necessary but NOT sufficient.
Two classes of row pass `convertible` yet must NOT be driven by the agent:

1. **Cross-URL / cross-board duplicates** — same Company+Role already in `application-tracker.csv`
   under a DIFFERENT url/slug (e.g. a WTTJ posting vs the same role on atsdirect-Greenhouse;
   a CSJ advert vs its applicationtrack vacancy). `convertible_pool.py` now ALSO dedups on
   `(company_lower, role_lower)` against the tracker, so it should not emit these — but the
   driver-layer guard is the real backstop (each driver checks the tracker by Company+Role
   before logging, and REFUSES a blind merge when the URL differs).
2. **No-driver sources** — creativepool / escapecity / dezeen / ifyoucould emit `convertible`
   in the loose view but have NO shipped driver; treat them as `manual_vnc` (your VNC labour).

## Reproducible pre-audit (run it, drive only `real_drivable`)

```python
import json, csv, sys
sys.path.insert(0,'scripts')
import convertible_pool as cp

feeds = ["/tmp/atsdirect_lane.json","/tmp/guardian.json", ...]  # every harvested feed
rows=[]
for fp in feeds:
    try: rows += cp.load_rows(fp)
    except Exception as e: sys.stderr.write(f"warn skip {fp}: {e}\n")

seen=set(); uniq=[]
for j in rows:
    u=(j.get("url") or "").strip()
    if not u or u in seen: continue
    seen.add(u); uniq.append(j)

TRACKER="application-tracker.csv"
tracked_urls=set(); cr=set()
with open(TRACKER, newline='') as f:
    for r in csv.DictReader(f):
        tracked_urls.add((r.get("URL") or "").strip())
        cr.add(((r.get("Company") or "").strip().lower(), (r.get("Role") or "").strip().lower()))

from collections import Counter
reasons=Counter(); conv=[]
for j in uniq:
    r=cp.classify_strict(j, tracked_urls, cr)
    reasons[r]+=1
    if r=="convertible":
        key=((j.get("company") or "").strip().lower(),(j.get("title") or "").strip().lower())
        if (j.get("url") or "").strip() in tracked_urls or key in cr:
            reasons["convertible_but_tracked"]+=1
        else:
            conv.append(j)

# driver map: which of these convertibles actually have a shipped driver?
def driver(j):
    ats=(j.get("ats_hint") or "").lower(); src=(j.get("source") or "").lower(); u=str(j.get("url",""))
    if ats=="greenhouse": return "greenhouse"
    if ats=="ashby": return "ashby"
    if "smartrecruiters" in ats: return "smartrecruiters_NO_DRIVER"
    if src=="csj" or "civilservicejobs" in u: return "csj_tal"
    if src=="guardian" or "jobs.theguardian" in u: return "guardian_direct"
    if src=="wttj" or "welcometothejungle" in u: return "wttj_apply"
    if src=="atsdirect": return "atsdirect_"+ats
    if src in ("adzuna","thedots","creativepool","escapecity","dezeen","designweek","ifyoucould"):
        return "NO_DRIVER_"+src
    return "unknown:"+src

print("reject histogram:", dict(reasons))
print("CONVERTIBLE truly-new:", len(conv))
from collections import Counter as C
for k,v in C(driver(j) for j in conv).most_common(): print(f"  {v:3d} {k}")
```

Drive ONLY the rows whose `driver()` returns a shipped-driver name (greenhouse / ashby / csj_tal /
guardian_direct / wttj_apply / atsdirect_*). Everything else is `NO_DRIVER` (your VNC) or
`smartrecruiters_NO_DRIVER` (off-site) — do NOT pad the Applied count with them.

## EYEBALL step is MANDATORY — the classifier cannot see grade / in-platform-vs-external
(2026-07-22 lesson, pairs with `convertible-pool-ceiling.md` §Feed-shape-mismatches.)
`convertible_pool.py` classifies on TITLE + URL + location only. It **cannot** see:
- **CSJ grade** (junior-mid EO/HEO/SEO vs G7+/Head/Director) — the CSJ feed row carries no grade for most design/research titles, so `User Researcher` / `Content Designer` / `Service Designer` survive the lane filter but may be senior (verify the JD, or grep the live posting for "Grade").
- **WTTJ in-platform vs external-only** — the WTTJ feed gives no signal; you must open the row with `apply.py start <url>` and read whether it prints `EXTERNAL-ONLY` (routes to employer ATS, no shipped driver → NO_DRIVER) or in-platform.
- **off-lane drift** — titles like `Associate Dean School of Design`, `Silicon Physical Design Engineer`, `Technical Sourcer`, `Social Researcher`, `Information Access and Compliance Researcher` pass the loose lane regex but are NOT this applicant's lane (product/UX designer). Drop them by hand; driving them = padding.

So: after the preaudit prints the `convertible` list, **read every surviving row's title + drive a JD/apply probe on each** before counting it toward the ceiling. A raw "convertible: N" number is necessary but NOT sufficient.

## Cross-board dupe that slips past Company+Role dedup (2026-07-22)
The preaudit's `cr` set keys on `(company_lower, role_lower)`. **WTTJ feed rows have NO `company` field** (only `id/url/title/sources`), so a WTTJ row's key is `("", "product designer - integration")` while the SAME role on atsdirect is `("typeform", "product designer - integration")` — **different keys, so dedup misses it** and the role double-counts as "fresh" in both feeds. Always cross-check the live tracker by Company+Role (not just URL) for any role that appears in two feeds, and prefer dropping the WTTJ copy when the atsdirect/Greenhouse copy already exists or is tracked.

## Honest-ceiling post-mortem (2026-07-20 "100 more" attempt)

Baseline 358 strict Applied. Full board-set sweep (keyless + tab-bound, CSJ logged in):
643 unique candidates → 78 convertible (strict) → after Company+Role dedup, **67 truly-new**.
Driver spread of those 67: `thedots` 27, `adzuna` 23, `creativepool` 8, `escapecity` 4 = **62 NO_DRIVER**
(undrivable, need VNC); only **5** had a driver: 2 ashby (Primer=borderline architectural; Paddle
already-tracked cross-post), 2 guardian_direct (ACCENTURE = external/account-wall; SEARCHLIGHT =
in-platform but halts at reCAPTCHA grid), 1 greenhouse (Storyblok = no `#resume`, Blocked).
Net autonomous Applied this session: **0**. The convertible pool for this junior→mid London/remote
design/UX applicant is **inventory-exhausted** — 100 was not reachable honestly. Single unblock
= clear LinkedIn/Reed walls + create SuccessFactors RMK accounts (BBC/TfL) + VNC the 62 no-driver
rows. Never fabricate off-profile/senior/Easy-Apply rows to hit a target.

## Guardian driver generalization (2026-07-20)

`sites/jobs.theguardian.com/scripts/apply.py` was HARDCODED to REVIVA SOFTWORKS (company/role +
proof dir), which would MISLOG any other Guardian role under REVIVA's identity. Fixed: it now
derives Company+Role + slug from the live page (`_derive_identity`) and logs under the real
identity. Verified: SEARCHLIGHT (10130380) fills name/email/CV + stages cleanly with `--no-submit`
and no mislog. The reCAPTCHA image-grid at Send is still a sanctioned human noVNC handoff (unchanged).
NOTE: classify a Guardian row as `in-platform` vs `external` at apply time — ACCENTURE (10150420)
classifies `external` (Apply-on-website → employer ATS account wall), so it is NOT drivable despite
appearing in the feed. Only `in-platform` Guardian rows are `guardian_direct`-drivable.
