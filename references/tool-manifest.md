# Task → tool manifest — READ THIS BEFORE WRITING ANY SCRIPT (perf-roadmap E.3)

The #1 cause of wasted work in this skill is **re-implementing a shipped tool** because
its existence wasn't obvious at the moment of need (session amnesia + a large doc
corpus). `run_pass.py` re-wrote sourcing, the title screen, and tracker dedup that all
already existed — and its divergent title filter quietly masked a real bug in the
canonical path. This table is the fast intent→tool lookup so that never repeats.

**Rule: if your task is in the left column, call the tool in the middle — never write a
new one.** A test (`TestNoDivergentTitleScreen`) fails the build if title-screen word
lists reappear outside `check_title.py`.

| I need to… | Use (single source of truth) | Never do instead |
|---|---|---|
| Run the whole sourcing→screening funnel | `pipeline.py` (CLI) or `import pipeline; pipeline.run(...)` | hand-chain feeds+merge+precheck |
| Decide if a run should even start | `loop-preflight.py` / `search_plan.plan()` (SLEEP/WORK/HOLD/DONE) | count tracker rows by hand |
| Source one board | `sites/<board>/scripts/feed.py --nav <url>` | scrape the results page via snapshots |
| Source Adzuna (JSON API, no browser) | `sites/adzuna.co.uk/scripts/feed.py --what "<q>"` (needs `ADZUNA_APP_ID`/`_KEY`, free at developer.adzuna.com) | scrape adzuna pages |
| Screen a title against target-roles tiers | `check_title.check_title(title)` | inline SENIOR/OFF/ONPROFILE word lists |
| Pre-filter a feed (title+location+salary+dedup) | `precheck.py -` (stdin) / `precheck.precheck(list)` | per-card `check_title` + tracker greps |
| Merge several feed passes | `merge_sources.merge_lists(posts)` / `merge(paths)` | hand-rolled dedup loop |
| Screen+extract a JD (nav+requirements+funnel+traps) | `jd.py --nav <url>` / `jd.screen_one(url)` | full-page `snap` of a JD |
| Tailor resume+cover+PDF for the work list | `tailor.py apply <spec> --render` | re-emit the whole resume HTML per posting |
| Render one HTML→ATS-safe PDF | `make-pdf.sh <dir>` | weasyprint/wkhtmltopdf (not installed) |
| Render many PDFs in parallel | `prerender-pdfs.sh <dirs…>` | a serial render loop |
| Fill a whole ATS form in one process | `atsform.py apply <config>` (`"defaults": true`) | per-field `fill`/`select`/`radio` calls |
| Drive an Ashby form | `sites/ashbyhq/scripts/ashby.py apply` | atsform (misses Ashby toggle quirks) |
| Drive LinkedIn Easy Apply | `sites/linkedin/scripts/apply_ea.py` | atsform (shadow-DOM modal) |
| Headlessly apply the whole queue (Easy Apply) | `scripts/apply_queue.py` | a bespoke sourcing+apply orchestrator |
| Answer a gating screener (RTW/sponsorship/notice/…) | `screener.py ask "<q>"` (+`learn`) | re-derive per posting |
| Reuse a company research hook | `company_cache.py get/put "<Company>"` | re-research each time |
| Log a tracker row (dedup-safe, in place) | `log-application.py` | `echo >>` / hand-append |
| Any browser action (nav/click/type/eval/shot/upload) | `cfx.sh` / `cfx.py` (`import cfx`) | the host agent's native browser tools (Hermes `browser_*`, IDE/MCP); raw REST |
| Region-crop screenshot for the vision gate | `cfx.py shot --selector <css>` | full-page screenshot |
| Record/rank per-ATS apply success | `apply_stats.py` (drivers call it) | — |
| Board+query cooldown | enforced INSIDE `feed.py`; inspect via `board_cooldown.py` | check/mark by hand |
| Break cooldown w/ broad alternate queries | `scripts/gen_queries.py` (wider-vocab LI/Indeed URLs, new keys) | hand-build OR-bundle search URLs |
| Handle LinkedIn's daily submission limit | auto in `apply_queue.py` via `ratelimit.py` (detect→save→trip cooldown→switch boards); `references/linkedin-daily-limit.md` | grind failed Easy Apply submits |
| Atomic + locked write to a shared CSV/JSONL | `fsutil.file_lock(path)` + `fsutil.atomic_write(...)` | bare `open(,"w")` on shared state |
| Solve reCAPTCHA v2 (sanctioned) | `recaptcha.py` | — (any other CAPTCHA = hard stop) |

**Before writing a probe/helper**: also check `references/scratch-probes-and-capability-index.md`
— the shipped tool almost always exists. New capability that genuinely doesn't exist yet
→ add it to a shared module AND add a row here, so the next run finds it in one lookup.
