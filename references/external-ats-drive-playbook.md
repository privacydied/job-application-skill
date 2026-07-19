# External LinkedIn/Indeed ATS — drive playbook (verified 2026-07-19)

Reusable technique for the EXTERNAL apply path (LinkedIn/Indeed posting -> employer ATS that is
NOT Easy-Apply). The prior `external-ats-account-wall-reality.md` wrongly called guest-drivable
ATScrap; this playbook is the working method that produced real `Applied` rows this session.

## Discovery loop (one tab, serial)
1. Source on-profile roles: `python3 sites/linkedin/scripts/feed.py --nav "<search URL>" --all --scrolls 10`
   (search URL: `https://www.linkedin.com/jobs/search/?keywords=<OR bundle>&location=London&f_TPR=r604800&sortBy=DD`).
   Parse the JSON array (it's one pretty-printed array; use `json.JSONDecoder().raw_decode` if there's a
   leading non-JSON line). Keep rows where `eligibility.eligible` AND NOT `eligibility.seniority_flag`.
2. For each on-profile id, open the JD and read the external `safety/go?url=` link, decode the inner
   `url=` param -> that's the employer ATS host. Classify via the cheat-sheet in
   `external-ats-account-wall-reality.md` (Greenhouse/Ashby = drive; iCIMS/EA/CGI/Workday/join = wall).
3. Run the duplicate guard BEFORE driving:
   `python3 -c "import sys;sys.path.insert(0,'sites/_common/scripts');import precheck as p;h=p.already_applied(url='<LI URL>');print('SKIP' if h and p.is_applied(h[0]) else 'DRIVE')"`

## Greenhouse (job-boards.greenhouse.io) — guest-drivable
- Navigate to the decoded `.../jobs/<id>` URL. Form has `first_name/last_name/email/phone/country/resume`
  + `question_*` text fields + EEO selects (optional).
- Fill text fields with the prototype value-setter + `input`/`change` dispatch (minimal per-field
  `cfx.evaluate`, avoid complex array-mapping JS that triggers the camofox wedge).
- **Upload CV**: `python3 -c "import sys;sys.path.insert(0,'sites/_common/scripts');import atsform;print(atsform.upload('#resume','/uploads/base-resume.pdf'))"`.
  The container path `/uploads/<base>.pdf` is MANDATORY — the host path 400s. Verify by the filename
  chip text (input.files[0] reads NONE post-upload; that's normal). See `greenhouse-ats-quirks.md` §5.
- EEO fields: leave optional ones blank (Greenhouse saves blank = "prefer not to say"); disclose age
  ("30-34") + pronouns ("He/Him") per profile; set nationality "British".
- Click "Submit application". Confirmation = "Thank you for applying to <Company>".

## Ashby (jobs.ashbyhq.com) — guest-drivable, full driver
- Navigate to decoded URL; `python3 sites/ashbyhq/scripts/ashby.py reveal`.
- Write a gitignored spec JSON at repo root (`spec_<co>_ashby.json`):
  `{"cv":"base-resume.pdf","fill":{"Name":"Jane Doe","Email":"you@example.com",...},"radios":{"legal right to work":"Yes"}}`.
  Truthful free-text answers only (e.g. the AI-use question -> his applied-AI homelab: llama.cpp, ChromaDB
  RAG, ComfyUI/SD, agentic tooling — the differentiator).
- `python3 sites/ashbyhq/scripts/ashby.py apply spec_<co>_ashby.json` (fills + `check`, stops for review).
- **Location is a typeahead**: `ashby.py fill "Location" "London, UK"` is NOT enough — Ashby needs the
  dropdown option CLICKED. After typing, click the first `[role=option]`/`li` matching "London". Otherwise
  submit fails "Missing entry for required field: Location".
- `python3 sites/ashbyhq/scripts/ashby.py submit` -> "Thanks for applying".

## Walls observed (log `Blocked`, record via `accounts.py` only if user wants pursuit)
- iCIMS (`careers*.icims.com`) — account login. · EA (`jobs.ea.com`) — email-verify. · CGI (`cgi.joyn.com`) — SSL cert error in camofox. · Workday / join.com — account / Google-OAuth.
- `jobs.micro1.ai` — form renders but final step has OPAQUE required number/text fields (no labels) ->
  HARD STOP (can't truthfully answer); skip, don't guess.

## Logging (POSITIONAL args, not flags!)
`python3 sites/_common/scripts/log-application.py "<Company>" "<Role>" "<Source>" "<url>" Applied --proof <file>`
- Args 1-5 are POSITIONAL: company, role, source, url, status. `--proof` is the only flag.
- Proof = `applications/<slug>/confirmation.png` (+ a `.txt` with the confirmation string). A row citing
  `--proof` whose file doesn't exist is NOT submitted.
- Count with `python3 sites/_common/scripts/tracker_stats.py --count` (never grep — counts `Applied?` too).

## Camofox wedge gotchas (this session)
- Complex JS (array `.map` over DOM, IIFEs returning objects) 500s on heavy ATS pages. Route reads/fills
  through `bash sites/_common/scripts/cfx.sh eval '<primitive expr>'` (same endpoint, no python 500s), or
  use minimal per-field evaluates.
- `[id^=4009751]` attribute selectors wedge; use a `for` loop building a plain array instead.
