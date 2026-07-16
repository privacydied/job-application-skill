# welcometothejungle.com — verified site notes

Site logic for Welcome to the Jungle (ex-otta). `scripts/` assume the camofox tab is
already on a WTTJ page with `CFX_KEY`/`CFX_TAB` (and optionally `CFX_USER`) exported
(`../_common/scripts/cfx.sh`).

## Canonical login flow (verified)
1. Go to `https://app.welcometothejungle.com/login` (the **app** subdomain — bare
   `welcometothejungle.com/login` and `otta.com/...` 404 or land on marketing).
2. Axeptio consent may paint over the page: click "OK for me" if visible; if only "Manage
   your preferences about cookies" shows, **press `Escape`** to expand, then "OK for me".
   ⚠️ Clicking "Manage preferences" directly TIMES OUT (30s) and on retry navigates to
   `us.welcometothejungle.com/` (wrong site) — avoid.
3. Type Email + Password (empty on first load), submit "Sign in". Success → URL becomes
   `app.welcometothejungle.com/` + "Welcome back, <First>".

## Login pitfalls (false failures)
- **Leftover char from a persisted session** (observed a stray leading `v` in the password)
  yields a false "Incorrect email or password" — always re-type into a CLEARED field and
  confirm the snapshot shows only the fresh value before submitting.
- **"Incorrect email or password" = credentials rejected**, NOT a network/captcha block —
  report distinctly, offer reset / SSO; do NOT blind-retry.
- **Flaky backend nav** ("No browser session") — just re-navigate to the login URL; no
  server-side state lost.

## ⛔ `/jobs` auto-opens the TOP job — it is NOT a list. Re-walking it = INFINITE LOOP
`/jobs` (and `/jobs?query=...`) is an index route that auto-opens the top recommended job
and rewrites the URL to `/jobs/<id>` via `history.replaceState` — a single detail pane
(one `[data-testid=job-card-v2]`), NOT a browsable list, NOT last-viewed memory (the #1
feed card is just sticky across loads; nothing stores the id). The #1 hour-waster: a driver
treats `/jobs` like Indeed, gets bounced to the top job, "finishes", re-navigates to `/jobs`,
gets the SAME top job again (a real run looped on one AlphaSights job for >1h). Rules:
1. **NEVER re-navigate to bare `/jobs` expecting a list** — it always resolves to the single
   top recommendation. There is no multi-job list view.
