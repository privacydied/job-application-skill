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
import re
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
from precheck import load_tracker, canon_ids, _norm, screen_location  # noqa: E402  (canonical dedup + location screen)

QUEUE = os.path.join(ROOT, "queue.jsonl")
APPLY_EA = os.path.join(ROOT, "sites", "linkedin", "scripts", "apply_ea.py")
ASHBY = os.path.join(ROOT, "sites", "ashbyhq", "scripts", "ashby.py")
GH_APPLY = os.path.join(ROOT, "sites", "greenhouse", "scripts", "gh_apply.py")
LEVER = os.path.join(ROOT, "sites", "lever", "scripts", "lever.py")
RUNCFG = os.path.join(ROOT, "runcfg")
COUNT_FILE = "/tmp/apply_queue_count.json"
DEFAULT_HEADLESS_ATS = {"linkedin-easyapply"}
# Hard-board lanes (2026-08-15). SKILL.md §"apply_queue.py is the WRONG tool for the
# HARD-BOARD loop" was true only because dispatch was hardcoded to apply_ea.py. Ashby and
# Greenhouse are the two GUEST-DRIVABLE ATSes (sites/_common/scripts/ats_router.py), each with
# a shipped driver that fills from apply-defaults.json and refuses to submit unless its own
# pre-submit `check` is clean — so they can be drained headlessly, exactly like Easy Apply,
# without the model in the loop per field. Opt in with `--ats ashby,greenhouse`.
# lever added 2026-08-15: ats_router called it "recognised ATS, no shipped driver", which
# was true only because nobody had turned sites/lever/NOTES.md's recipe into a file.
HARD_BOARD_ATS = {"ashby", "greenhouse", "lever"}
# Easy Apply is FORBIDDEN as a logged application (SKILL.md §Forbidden). Selecting any hard
# board implies "not Easy Apply" unless the caller asks for it by name.
EASYAPPLY_ATS = {"linkedin-easyapply", "reed-easyapply"}


def _slug(*parts):
    s = "-".join(str(p or "") for p in parts).lower()
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s)).strip("-")[:80] or "posting"


_GH_URL = re.compile(r"greenhouse\.io/(?:embed/job_app\?for=([\w.-]+)&token=(\d+)|"
                     r"([\w.-]+)/jobs/(\d+))")
# A Greenhouse job advertised on the EMPLOYER's own careers page carries ?gh_jid=<id> and no
# board slug — e.g. coinbase.com/careers/positions/8126896?gh_jid=8126896. Driving that page
# fails with "no file input for '#resume'", because it is the company's marketing page, not
# the Greenhouse form (34 of 41 failures in one drain). Greenhouse serves the real form from
# the TOKEN ALONE, no slug required — verified live:
#   https://boards.greenhouse.io/embed/job_app?token=<id>   -> renders, has the resume input
# (note job-boards.greenhouse.io/embed/... needs the slug and 404s without it; boards.* does not)
_GH_JID = re.compile(r"[?&]gh_jid=(\d+)")
_GH_EMBED = "https://boards.greenhouse.io/embed/job_app?token=%s"


