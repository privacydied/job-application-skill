# Rotation & recovery learnings (volume run) — durable patterns

Supplements `easyapply-batch-pitfalls.md` + `camofox-session-stability.md`. Point-in-time
narration trimmed; these are the rules that outlive the incident.

## A. apply_ea.py confirmation gaps — RESOLVED (patched in `sites/linkedin/scripts/apply_ea.py`)
1. A direct "sent"/"application submitted" step now logs inline (sets `already_sent`,
   goes straight to `capture_proof_and_log`) — no Review→submit needed.
2. An unanswerable required field bails `7` (NEEDS_HUMAN) on attempt 1, not after the
   attempt cap.
**Do NOT re-add the old manual-reconcile workaround** (nav to job page → check
"Application submitted" → log) unless a batch genuinely leaves a `sent`-but-unlogged role
behind — that's a NEW regression, not the old gap.

## B. TAB-API WEDGE recovery — poll `POST /tabs`, skip the hanging `GET /tabs`
When the engine wedges, `GET /tabs?userId=…` (and `cfx.list_tabs()`/`ensure_tab()` which
call it) HANGS while `GET /health` still says `browserRunning:true`. `POST /tabs` is flaky
but sometimes answers, and a created tab works:
```bash
KEY=$(grep CFX_KEY .jobenv.run | cut -d"'" -f2)
for i in 1 2 3 4 5; do
  RESP=$(timeout 15 curl -fsS -X POST -H "Authorization: Bearer $KEY" \
    -H "Content-Type: application/json" \
    -d '{"userId":"nasirjones","listItemId":"job-apply","url":"https://www.linkedin.com/jobs/"}' \
    "http://localhost:9377/tabs" 2>&1)
  TAB=$(echo "$RESP" | python3 -c "import sys,json;print(json.load(sys.stdin).get('tabId',''))" 2>/dev/null)
  [ -n "$TAB" ] && break; sleep 5
done   # persist TAB into .jobenv.run, then drive.
```
- `about:blank`/`data:` URLs 500 here — POST a real `https://` URL. A `400` = alive but
  bad body (retry); empty/timeout = still wedged (wait).
- TEMPORARY. The real fix is `docker compose restart` (`camofox-backend-recovery.md`); if
  the NOPASSWD grant has lapsed (`sudo: a password is required`) you're blocked until the
  user restarts — surface that, don't loop on the wedge.

## C. DEDUP TRAP — dedup against the ENTIRE tracker, never `date +%F`
A dedup that filters `if date.today() in row[0]` matches 0 rows across a midnight boundary
(rows dated yesterday, clock today) → re-opens and RE-APPLIES done postings (nearly
double-submitted a batch once). **Rule:** build the applied set from ALL tracker rows,
never today-only. Current code is correct — `precheck.load_tracker` reads every row
(date-independent), so the trap is prevented; keep it that way. (Separate & intentional:
`search_plan.applied_today` IS today-scoped — it's the per-DAY target counter, not the
dedup. A session spanning midnight resets that counter; rare, by design.)

## D. Batching model
One role per `apply_ea.py` subprocess, serial (one tab — parallel wedges the engine;
Easy Apply is a single shadow-DOM modal), 2s between. A fresh subprocess per role means a
driver fix applied mid-batch takes effect for later roles without relaunching. The shipped
headless driver is now **`scripts/apply_queue.py`** (drains `queue.jsonl` via
`pipeline.run` + `apply_ea`); prefer it over an ad-hoc shell queue.