2. **Enumerate with `scripts/feed.py`** — returns a de-duped JSON list of FRESH
   `{id, url, title, sources}` (tracker-filtered; `--all` to include tracked). **`[]` / exit
   3 = WTTJ feed EXHAUSTED for this profile — stop, do NOT re-walk, switch boards.** The
   profile-matched pool is small (~15) and runs dry fast. Two sources (iterate each by
   navigating straight to `/jobs/<id>`, never `/jobs`):
   - **Home** (`app.welcometothejungle.com/`) — pipeline + inline `[data-testid=preview-card]`
     anchors (~9). `source="home"`.
   - **Themed feeds** — each is its own route `/jobs?theme=<name>` (auto-discovered from home
     `a[href*="theme="]`: fully-remote, recently-funded, newly-added, has-salaries,
     female-leaders, apply-via-otta, preferred-sector). There are NO carousels on WTTJ (fixed
     grid, no infinite scroll). Each theme route also auto-opens only its TOP job, so feed.py
     harvests one fresh lead per theme (~6), total ~15. `source="theme:<name>"`. It does NOT
     click the in-app "Move"/skip control (that mutates the user's real recommendation state).
     `--home-only` skips themes.
3. **NEVER use `www`/`us`/`en` marketing-domain paths** (dead end — below).
4. **Same-id-twice = the loop signal** — advance to the next distinct feed.py id or stop;
   dedup against the tracker AND ids seen this run.

Home cards are anchors (`a[href*="/jobs/"]` in `[data-testid=preview-card]`); the `/jobs/<id>`
DETAIL page is NOT (one `job-card-v2`, its only `/jobs/` anchor is the open job). Enumerate
from HOME (what feed.py does), never a detail page.

## The `www.welcometothejungle.com` marketing site is a DEAD END for sourcing (spiked)
Do NOT try to map its larger listings back to app `/jobs/<id>`. Three fatal blockers:
(1) **no browsable list** — `www…/en/jobs?query=` is a lead-capture funnel ("5193 jobs found…
Match me to jobs" → sign up), zero result anchors for an app session; (2) **disjoint
inventories** — marketing and the app (ex-Otta) are separate products with different pools
(a live app job can read "no longer part of the Jungle" on marketing); (3) **no shared id**
(app ids are opaque tokens; marketing URLs are company/slug). The app's `feed.py` pool (~15)
is the WTTJ ceiling — for more VOLUME source OTHER boards (Indeed, LinkedIn).

## "Apply with your profile" is NOT a PDF upload
WTTJ-native ("apply via otta") applications use the structured WTTJ profile (work
experience/education/snippets auto-populated), no file upload, no free-text cover box (unless
a posting's Application Questions adds one). **Skip the skill's PDF-generation step for
WTTJ-native applies**; only generate a PDF for postings that redirect to an external ATS.

## ✅ Apply flow — DEFAULT to the in-platform driver `scripts/apply.py`
Clicking "Apply" opens a modal; two types (the driver detects by whether "Apply with your
profile" is present):
- **IN-PLATFORM** ("Apply with your profile" present) → **PREFER.** No PDF, no external ATS
  quirks, no reCAPTCHA; profile auto-populates, usually only the company **Application
  Question(s)** need answering.
- **EXTERNAL-ONLY** (only "Apply on [Company]'s website" + "Export profile PDF") → take the
  company site + that ATS's recipe (`sites/ashbyhq|greenhouse|lever|workable|myworkdayjobs/`).
  External ATS is NEVER a skip reason.

**In-platform driver:**
```
apply.py start "<job url>"                    # click Apply, detect modal; in-platform OR prints EXTERNAL:<co>
apply.py answer "salary expectations" "£55k" # fill a typed field (text/url/date OR textarea) by label
apply.py pick "eligible to work in the UK" Yes # select a react-select (Yes/No) dropdown by label
apply.py save                                 # commit the section (required — see below)
apply.py status                               # "All done" + "Send now" enabled?
apply.py send                                 # POINT OF NO RETURN. rc: 0 sent · 1 incomplete · 2 unclear · 3 EXTERNAL_FALLBACK
apply.py open-external                         # on rc 3: click "Apply on <co>'s website" (company ATS opens in a NEW tab)
apply.py resolve-applied <yes|no>             # answer the "Did you apply?" toast (unanswered = FEED LOCKS)
```
- ⛔ **WTTJ clicks need a dispatched MouseEvent sequence, NOT `/click` or DOM `.click()`.**
  camofox's `/click` HANGS (30s timeout) on WTTJ's post-click re-renders, and a bare
  `el.click()` doesn't fire React's synthetic onClick — so Send/radios/Save/modal-close all
  *appeared* to no-op. `apply.py`'s `_react_click` marks the element and dispatches
  `pointerover→pointerdown→mousedown→pointerup→mouseup→click`; ALL its clicks route through it.
- ⚠️ **Application Questions: `answer` for typed fields, `pick` for dropdowns, then `save`.**
  Each question is a label + its control in a SEPARATE sibling div; the typed control is a
  text/url/date `<input>` OR a `<textarea>` (revealed from a "Type your answer here…" `<p>` on
  click). `answer` binds the value to the control whose NEAREST-PRECEDING label matches — never
  the first empty field (the old bug mis-routed answers between fields, e.g. a salary into the
  AI-example box on multi-question forms). Yes/No questions (eligibility, consent, privacy) are
  **react-selects** → use `pick`. **Fill ALL fields, then `save` once** — a section stays "N
  left" until Saved even when every field validates. (Verified on Octopus Money's 10-question
  form: 6 typed + 4 dropdowns → in-platform Send confirmed.)
- ⚠️ **The "write better applications" promo modal RE-MOUNTS and its backdrop intercepts every
  click** until closed — the real reason fills/sends looked dead. `apply.py dismiss-promo`
  (and `start`) closes it via `_react_click` on its X; Escape/`/click` are unreliable.
- Each section (Application Questions / Work experience / descriptions) is collapsible with
  its own pencil-edit + **Save**; Saving one doesn't submit — the top tracks "N section(s)
  left" → "All done!".
- **Dropdowns are react-select** (no a11y ref for the option list): `scripts/opts.py` lists
  options, `scripts/pick.py` selects (CSS-`selector` fallback opens `input#react-select-N-input`,
  waits ~0.8s for the listbox, JS-`.click()`s the matching `[class*=option]` by text). ⚠️ **A
  stale open dropdown blocks the next from rendering — press `Escape` (`cfx.sh press Escape`)
  before opening the next select.** Voluntary-Disclosure EEO questions use the same pattern →
  "Prefer not to say".
- ⚠️ **Free-text fields silently DUPLICATE text** if you `type` into a field with content
  (observed: cover letter appended to itself). Use `scripts/set_textarea.py` (native setter +
  input/change dispatch) and verify the length matches your source before saving.
- "Send now" enables automatically once all required fields validate — **no "are you sure"
  dialog**; clicking it IS the point of no return.
- Success signal to screenshot + log: heading **"We're rooting for you!"** + "We've sent your
  application to [Company]…" + "Application sent [date]".

## ⚠️ In-platform Send FAILS for external-ATS jobs → go to the company ATS (verified Maze→Ashby)
Many "Apply with your profile" jobs are backed by an external ATS (Ashby/Greenhouse/…). WTTJ
tries to relay your in-platform application to it and its backend often **fails**: after Send
you get **"We can't submit your application right now … we couldn't submit your application to
[Company]"** + a fallback **"Apply on [Company]'s website"**. This is NOT a click bug (the Send
fired) — it is the true cause of the old "Send lands, no confirmation" reports. `send` detects
this and returns **rc 3 (EXTERNAL_FALLBACK)**. Then:
1. `apply.py open-external` → clicks "Apply on [Company]'s website"; the ATS opens in a **new
   tab** (find it via `GET /tabs`; the URL names the ATS, e.g. `jobs.ashbyhq.com/<co>/…`).
2. Drive that tab to submission with the ATS recipe (`sites/ashbyhq|greenhouse|lever/…`). Its
   fields mirror the WTTJ ones — plus watch for a required **Location** field (a country
   combobox on Ashby: type "United Kingdom", pick the option; "London" gives *No results*).
3. Back on the WTTJ tab, WTTJ shows a bottom-right **"Did you apply?" [Yes]/[No]** toast.
   **Unanswered it BLOCKS advancing to the next job** (the "carousel lock-up"). Run
   `apply.py resolve-applied yes` (only if you truly submitted; else `no`). Clicking Yes lands
   an acknowledgment page → "Back to Home" returns to the feed.
Log the row from the **company ATS confirmation** (proof=the ATS success banner), Source
"Welcome to the Jungle (Ashby)" — the WTTJ toast is tracking-only, not proof of submission.
