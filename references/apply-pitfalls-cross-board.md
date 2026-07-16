# Cross-board application pitfalls (learned 2026-07-14 run)

Durable lessons from a 10-application run (CSJ/Hackney exhausted → LinkedIn/Indeed/WTTJ/SEEK).
Each is a trap that wasted a submit or a tailoring pass. Encode into the loop.

## 1. LinkedIn Easy Apply — stale-resume trap
The resume picker **persists the last-selected file across applications** (e.g.
`oho-product-designer.pdf` stayed selected on the next run). If you just click
"Upload resume" with the default `resume.pdf` basename, you can silently attach
the WRONG (previous) candidate's PDF. (SKILL.md already flags this; the SAFE
PATTERN: copy each role's PDF to `uploads/` with a **unique basename**
`cp applications/<role>/resume.pdf uploads/<role-short>.pdf`, then
`easyapply.py upload <role-short>.pdf`, and confirm on Review that `resume = <role-short>.pdf`.)

## 2. Detect dead / broken / walled roles BEFORE tailoring
Don't generate a PDF until the apply path is confirmed reachable. Cheap checks:
- **Removed JD**: LinkedIn shows "Unable to load the page — Job id provided may
  not be valid or the job posting has been removed." → dead, replace from pool.
- **Broken aggregator redirect**: the LinkedIn "Apply" safety link, when followed,
  lands on a *mismatched* third-party board (e.g. FetchJobs → thebigjobsite showing
  an unrelated job title). The real apply form never resolves → broken path, replace.
- **Login wall (no guest apply)**: ATS redirects to an account sign-in/register with
  no visible guest flow — observed on `passport.amazon.jobs` (Amazon) and
  `jobs.bhf.org.uk` (British Heart Foundation, "Sign in/Register" only; the 36-input
  "form" is just ASP.NET `__VIEWSTATE` scaffolding, not an application form).
  → needs the candidate's stored credential or skip. Do NOT guess passwords.

## 3. camofox HTTP 500 on evaluate/type — transient, retry
`/tabs/<id>/evaluate` and `/type` intermittently return `HTTP 500 Internal Server
error`, especially right after navigation or a modal open. It is transient: `sleep 1–2`
and re-issue the same call. Never treat a single 500 as a hard failure mid-apply.
(If it persists >3 retries, the tab may have crashed — check `/tabs` list + re-open.)

## 4. SmartRecruiters oneclick-ui — driver is MISSING
`sites/smartrecruiters/NOTES.md` documents a shadow-DOM flow and tells you to use
`scripts/sr.py`, but **`sr.py` does not exist in the repo** (verified 2026-07-14).
The oneclick-ui apply URL is `https://www.smartr.me/oneclick-ui/company/<Company>/publication/<uuid>?...`.
If you must apply there, you'll have to hand-drive via Playwright `role=` selectors
through `cfx.py` click/type (the NOTES' selector recipes are correct), since no
adapter wraps it. Flag this BEFORE investing — prefer an easier board for the same role.

## 5. Ashby toggle backing-checkbox — see SKILL.md apply step 5 + sites/ashbyhq/NOTES.md
`set-toggle` reports success on colour but submit reads a hidden checkbox. Tick the
backing `input[type=checkbox]` too. (Covered in the main SKILL.md.)

## 6. Replacement discipline when a pick dies
Keep a spare pool: after screening, you usually have more on-profile candidates than
the 10 you'll apply. When a pick is dead/broken/walled, pull the next reachable
Easy Apply role from the pool (a fresh `feed.py --nav <design search>` is fast) rather
than blocking. In this run Field + FetchJobs died and Amazon + BHF were walled, so 4
replacements were needed (Flicknmix, Oliver Bernard, + 2 more) to still hit 10.
