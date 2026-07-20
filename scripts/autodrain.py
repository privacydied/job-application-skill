#!/usr/bin/env python3
"""
autodrain.py — unattended, code-only draining of queue.jsonl (feature-roadmap N.2).

WHY THIS EXISTS. warm_queue.py keeps the queue WARM (sourcing) but never APPLIES — so
submissions still only happen while a model session is live. Yet a whole class of queue rows
needs ZERO model judgment to submit:
  * Reed rows — reed_apply.py drives job page → Apply now → Yes/Continue screeners → Submit,
    with ~86% submit rate on a clean on-profile queue and no free-text at all.
  * LinkedIn Easy-Apply rows whose screeners are all covered by the shared answer bank —
    apply_ea.py fills them from screener.py and only bails NEEDS_HUMAN on an uncovered one.
Those can be drained by a daemon between firings, so a model session then only has to handle
the EXCEPTIONS (novel screeners, essays, borderline titles) instead of every submit.

This does NOT re-implement applying — it DELEGATES to the shipped drivers (reed_apply.py for
Reed, apply_queue.py for Easy-Apply), which already own dedup, cooldown, screener lookup,
proof capture and log-application. autodrain just: self-gates on the checkpoint, partitions
the queue into code-only vs needs-model, drives the code-only rows within a cap, and leaves
needs-model rows for the model.

SAFETY (load-bearing):
  * DRY-RUN BY DEFAULT. It reports what it WOULD drain and drives nothing. `--go` actually
    applies. So a mis-run can't submit.
  * Self-gates via pipeline.plan(): on SLEEP/DONE/HOLD it drains nothing (a HOLD is exactly a
    live CAPTCHA/login hard-stop).
  * ⚠️ CAPTCHA POLICY UNCHANGED. autodrain never solves a non-sanctioned CAPTCHA. If a driver
    reports a CAPTCHA/hard wall, autodrain STOPS draining and records a blocker (blockers.py)
    + notifies — identical halt semantics to the interactive loop. The sanctioned auto-solves
    (reCAPTCHA v2, CSJ ALTCHA) stay inside the drivers; autodrain adds nothing.
  * Honours a cap (--max, default from APPLY_TARGET minus today's applied) so it can't run
    away.

Usage:
  autodrain.py                    # DRY-RUN: partition queue, report code-only vs needs-model
  autodrain.py --go [--max N]     # actually drain code-only rows (needs CFX_KEY + a tab)
  autodrain.py --go --reed-only   # drive only Reed rows this pass
  autodrain.py --go --ea-only     # drive only Easy-Apply rows this pass

CRON (hourly; sources env + ensures a tab, like warm_queue):
  30 * * * * cd /…/job-application && . ./.jobenv 2>/dev/null; \
             python3 scripts/autodrain.py --go >> autodrain.log 2>&1
"""
import json
import os
import re
import subprocess
import sys
import time

_here = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_here)
sys.path.insert(0, os.path.join(_ROOT, "sites", "_common", "scripts"))
import search_plan as sp   # noqa: E402
import precheck            # noqa: E402  (canon_ids -> reed numeric id)
import journal             # noqa: E402  (slugify -> applications/<slug>/ proof dir)

QUEUE = os.path.join(_ROOT, "queue.jsonl")
LOG = os.path.join(_ROOT, "autodrain.log")
REED_APPLY = os.path.join(_ROOT, "scripts", "reed_apply.py")
APPLY_QUEUE = os.path.join(_ROOT, "scripts", "apply_queue.py")
LOG_APP = os.path.join(_ROOT, "sites", "_common", "scripts", "log-application.py")

# markers a delegated driver prints when it hits a hard wall we must HALT on (never bypass).
_CAPTCHA_MARKERS = re.compile(r"\b(turnstile|hcaptcha|captcha)\b", re.I)


