# Fast loop — model round-trips are the currency

On slow/free inference endpoints (the Hermes path especially), a run's wall-clock is
dominated by **model turns**: every turn pays model latency PLUS re-reading the whole
growing context. Tokens/sec is not the lever — **turn count is**. The loop's batch
scripts exist to compress many would-be turns into one process call each. This file is
the playbook; SKILL.md steps stay authoritative for the mechanics.

## Per-run turn budget (the target shape)

| Phase | Tool | Turns |
|---|---|---|
| 0. Preflight gate | `loop-preflight.py` | 1 |
| 1. Source | `feed.py` per clear board | 1 per board |
| 2. Pre-filter EVERYTHING | `feed.py` output → `precheck.py -` | 1 total |
| 3. Screen+extract ALL survivors | `jd.py --nav-batch urls.txt` | **1 total** |
| 4. Tailor + render the WHOLE work list | `tailor.py apply spec.json --render` | 1–2 total |
| 4b. (optional) Warm apply pages under compute | `warm.py open urls.txt` | 0 (overlaps step 4) |
| 5. Fill+review per posting | `atsform.py apply` (with `"defaults": true`) | 1–2 per posting |
| 6. Submit + log + dismiss | per SKILL.md | 1–2 per posting |

Anti-patterns, each of which multiplies turns by ~5–10x:
- a full-page `snap` of a JD or search page (the single biggest token payload in a
  turn — nav chrome and footers, not signal) when `jd.py` / a scoped `eval` answers it;
- per-field `fill`/`select` calls when `apply` takes the whole form;
- per-card `check_title.py` / tracker greps when `precheck.py` batches the whole feed;
- re-emitting the whole resume HTML per posting when `tailor.py` subs express the
  same edit in ~10 lines of spec (a real tailored resume differs from the master by a
  handful of substitutions — measured: 14 tiny opcodes on 11.5KB);
- interleaving write-work and browser-work per posting instead of batching all
  writing first (each mode switch re-orients the model against the full context).

## The pipeline

```bash
# 2. one call filters every candidate (title tiers, location screen, dedup, salary cache)
python3 sites/linkedin/scripts/feed.py --nav "<searches.csv nav>" \
  | python3 sites/_common/scripts/precheck.py -        # -> keep / review / drop + reasons

# 3. ONE call screens+extracts EVERY surviving posting (was 1 turn per posting).
#    Feed the survivor URLs (one per line) via a file or stdin; get a JSON ARRAY
#    of the same per-posting payloads back. Navigations stay sequential with the
#    usual human_pause between them, so the anti-detection cadence is unchanged.
python3 sites/_common/scripts/jd.py --nav-batch survivors.txt      # or: ... --nav-batch -
#    -> [{title/company, jd_text, requirements, salary, location signals, funnel
#        signature, hidden-text trap scan, title eligibility, _cache}, ...] —
#       screen AND capture the 3–5 must-haves from this ONE payload; never revisit.
#    Payloads are memoized in .jd-cache/ keyed by URL (6h TTL): a re-run (or a
#    resumed partial batch) skips the browser. An under-rendered SPA shell is
#    never cached, so the "came back thin -> re-run once" flow still re-fetches.
#    Single posting / park the tab on the page:  jd.py --nav "<url>"  (--refresh
#    bypasses the cache read).

# 4. ONE spec tailors + renders the whole work list (subs verified against the master;
#    placeholder / wrong-company / company-mention checks built in)
python3 sites/_common/scripts/tailor.py apply applications/run-spec.json --render
#    compose exact `find` strings with:  tailor.py find "<verbatim snippet>"

# 4b. (optional, overlaps step 4) speculative page-warming — spend the browser's
#    idle time DURING the pure-compute tailor phase pre-loading the apply forms so
#    step 5's page-load latency is already paid. Kick off BEFORE you start writing:
python3 sites/_common/scripts/warm.py open survivors.txt   # -> background tabs + warm-map.json
#    then in step 5, per posting, point atsform at the pre-warmed tab:
export CFX_TAB="$(python3 sites/_common/scripts/warm.py lookup "<apply url>")"  # empty => cold nav
#    ... and reclaim the tabs when the run ends:  warm.py close

# 5. one call per form; constants come from defaults, model writes only JD-specific keys
python3 sites/_common/scripts/atsform.py apply applications/<dir>/apply.json
#    apply.json: {"defaults": true, "upload": {...}, "fill": {"<JD-specific>": "..."},
#                 "review": "<Company>", ...}
#    On the all-OK path the summary is ONE line (N fields filled, review clean); a
#    failure prints the full per-field list so you fix everything in one more turn.
```

`tailor.py` spec shape (one file covers ALL postings in the run):

```json
{"postings": [
  {"dir": "applications/acme-product-designer",
   "company": "Acme",
   "subs": [{"find": "<verbatim master substring>", "replace": "<tailored text>"}],
   "drop": ["<unique text of a bullet to remove — kills its whole <p>/<li> block>"],
   "cover": "@applications/acme-product-designer/cover-draft.md  (or inline text)",
   "must_haves": ["design systems", "Figma"]}
]}
```

Rules of thumb for the spec: `find` strings must be **verbatim** (the master is a
single-line blob — `tailor.py find` pins exact text; never eyeball whitespace);
subs apply in order against the already-tailored text; a FAILed posting still writes
its files for inspection but is excluded from `--render`.

## Hermes vs Claude Code (why batch-tailor is the strategy)

The user runs this loop on **Hermes for its free models** — slow inference, no
subagents. There, inference cannot overlap the browser, so the ONLY way to keep the
browser busy is to front-load all model writing: tailor every posting's resume+letter
in one contiguous pass (step 4), then run the sequential browser fills back-to-back
with nothing between them but `apply` calls. On Claude Code a subagent COULD tailor
posting N+1 while the main agent fills posting N — but with batch-tailoring upfront
that overlap buys almost nothing, so the batched pipeline is the recommended shape on
BOTH agents. One pipeline, no per-agent forks.

The ONE overlap worth taking even after batch-tailoring is `warm.py` (step 4b): the
tailor phase is pure compute with the browser fully idle, so pre-loading the apply
pages then is free wall-clock on BOTH agents — it overlaps browser-I/O (page loads)
under model-compute (writing), not inference under inference, so no subagent is
needed. On Claude Code launch it as a background `Bash` right before step 4; on
Hermes run it as its own step immediately before step 4 (the tabs keep loading while
the model writes). It's a pure optimisation: a URL that fails to warm just falls back
to a normal cold `atsform` nav in step 5.

## What NOT to speed up

The cfx pacing/jitter/orientation dwells are **deliberate anti-detection wall-clock**,
not waste (see ENDPOINT-CAPABILITIES.md). A faster action cadence that trips one
Turnstile costs a full-loop halt + a cooldown up to 24h — orders of magnitude more
than it saves. If `stagetimer` shows `fill`/`source` dominating, the answer is fewer
*actions* (batching), never faster actions. Profile before optimizing:
`export STAGETIMER=1`, then `python3 sites/_common/scripts/stagetimer.py report`
(stages: source / screen / tailor-exec / pdf / fill).
