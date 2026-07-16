# CSJ Pay-Band Mining (verified 2026-07-15)

`precheck.py` title-seniority gate alone yields ~1 keep on CSJ and hides real
junior-mid volume (the documented "CSJ over-filters on title-only precheck"
trap). The working harvest flow that defeats it — run it verbatim when CSJ
looks "exhausted" after a title-only pass.

## ⚠️ AUTHORITATIVE ON-PROFILE SIGNAL = the feed's `eligibility` dict (not your salary heuristic)
`feed.py` emits, per card, an `eligibility` object:
`{eligible, tier (A/B/C…), matched_phrase, seniority_flag, discipline_flag}`.
**`seniority_flag: False` + `eligible: True` means the feed's own classifier judges the
posting NOT senior — trust it over any ad-hoc salary cut you write.** The ad-hoc filter
`if min(nums) > 52000: continue` (merge script below) WRONGLY excluded genuine EO/HEO/SEO
(£43k–£59k) fits during the 2026-07-15 "LinkedIn-off" run, costing ~6 wasted re-source
passes that "rediscovered" already-applied roles. SEO (£42k–£59k) is mid-grade and
on-profile for Jane (~6 yrs). **Use `eligibility.seniority_flag` as the PRIMARY gate;
treat salary only as a tie-breaker; keep the London/remote location gate.** A card with
`seniority_flag: False` + London/remote + a target-family match is a REAL candidate even
if its salary tops £52k. If you must filter by salary, cap at ~£60k (not £52k) so SEO
bands survive.

## ⚠️ Before treating a re-found card as NEW, grep the tracker for its jcode
`feed.py` dedups against the tracker at emit, but a posting applied in a PRIOR session
(TalentLink flow — e.g. User Researcher 2004993 / 2005241, Business Analyst 2005473 on
2026-07-14/15) still reads "fresh" on a later sweep because the jcode is stable. A broad
re-sweep re-emits already-applied jcodes. **`grep -c "<jcode>" application-tracker.csv`
before investing in a card** — if it's already `Applied`, skip it (re-opening just lands
on the existing "Application received" page, no double-submit). In the 2026-07-15 run, a
broad sweep surfaced 4 "new" candidates; ALL 4 were already-applied (3 via TalentLink,
1 being the blocked MoJ/HMCTS wizard 1999568). The over-filtering above is what made them
look undiscovered — they were never actually missing.

## Why
CSJ grade lives in the JD, not the card. Many EO/HEO (junior-mid, ~£37k–£52k)
posts carry senior-sounding title words ("Service Designer", "Officer",
"Engineer"). Title-only `precheck` drops them. Parse the **salary band minimum**
instead and screen the JD for grade + clearance.

## One-shot source + merge + filter

```bash
cd $HOME/.hermes/skills/productivity/job-application
source .jobenv.run
export CFX_TAB=<live CSJ tab id>          # a tab on a CSJ results/home page
mkdir -p /tmp/csj_src
for kw in "design" "service designer" "interaction designer" "ux designer" \
          "content designer" "user researcher" "business analyst" "analyst" \
          "digital" "research" "product" "accessibility" "web" "officer" "technician"; do
  SID=$(python3 scripts/csj_search.py "$kw" 2>/dev/null | grep SID_URL= | sed 's/SID_URL=//')
  [ -z "$SID" ] && { echo "$kw: NO SID"; continue; }
  python3 sites/civilservicejobs/scripts/feed.py --nav "$SID" --all-pages --force \
    > "/tmp/csj_src/$kw.json" 2>"/tmp/csj_src/$kw.err"
  echo "$kw: $(python3 -c "import json;print(len(json.load(open('/tmp/csj_src/$kw.json'))))" 2>/dev/null) fresh"
done
```

