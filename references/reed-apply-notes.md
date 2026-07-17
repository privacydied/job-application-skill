# Reed.co.uk apply notes (verified 2026-07-15)

Reed is a working **non-LinkedIn** channel: sourceable via `sites/reed.co.uk/scripts/feed.py`
(~25 fresh UX/UI/design jobs per London pull) AND applyable on-site. Critically, **Jane's
Reed session is already logged in** — the apply modal shows his profile (name Jane Doe,
email you@example.com, phone, location) and an attached CV (`jane-doe-resume-2021.pdf`),
so apply is a 1-2 click modal, not an external-ATS drive. This makes Reed the highest-yield
non-LinkedIn board after CSJ when LinkedIn is rate-limited.

## Source
```
python3 sites/reed.co.uk/scripts/feed.py --nav "https://www.reed.co.uk/jobs/ux-designer/london"
```
Returns JSON list (title/location/url/salary where extractable). Precheck screen on
junior-mid UX/Service/Product Designer (drop Lead/Senior/UI Architect/UI-UX Developer
financial/graphic-non-UX). On-profile junior-mid fits seen: UX Designer ×N, Trainee UX/UI
Designer, Interactive UX/UI Designer, UX / Service Designer - Consumer Duty.

## Apply (driver: `scripts/reed_apply.py`)
```
python3 scripts/reed_apply.py 57108922 57096916 56992386 ...
```
Flow per posting: click "Apply now" → modal → screening question(s) (Yes/No + Continue) →
"About you" prefilled summary + "Submit application". The driver answers screening "Yes"
(truthful for Jane) and loops Continue→Submit.

## WEDGE — read before debugging a failed Reed apply
1. **`cfx.sh click <ref>` on "Apply now" 500s and the modal does NOT open.** Use the DOM
   click in `reed_apply.py` (`button.btn-primary` filtered by text 'Apply now'). This alone
   was the difference between 0 and 8 successful Reed submits this session.
2. **"Submit application" is NOT in `cfx.sh snap` output** (modal bottom cut off / portal).
   Click it by text via minimal evaluate (`[...].find(x=>x.innerText.trim()==='Submit application')`).
3. **Post-submit redirect 404s** ("Oops, page not found") but the application REGISTERS.
   Verify on `https://www.reed.co.uk/account/jobs/applications` — the "Applications" badge
   count + the card ("Applied 15/07/2026"). Do NOT treat the 404 as a failure.
4. Some postings have 1-4 screening steps before the About-you/Submit page (e.g. "2yrs in a
   UX Design/Interaction Design role?", "Experience within the public sector with GDS?").
   All answerable Yes for Jane → the driver loops them. A posting whose modal needs a CV
   re-upload step may LOOP-END (e.g. UX Writer 57119546) — skip those.

## Volume context (LinkedIn-pivot)
When LinkedIn is rate-limited, Reed is the best remaining on-profile source: a single London
pull yielded ~10 genuinely on-profile junior-mid UX/Service Designer cards, all submittable
in one session via the driver (8 submitted, badge hit 10). CSJ yields only 1 junior-mid
on-profile non-cyber fit; The Dots on-profile roles are stale/dead (see
`sites/the-dots.com/NOTES.md`). So under a LinkedIn hold the realistic non-LinkedIn
on-profile pool ≈ Reed (harvestable) + CSJ (1) — not zero, but far short of 100.