def _gh_config_from_api(row):
    """Build a Greenhouse config via gen_gh_config (keyless questions API). None if not
    derivable, so the caller can fall back to the minimal config."""
    url = row.get("url") or ""
    m = _GH_URL.search(url)
    if not m:
        # employer careers page carrying ?gh_jid=<id> — rewrite to the canonical embed form
        j = _GH_JID.search(url)
        if j:
            token = j.group(1)
            embed = _GH_EMBED % token
            row = dict(row, url=embed)
            # RECOVER THE BOARD SLUG (2026-08-16). Without it there is no questions API, so the
            # config is minimal and every per-posting required screener blocks the submit — the
            # embed form renders fine but bounces on "This field is required." The slug IS in
            # the rendered embed page (verified: token 8017146 -> "samsara"), though only after
            # JS runs: a plain HTTP GET of that URL returns an empty body. One extra nav buys
            # the full API-built config.
            slug = ""
            try:
                if cfx.goto(embed).get("ok"):
                    slug = cfx.evaluate(
                        "(()=>{const h=document.documentElement.innerHTML;"
                        "const m=h.match(/for=([a-z0-9_.-]{2,40})/i)"
                        "||h.match(/boards\\.greenhouse\\.io\\/([a-z0-9_.-]{2,40})/i);"
                        "return m?m[1]:'';})()") or ""
            except Exception:  # noqa: BLE001
                slug = ""
            if slug and slug not in ("embed", "job_app"):
                print(f"    gh_jid={token} -> slug {slug!r}, using the questions API",
                      file=sys.stderr)
                return _gh_from_slug(slug, token, row)
            print(f"    gh_jid={token} -> embed form (no slug; minimal config)", file=sys.stderr)
            return _minimal_gh(row)
        return None
    # ⛔ THE MATCHED-URL PATH MUST NOT FALL OFF THE END (2026-08-16). It did, for one day.
    # Commit 7a5bca9 inserted `def _gh_from_slug` in the MIDDLE of this function, so everything
    # below the insertion point — the slug/jid extraction, the questions-API build, and BOTH
    # integrity refusals — became unreachable code sitting after that function's `return path`.
    # `_gh_config_from_api` then returned None for every canonical Greenhouse URL, which
    # `_hard_board_config` reads as "not derivable" and answers with the minimal `{"fill": {}}`
    # stub. Net effect was exactly inverted from the design: the questions API ran ONLY for the
    # rare employer-careers `?gh_jid=` case, never for the common job-boards.greenhouse.io rows,
    # so per-posting required screeners stayed empty and every submit bounced on "This field is
    # required." Worse, the two refusals below (anti-AI oath, unanswered required) were bypassed
    # for those rows — a posting demanding an attestation was driven to the submit button.
    # There is now ONE questions-API path, shared by both entry points.
    slug, jid = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
    return _gh_from_slug(slug, jid, row)


def _gh_from_slug(slug, jid, row):
    """Full questions-API config for a posting we reached by slug+id. False = do not drive."""
    try:
        sys.path.insert(0, HERE)
        import gen_gh_config  # noqa: PLC0415
        path, _cfg, unanswered, human, oath = gen_gh_config.build(
            slug, jid, eu="eu.greenhouse.io" in (row.get("url") or ""))
    except Exception as e:  # noqa: BLE001 — API hiccup → minimal config, not a dead posting
        print(f"    questions API failed ({str(e)[:60]}) — minimal config", file=sys.stderr)
        return _minimal_gh(row)
    if oath:
        print("    anti-AI oath on this posting — needs the applicant's own words",
              file=sys.stderr)
        return False        # BLOCKED, not "fall back to a minimal config"
    if unanswered or human:
        for u in (unanswered + human)[:4]:
            print(f"    UNANSWERED_REQUIRED: {u[:90]}", file=sys.stderr)
        return False        # driving this would bounce on a required field — don't spend the tab
    return path