Merge + pay-band filter (dedup on `jcode`; on-profile = min salary <= £52k,
London/remote, non-senior title, in Jane's target-role families):

```python
import json, re, glob
def sal_nums(s):
    if not s: return []
    return [int(x.replace(',','')) for x in re.findall(r'[\d,]{4,}', s) if int(x.replace(',',''))>1000]
FAM = re.compile(r'(designer|interaction|service design|content design|user researcher|'
    r'ux researcher|design research|usability|user research|user experience|frontend|'
    r'front-end|web developer|web design|web content|web editor|wordpress|prototyper|'
    r'design engineer|ux engineer|design technologist|creative technologist|devops|'
    r'site reliability|platform engineer|cloud support|infrastructure|linux|sysadmin|'
    r'systems administrator|web operations|hosting|soc analyst|security analyst|cyber|'
    r'information security|grc|security operations|it support|it technician|desktop support|'
    r'service desk|technical support|1st line|2nd line|first line|second line|'
    r'application support|network technician|accessibility|qa tester|qa analyst|software tester|'
    r'test analyst|uat|quality assurance|accessibility tester|accessibility auditor)', re.I)
BAD = re.compile(r'(senior|lead|principal|staff|head of|chief|director|deputy|manager)', re.I)
seen=set(); out=[]
for f in glob.glob('/tmp/csj_src/*.json'):
    try: d=json.load(open(f))
    except: continue
    for r in d:
        if r.get('id') in seen: continue
        seen.add(r['id'])
        t=r.get('title','')
        if not FAM.search(t): continue
        nums=sal_nums(r.get('salary'))
        if not nums: continue
        if BAD.search(t) and min(nums)>46000: continue   # senior title + high band
        if min(nums)>52000: continue                      # above HEO entry band
        L=(r.get('location') or '').lower()
        if 'london' not in L and 'remote' not in L and 'anywhere' not in L: continue
        out.append(r)
print('on-profile:', len(out))
for r in sorted(out, key=lambda x: min(sal_nums(x.get('salary')))):
    print(f"  {r.get('title')[:50]:50} | {r.get('salary'):19} | {r.get('url')}")
```

## Verified ceiling (2026-07-15)
12 families -> 320 unique jcodes. Filtering to target families + London/remote
yielded 22 cards; of those only 2 were junior-mid-banded AND on-profile title:
both MI5 (Cyber Research Engineer 2004525, SRE Covert Capability 2003197,
£44k–£53k) — but MI5 requires national-security/developed vetting he doesn't
hold -> skip. Every other design/DevOps/security card was £49k+ senior-titled.
**Conclusion: a genuine data-scarcity ceiling, not a tool failure.** State it
once and stop — do NOT pad the count with off-profile intel/defence/finance/policy
roles (no-fabrication rule).

### Second pass — same day (2026-07-15)
Re-swept **all 15 target-role families** (design / service / interaction / ux /
content / user researcher / business analyst / digital / research / product /
accessibility / web / officer / technician / support / tester), London + national,
~2000 unique jcodes after de-dup. Junior-mid on-profile London/remote fits =
**exactly 1**: **Service Designer, UK Export Finance (jcode 2005590, SEO,
£48,750–£59,559, Westminster/London)** — applied end-to-end (S1+S2, confirmed
"Application received"). Every other on-profile-family card was £57k+ senior-titled
(G7 "Senior User Researcher" et al — off-profile per the junior→mid rule) or
MI5/developed-vetting-gated. Hackney = 0 on-profile. Indeed = Cloudflare-walled.
WTTJ = no-creds login wall. **Net: without LinkedIn, the submittable on-profile
pool is ~1 — a 100-target run cannot be met off-LinkedIn.** This re-confirms the
ceiling is inventory, not tooling.

## Then per survivor
Open the JD (`jd.py --nav <jcode url>`), read the "Job grade" row + clearance
line. EO/HEO + no existing-clearance gate = real fit -> drive via tal_eform.py /
tal_sec2.py. MI5/security-service clearance-gated = skip.