def _logline(msg):
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {msg}"
    print(line)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def load_queue():
    rows = []
    try:
        with open(QUEUE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except ValueError:
                        continue
    except (FileNotFoundError, OSError):
        pass
    return rows


def _reed_id(row):
    url = (row.get("url") or "")
    if "reed.co.uk" not in url.lower():
        return None
    for i in precheck.canon_ids(url):
        if i.isdigit() and 5 <= len(i) <= 8:
            return i
    return None


def partition(rows):
    """Split queue rows into code-only drivable groups vs needs-model.
    Returns {reed: [ids], ea: [rows], needs_model: [rows]}."""
    reed, ea, needs = [], [], []
    for r in rows:
        if r.get("verdict") == "review":
            needs.append(r)          # ambiguous location — the model decides
            continue
        rid = _reed_id(r)
        if rid:
            reed.append((rid, r))    # keep the ROW too, for post-submit tracker logging
        elif r.get("ats_hint") == "linkedin-easyapply":
            ea.append(r)
        else:
            needs.append(r)          # greenhouse/workday/external/etc. — need tailoring/judgment
    return {"reed": reed, "ea": ea, "needs_model": needs}


def _capture_reed_proof(row):
    """Screenshot the current (post-submit confirmation) tab into applications/<slug>/ so a Reed
    submit can be logged strict **Applied**. Falls back to a .txt capture of the confirmation text
    if the screenshot endpoint flakes (mirrors apply_ea) — either satisfies log-application's
    Applied proof-gate. Returns a proof path, or None (⇒ caller logs Applied? instead)."""
    import cfx
    slug = journal.slugify(row.get("company") or "", row.get("title") or row.get("role") or "")
    appdir = os.path.join(_ROOT, "applications", slug)
    os.makedirs(appdir, exist_ok=True)
    png = os.path.join(appdir, "confirmation.png")
    try:
        cfx.shot(png)
        if os.path.isfile(png) and os.path.getsize(png) > 1024:
            return png
    except Exception as e:  # noqa: BLE001
        _logline(f"reed: screenshot failed for {slug}: {e}")
    try:
        body = cfx.evaluate("(document.body?document.body.innerText:'').slice(0,2000)") or ""
    except Exception:  # noqa: BLE001
        body = ""
    if body.strip():
        txt = os.path.join(appdir, "confirmation.txt")
        with open(txt, "w", encoding="utf-8") as f:
            f.write(body)
        if os.path.getsize(txt) > 0:
            return txt
    return None


def _log_reed_applied(row, url, proof):
    """Record a driven Reed submit so the NEXT pass DEDUPS it (reed_apply.py logs nothing and
    autodrain used to write nothing back → duplicate applications every pass). Logs strict
    **Applied** WITH the captured --proof; if no proof could be captured, falls back to
    **Applied?** (log-application refuses Applied without proof). Either status lands the row in
    the tracker so the next pass skips it."""
    company = (row.get("company") or "").strip() or "(unknown)"
    role = (row.get("title") or row.get("role") or "").strip() or "(unknown)"
    u = url or row.get("url") or ""
    if not u:
        return None
    status = "Applied" if proof else "Applied?"
    cmd = [sys.executable, LOG_APP, company, role, "Reed", u, status, "--append-new",
           "--notes", "autodrain Reed auto-submit"]
    if proof:
        cmd += ["--proof", proof]
    try:
        subprocess.run(cmd, capture_output=True, text=True, cwd=_ROOT, timeout=30)
        return status
    except Exception as e:  # noqa: BLE001 — logging must never crash the drain
        _logline(f"reed: log-application failed for {u}: {e}")


def _run(cmd, timeout):
    """Run a delegated driver; return (returncode, combined_output)."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, cwd=_ROOT,
                           env=os.environ, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired as e:
        return 124, f"TIMEOUT after {timeout}s: {e}"


def _halt_on_captcha(output):
    """A delegated driver surfaced a non-sanctioned CAPTCHA / hard wall → record a blocker,
    notify, and signal STOP. CAPTCHA policy is unchanged: we HALT, never solve."""
    if _CAPTCHA_MARKERS.search(output or ""):
        try:
            import blockers
            blockers.record("captcha", "autodrain",
                            what="a delegated driver hit a non-sanctioned CAPTCHA during an "
                                 "unattended drain — the drain HALTED (policy: never auto-solve). "
                                 "Solve via VNC, then resume interactively.")
        except Exception:  # noqa: BLE001
            pass
        return True
    return False


def main():
    argv = sys.argv[1:]
    go = "--go" in argv
    reed_only = "--reed-only" in argv
    ea_only = "--ea-only" in argv

    def opt(flag, default=None):
        return argv[argv.index(flag) + 1] if flag in argv and argv.index(flag) + 1 < len(argv) else default

    # self-gate: never drain during SLEEP/HOLD (HOLD = a live hard-stop). Pass the SAME
    # target the cap uses, so a raised APPLY_TARGET doesn't false-trip the DONE gate. A DONE
    # with headroom (clear searches remain) is not a reason to skip draining an existing
    # queue, so DONE only skips when there is genuinely nothing actionable.
    target = int(os.environ.get("APPLY_TARGET") or sp.DEFAULT_TARGET)
    plan = sp.plan(target=target)
    if plan["verdict"] in ("HOLD", "SLEEP"):
        _logline(f"SKIP: checkpoint verdict={plan['verdict']} "
                 f"({plan.get('note','') or plan.get('captcha_hold','')})")
        return 0

    rows = load_queue()
    part = partition(rows)
    # DEDUP Reed against the tracker (mirror apply_queue._handled: a tracked id is handled
    # unless it's Blocked, which stays retryable). reed_apply.py logs nothing, so without this
    # a Reed row already submitted on a prior pass re-sources and gets RE-SUBMITTED every pass.
    by_id, _by_pair = precheck.load_tracker()
    reed_pending = [(rid, r) for (rid, r) in part["reed"]
                    if not (by_id.get(rid) and by_id.get(rid).lower() != "blocked")]
    n_reed_tracked = len(part["reed"]) - len(reed_pending)
    n_reed, n_ea, n_needs = len(reed_pending), len(part["ea"]), len(part["needs_model"])
    _logline(f"queue={len(rows)}: reed={n_reed} (+{n_reed_tracked} already-tracked, skipped) "
             f"ea={n_ea} needs_model={n_needs}")

    # cap: default = remaining headroom under APPLY_TARGET (today), min 0.
    applied_today = plan.get("applied_today", 0)
    default_cap = max(0, target - applied_today)
    cap = int(opt("--max", default_cap))

    if not go:
        print("\nDRY-RUN (no applications submitted). --go to drain.")
        print(f"  code-only drivable now: {n_reed} Reed + {n_ea} Easy-Apply "
              f"(cap would be {cap}; APPLY_TARGET={target}, applied_today={applied_today})")
        print(f"  needs model judgment (left in queue): {n_needs} "
              f"(greenhouse/workday/external/review rows — tailor + apply interactively)")
        if cap == 0:
            print("  ⚠️ cap is 0 (target met today) — raise APPLY_TARGET or pass --max N to drain more.")
        return 0

    if not os.environ.get("CFX_KEY"):
        _logline("SKIP --go: no CFX_KEY in env (source .jobenv first).")
        return 0
    if cap <= 0:
        _logline(f"SKIP --go: cap={cap} (target {target} met, applied_today={applied_today}). "
                 f"Raise APPLY_TARGET or pass --max N.")
        return 0

    try:
        import cfx
        cfx.set_tab(cfx.ensure_tab(persist=False))
    except Exception as e:  # noqa: BLE001
        _logline(f"SKIP --go: could not ensure a tab ({e})")
        return 0

    drained = 0
    # ── Reed first (highest submit rate, cleanest code-only path) ────────────
    # Drive ONE id at a time: after each reed_apply SUBMITTED the tab is left on that posting's
    # confirmation page, so we can screenshot it and log strict **Applied** (with --proof) per id,
    # instead of a batch that leaves only the last page capturable.
    if reed_pending and not ea_only and drained < cap:
        batch = reed_pending[:cap - drained]
        _logline(f"reed: driving {len(batch)} id(s) one-at-a-time via reed_apply.py (per-id proof)")
        n_applied = n_unconfirmed = 0
        for rid, row in batch:
            if drained >= cap:
                break
            rc, out = _run([sys.executable, REED_APPLY, rid], timeout=90 + 120)
            if _halt_on_captcha(out):
                _logline("HALT: Reed drain hit a non-sanctioned CAPTCHA — blocker recorded, stopping.")
                return 0
            if not re.search(r"\[" + re.escape(rid) + r"\]\s+SUBMITTED", out):
                tail = (out.strip().splitlines() or ["(no output)"])[-1]
                _logline(f"reed: {rid} not submitted (rc={rc}, {tail[:90]})")
                continue
            m = re.search(r"\[" + re.escape(rid) + r"\]\s+SUBMITTED2?\s+\(url=([^)]*)\)", out)
            url = m.group(1) if m else ""
            proof = _capture_reed_proof(row)                 # screenshot the confirmation (+ .txt fallback)
            status = _log_reed_applied(row, url, proof)
            drained += 1
            if status == "Applied":
                n_applied += 1
            else:
                n_unconfirmed += 1
            _logline(f"reed: {rid} SUBMITTED -> {status} (proof={os.path.basename(proof) if proof else 'none'})")
        _logline(f"reed: done — {n_applied} Applied (with proof), {n_unconfirmed} Applied? (no proof)")

    # ── Easy-Apply via the existing queue driver ─────────────────────────────
    if part["ea"] and not reed_only and drained < cap:
        room = cap - drained
        _logline(f"ea: driving up to {room} Easy-Apply row(s) via apply_queue.py")
        rc, out = _run([sys.executable, APPLY_QUEUE, "--ats", "linkedin-easyapply",
                        "--max", str(room)], timeout=room * 120 + 180)
        if _halt_on_captcha(out):
            _logline("HALT: Easy-Apply drain hit a non-sanctioned CAPTCHA — blocker recorded, stopping.")
            return 0
        submitted = out.upper().count("SUBMITTED") + out.count("APPENDED")
        drained += submitted
        _logline(f"ea: apply_queue rc={rc}, ~{submitted} submitted")

    _logline(f"done: ~{drained} code-only application(s) this pass; {n_needs} left for the model.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