def _minimal_gh(row):
    """Config for a Greenhouse posting we know only by token (no slug -> no questions API).
    gh_apply still fills identity/EEO from apply-defaults and the screener bank; any
    per-posting required screener simply blocks the submit, which is the correct outcome."""
    os.makedirs(RUNCFG, exist_ok=True)
    cfg = {"cv": "base-resume.pdf", "company": row.get("company") or "Unknown",
           "role": row.get("title") or "", "url": row["url"], "source": "Greenhouse",
           "defaults": True, "fill": {}}
    path = os.path.join(RUNCFG, f"{_slug(cfg['company'], cfg['role'])}.greenhouse.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    return path


def _hard_board_config(row, resume, ats):
    """Write (and return the path of) the per-application driver config for a hard-board row.

    Deliberately MINIMAL: identity/contact/EEO all come from the gitignored
    sites/_common/apply-defaults.json at drive time via `"defaults": true` — this file is
    written into runcfg/, which is TRACKED, so it must never carry a real personal value
    (SKILL.md step 12 PII gate). Company/role/url are posting facts, not PII.

    GREENHOUSE gets a RICHER config than this (2026-08-15): its forms carry per-posting
    REQUIRED screeners (right-to-work status, "have you added your full legal name",
    consent selects) whose options must match the employer's exact option TEXT. A minimal
    config leaves those empty and every submit bounces with a bare "This field is required."
    gen_gh_config.py already builds a correct one with NO browser, straight from Greenhouse's
    keyless questions API (which publishes each select's exact `values[].label`) — so use it
    and reserve the tab for submitting. Falls back to the minimal config if the API can't be
    read, and if the generator reports UNANSWERED_REQUIRED we say so rather than driving a
    form that cannot submit."""
    if ats == "greenhouse":
        gh = _gh_config_from_api(row)
        if gh is False:
            return None     # caller maps this to needs-human
        if gh:
            return gh
    os.makedirs(RUNCFG, exist_ok=True)
    cfg = {
        "cv": os.path.basename(resume),
        "company": row.get("company") or "Unknown",
        "role": row.get("title") or "",
        "url": row.get("url"),
        "source": {"ashby": "Ashby", "lever": "Lever"}.get(ats, "Greenhouse"),
        "defaults": True,
        "fill": {},
    }
    path = os.path.join(RUNCFG, f"{_slug(cfg['company'], cfg['role'])}.{ats}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    return path


def _location_block(row):
    """-> reason string if this row is OFF-LOCATION and must not be driven, else None.

    WHY (2026-08-15, caught by driving them): the hard-board lane happily drove Lendable
    (Virginia), Plaid (San Francisco), Quantexa (Ottawa), Notion (New York) and Paddle
    (Toronto) — every one abroad-onsite for a UK-based applicant with no work authorisation
    there. Lendable's form made it explicit: its right-to-work options were "I am a US
    Citizen" / "I require Visa Sponsorship", neither of which is a truthful, eligible answer.
    Each one burned the single serial apply tab on a form that could never be honestly
    submitted. The queue row ALREADY carries `location`, and precheck.screen_location is the
    shipped screen for it — the lane just never asked. Only a hard `drop` blocks; `review`
    (ambiguous/generic-UK) still drives, since the JD is authoritative there."""
    verdict, reason = screen_location(row.get("location") or "")
    if verdict == "drop":
        return reason
    # A remote role restricted to another country is unreachable for the same reason an
    # onsite one abroad is — there is no truthful right-to-work answer. screen_location keeps
    # it (sourcing may still want a human to read the JD); the apply lane, which has no model
    # and pays a whole serial-tab drive per attempt, refuses. See precheck's note: these were
    # the rows that produced drain23's most frequent blocker, "What U.S. State do you reside in?"
    if reason.startswith("remote — region-restricted"):
        return reason
    # screen_location returns `review` for abroad-onsite too ("JD decides"). Inside the
    # apply lane there is no model to decide, and driving is the expensive branch, so treat
    # an explicit abroad reading as a block rather than a maybe.
    if verdict == "review" and reason.startswith("abroad"):
        return reason
    return None


def _drive_hard_board(row, ats, resume, dry_run):
    """Navigate to the posting and hand it to its shipped driver.

    Returns the driver's rc, mapped onto apply_ea's contract so main()'s tally is unchanged:
    0 applied · 3 failed · 5 dry-ok · 7 needs-human · 9 no tab.
    The driver itself owns the irreversible step: `ashby.py apply --submit` submits ONLY when
    every fill step passed AND its pre-submit `check` is clean, so a form with an unanswered
    required field is left filled-but-unsubmitted rather than force-pushed."""
    # goto(), not navigate(): it VERIFIES the page actually rendered. A blank render would
    # otherwise read as "no apply button" and the posting would be written off as a wall.
    try:
        nav = cfx.goto(row["url"])
    except Exception as e:  # noqa: BLE001 — a dead nav is this posting's problem, not the run's
        print(f"    nav failed: {e}", file=sys.stderr)
        return 3
    if not nav.get("ok"):
        print(f"    nav rendered blank ({nav.get('attempts')} attempts) — skipping",
              file=sys.stderr)
        return 3
    cfg_path = _hard_board_config(row, resume, ats)
    if cfg_path is None:
        return 7            # a required question this run cannot answer truthfully
    if dry_run:
        print(f"    dry-run: would drive {ats} with {os.path.relpath(cfg_path, ROOT)}",
              file=sys.stderr)
        return 5
    if ats == "ashby":
        cmd = [sys.executable, ASHBY, "apply", cfg_path, "--submit"]
    elif ats == "lever":
        cmd = [sys.executable, LEVER, "apply", cfg_path, "--submit"]
    else:
        cmd = [sys.executable, GH_APPLY, cfg_path]
    try:
        rc = subprocess.run(cmd, cwd=ROOT, env=os.environ, timeout=420).returncode
    except subprocess.TimeoutExpired:
        return 3
    # A driver that filled but refused to submit (unanswered required field, attestation
    # refusal, CAPTCHA) is NOT a failure of the run — it is one posting needing a human.
    return 0 if rc == 0 else (7 if rc == 1 else 3)


def heal_tab():
    # current_url() SWALLOWS CfxError and returns "" on a dead/blank tab (it never raises),
    # so its truthiness IS the liveness signal — a real http(s) URL means the tab is alive.
    # A bare `try: current_url(); return True` always succeeded, making the recovery loop
    # below dead code and the proactive self-heal a no-op.
    try:
        if cfx.current_url():
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
        hint = (r.get("ats_hint") or "")
        if hint not in headless_ats and headless_ats & HARD_BOARD_ATS:
            # same URL-resolution as the dispatch loop, so a row whose ats_hint is 'unknown'
            # but whose URL is plainly Greenhouse/Lever/Ashby is COUNTED as drivable too.
            try:
                import ats_router  # noqa: PLC0415
                cl = ats_router.classify(r.get("url") or "")
                if cl.get("drivable") and cl.get("ats") in headless_ats:
                    hint = cl["ats"]
            except Exception:  # noqa: BLE001
                pass
        if hint in headless_ats:
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
        # ⛔ THE DEFERRED STORE IS 100% EASY APPLY (2026-08-16). ratelimit.defer() is called
        # from ONE place — the Easy-Apply branch, reachable only when `ats not in
        # HARD_BOARD_ATS` — so every row in here is a LinkedIn Easy-Apply posting. Folding them
        # in unconditionally meant `--ats greenhouse` (the sanctioned hard-board drain, and the
        # only form SKILL.md permits against a real target) still led with Easy-Apply rows:
        # their ats stays 'linkedin-easyapply', so the dispatch loop runs apply_ea.py, which
        # auto-submits off the generic base resume and appends Status=Applied. That is the
        # forbidden application class (SKILL.md §Forbidden) and it inflates the headline count
        # with rows §Count-integrity says must then be deleted by hand. EASYAPPLY_ATS was
        # declared for exactly this guard and never referenced — the guard was written down
        # but never wired. Honour --ats: a lane the caller did not select is never driven.
        refused = [r for r in deferred if (r.get("ats_hint") or "") not in headless_ats]
        deferred = [r for r in deferred if (r.get("ats_hint") or "") in headless_ats]
        if refused:
            print(f"apply_queue: holding {len(refused)} deferred Easy-Apply posting(s) — "
                  f"not in --ats ({','.join(sorted(headless_ats)) or 'default'}). Easy Apply is "
                  f"only ever driven when asked for by name.", file=sys.stderr)
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
        ats = (r.get("ats_hint") or "").strip()
        # ⛔ RESOLVE 'unknown' FROM THE URL (2026-08-16). The funnel sets ats_hint from the
        # SOURCING board, so a row harvested off a company careers page keeps ats_hint
        # 'unknown' even when its URL plainly carries `gh_jid=` (Greenhouse) or a lever.co /
        # ashbyhq.com host. Dispatch keys on ats_hint, so 35 on-profile GREENHOUSE-drivable
        # rows sat untouched in the queue for this entire run — invisible because they were
        # never counted as drivable in the first place. ats_router classifies from the URL
        # alone, no browser, so ask it before writing a row off.
        if ats not in HARD_BOARD_ATS:
            try:
                import ats_router  # noqa: PLC0415
                cl = ats_router.classify(r.get("url") or "")
                if cl.get("drivable") and cl.get("ats") in HARD_BOARD_ATS:
                    ats = cl["ats"]
                    print(f"    ats_hint {r.get('ats_hint')!r} -> {ats} (resolved from URL)",
                          file=sys.stderr)
            except Exception:  # noqa: BLE001 — routing is an optimisation, never a hard dep
                pass
        print(f"\n>>> apply [{ats}] {company} :: {role}", file=sys.stderr)
        blocked = _location_block(r) if ats in HARD_BOARD_ATS else None
        if blocked:
            print(f"    SKIP off-location: {blocked}", file=sys.stderr)
            tally["skipped_location"] = tally.get("skipped_location", 0) + 1
            attempted -= 1
            continue
        if ats in HARD_BOARD_ATS:
            rc = _drive_hard_board(r, ats, resume, dry_run)
        else:
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
        # ...and ONLY for an Easy Apply row. A failed Ashby/Greenhouse submit has nothing to do
        # with LinkedIn's daily cap, but `ratelimit.detect()` reads whatever page is open — on a
        # hard-board failure that could trip the cooldown and BREAK the whole drain off one
        # unrelated posting.
        if ats not in HARD_BOARD_ATS and (rc == 8 or (rc not in (0, 5) and ratelimit.detect(cfx))):
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
