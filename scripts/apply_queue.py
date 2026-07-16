#!/usr/bin/env python3
"""apply_queue.py — headless "drive the whole queue" loop over queue.jsonl (perf-roadmap
F.1). Replaces the session-scratch run_pass.py.

WHY (root-cause fix, not just a rewrite). run_pass.py re-sourced every LinkedIn bundle
ignoring board_cooldown (full browser cost every run, no yield recorded), re-filtered
on-profile with its OWN hardcoded SENIOR_WORDS/OFF_WORDS/ONPROFILE_HINTS lists — the
divergence that quietly held the *only correct* discipline filter while the canonical
check_title path leaked "Electrical/ICT Design Engineer" — and re-deduped with an
O(candidates × filesize) substring scan that false-matched Notes columns. Every one of
those was a shipped tool re-implemented because a parallel orchestrator started outside
pipeline.py. This driver re-implements NONE of it:

  * pipeline.run() (F.2) does sourcing → merge → precheck → jd-screen → queue.jsonl —
    cooldowns, canonical dedup, DONE/SLEEP/HOLD gating, yield ordering, and the (fixed)
    check_title eligibility ALL come from there.
  * queue.jsonl is already ordered easiest-ATS-first (apply_rank) and each row carries
    ats_hint, so this driver dispatches only the rows it can complete FULLY headlessly:
    LinkedIn Easy Apply via apply_ea.py (login-free, profile-driven, self-answers
    screeners from the shared screener bank, logs Applied+proof, records apply-stats).
  * Any other ATS needs a tailored resume/cover letter — a MODEL step — so those rows are
    left in the queue and reported as `needs_model`, never applied off a stale generic PDF.
  * Dedup against the tracker is the canonical precheck.load_tracker map, read ONCE
    (Blocked stays retryable), not run_pass's per-row substring re-read.

USAGE (needs a live tab: CFX_KEY / CFX_TAB in env):
  CFX_KEY=… CFX_TAB=… python3 scripts/apply_queue.py
      [--refresh] [--force] [--boards linkedin,indeed] [--max N] [--dry-run]
      [--resume /uploads/<f>.pdf] [--ats linkedin-easyapply,...]
  --refresh  rebuild queue.jsonl via pipeline.run() first (else use the existing file).
  --force    passed through to pipeline (re-source cooled boards).
  --ats      which ats_hints to drive headlessly (default: linkedin-easyapply).
Exit: 0 ran (see tally) · 10 SLEEP · 11 HOLD · 12 DONE · 9 no-tab · 2 error.
"""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
_COMMON = os.path.join(ROOT, "sites", "_common", "scripts")
sys.path.insert(0, _COMMON)
sys.path.insert(0, os.path.join(ROOT, "sites", "linkedin", "scripts"))
import cfx            # noqa: E402
import pipeline       # noqa: E402  (F.2 importable funnel)
import ratelimit      # noqa: E402  (LinkedIn daily-limit: detect/save/switch boards)
from precheck import load_tracker, canon_ids, _norm  # noqa: E402  (canonical dedup)

QUEUE = os.path.join(ROOT, "queue.jsonl")
APPLY_EA = os.path.join(ROOT, "sites", "linkedin", "scripts", "apply_ea.py")
COUNT_FILE = "/tmp/apply_queue_count.json"
DEFAULT_HEADLESS_ATS = {"linkedin-easyapply"}


def heal_tab():
    try:
        cfx.current_url()
        return True
    except Exception:
        pass
    for _ in range(4):
        try:
            cfx.set_tab(cfx.ensure_tab(persist=False))
            return True
        except Exception:
            time.sleep(4)
    return False


def read_queue(path):
    rows = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
    except FileNotFoundError:
        pass
    return rows


def _handled(row, by_id, by_pair):
    """Already applied/non-retryably tracked? (Blocked stays retryable.) Canonical keys,
    reused from precheck — no substring scan, no per-row file re-read."""
    ids = canon_ids(row.get("url") or "")
    if row.get("id"):
        ids = ids | {str(row.get("id")).lower()}
    for i in ids:
        st = by_id.get(i)
        if st and st.lower() != "blocked":
            return True
    pair = (_norm(row.get("company")), _norm(row.get("title")))
    if pair[0] and pair[1]:
        st = by_pair.get(pair)
        if st and st.lower() != "blocked":
            return True
    return False


def opt(argv, name, default=None):
    if name in argv:
        i = argv.index(name)
        if i + 1 < len(argv):
            return argv[i + 1]
    return default


def main():
    argv = sys.argv[1:]
    refresh = "--refresh" in argv
    force = "--force" in argv
    dry_run = "--dry-run" in argv
    max_n = opt(argv, "--max")
    max_n = int(max_n) if (max_n and max_n.isdigit()) else None
    resume = opt(argv, "--resume", "/uploads/base-resume.pdf")
    boards = opt(argv, "--boards")
    only_boards = boards.split(",") if boards else None
    ats_arg = opt(argv, "--ats")
    headless_ats = set(ats_arg.split(",")) if ats_arg else set(DEFAULT_HEADLESS_ATS)

    # 1) (re)build queue.jsonl via the shipped funnel when asked / when absent.
    if refresh or not os.path.exists(QUEUE):
        result, code = pipeline.run(force=force, only_boards=only_boards, out_path=QUEUE)
        if result.get("verdict") != "WORK":
            print(json.dumps({"verdict": result.get("verdict"),
                              **{k: result[k] for k in ("wake_at", "applied_today", "target")
                                 if k in result}}))
            print(f"apply_queue: pipeline verdict={result.get('verdict')} — nothing to do",
                  file=sys.stderr)
            return code

    rows = read_queue(QUEUE)
    by_id, by_pair = load_tracker()

    drivable, needs_model, skipped = [], [], 0
    for r in rows:
        if _handled(r, by_id, by_pair):
            skipped += 1
            continue
        if (r.get("ats_hint") or "") in headless_ats:
            drivable.append(r)
        else:
            needs_model.append(r)

    # LinkedIn daily-submission cap: if it's still cooling, don't drive Easy Apply rows —
    # they'd just fail. Leave them queued; the loop should be sourcing other boards
    # (search_plan already excludes LinkedIn from sourcing while the cooldown holds).
    rl_active = ratelimit.active()
    if rl_active:
        drivable = [r for r in drivable if (r.get("ats_hint") or "") != "linkedin-easyapply"]
        print("apply_queue: LinkedIn daily-limit ACTIVE — skipping Easy Apply drain; "
              "switch to other boards (CSJ/Indeed/welcometothejungle).", file=sys.stderr)
    else:
        # "apply later": fold previously-saved (rate-limited) postings back in, dropping any
        # already handled since. They lead the drain so a cleared limit retries them first.
        deferred = [r for r in ratelimit.load_deferred() if not _handled(r, by_id, by_pair)]
        if deferred:
            drivable = deferred + drivable
            print(f"apply_queue: re-injecting {len(deferred)} deferred posting(s) saved from "
                  f"an earlier LinkedIn rate-limit.", file=sys.stderr)

    print(f"apply_queue: {len(rows)} in queue · {len(drivable)} headless-drivable · "
          f"{len(needs_model)} need model tailoring · {skipped} already-tracked",
          file=sys.stderr)

    tally = {"applied": 0, "needs_human": 0, "failed": 0, "dry_ok": 0, "other": 0}
    attempted = 0
    tab_dead = False   # contract: exit 9 if the run stopped because the tab died
    rate_limited = False   # LinkedIn daily submission cap hit mid-drain
    for r in drivable:
        if max_n and attempted >= max_n:
            break
        url, company, role = r.get("url"), r.get("company") or "Unknown", r.get("title") or ""
        if not url or not role:
            continue
        if not heal_tab():
            print("apply_queue: TAB DEAD — stopping", file=sys.stderr)
            tab_dead = True
            break
        attempted += 1
        print(f"\n>>> apply [{r.get('ats_hint')}] {company} :: {role}", file=sys.stderr)
        cmd = [sys.executable, APPLY_EA, url, company, role,
               "--resume", resume, "--source", "LinkedIn Easy Apply"]
        if dry_run:
            cmd.append("--dry-run")
        try:
            rc = subprocess.run(cmd, cwd=ROOT, env=os.environ, timeout=360).returncode
        except subprocess.TimeoutExpired:
            rc = 3
        # LinkedIn daily submission cap. apply_ea returns rc==8 when it detected the limit
        # banner AT THE SOURCE (most reliable). Fall back to our own scan for any other
        # non-success rc (older apply_ea, or a limit that surfaced after the modal closed).
        # Either way: SAVE this posting, TRIP the board cooldown, STOP the drain so the loop
        # switches boards. (Detection only — no submit is ever retried.)
        if rc == 8 or (rc not in (0, 5) and ratelimit.detect(cfx)):
            until = ratelimit.trip()
            ratelimit.defer(r)
            rate_limited = True
            print(f"apply_queue: LinkedIn RATE LIMIT — saved '{role}' for later, board "
                  f"cooling until {until}. Switching boards.", file=sys.stderr)
            break
        if rc == 0:
            tally["applied"] += 1
        elif rc == 5:
            tally["dry_ok"] += 1
        elif rc == 7:
            tally["needs_human"] += 1
        elif rc == 3:
            tally["failed"] += 1
        elif rc == 9:
            print("apply_queue: apply_ea reports no tab — stopping", file=sys.stderr)
            tab_dead = True
            break
        else:
            tally["other"] += 1
        print(f"    rc={rc}  (applied={tally['applied']})", file=sys.stderr)
        time.sleep(2)

    # Prune the deferred store of anything that landed this run (fresh tracker read — apply_ea
    # appended its Applied rows). Skip when we just deferred a new one (rl this run).
    if not rl_active and not rate_limited:
        try:
            bid, bpair = load_tracker()
            ratelimit.rewrite_deferred(
                [d for d in ratelimit.load_deferred() if not _handled(d, bid, bpair)])
        except Exception:
            pass

    out = {"verdict": "WORK", "attempted": attempted, "tally": tally,
           "needs_model": len(needs_model), "already_tracked": skipped,
           "tab_dead": tab_dead, "rate_limited": rate_limited,
           "deferred": len(ratelimit.load_deferred()), "queue": QUEUE}
    try:
        with open(COUNT_FILE, "w") as f:
            json.dump(out, f)
    except OSError:
        pass
    print(json.dumps(out))
    return 9 if tab_dead else 0   # exit 9 signals the run stopped on a dead tab (per docstring)


if __name__ == "__main__":
    sys.exit(main())
