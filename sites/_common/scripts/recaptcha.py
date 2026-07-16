#!/usr/bin/env python3
"""
recaptcha.py — assist with a reCAPTCHA **v2** ("I'm not a robot" checkbox,
invisible badge, or image-grid challenge).

⚠️ STANDING AUTHORIZATION (2026-07-13, user directive). The default skill
policy (SKILL.md) is: on ANY CAPTCHA, STOP and hand it to the user. The user
has explicitly pre-authorized this helper to AUTO-SOLVE reCAPTCHA v2 in ALL
its forms — the checkbox, the invisible badge, AND the image-grid challenge —
whenever one is the only thing blocking a legitimate application for Jane
Doe. It does NOT touch Cloudflare Turnstile / hCaptcha (fingerprint-blocked —
see CAPABILITY-GAPS.md); only Google reCAPTCHA v2.

Mechanism, GROUND TRUTH. The widgets live in cross-origin iframes, so plain
page JS can't reach them — but `frameSelector` (used by both `/click` and the
newer `/eval-frame`) pierces cross-origin frames via Playwright's automation
protocol, not page JS, so the same-origin wall doesn't apply. We read
`#recaptcha-anchor`'s REAL `aria-checked` state directly from inside the anchor
iframe, the bframe's real tile table from inside IT, and the grid geometry the
same way — no inferring pass/fail from main-page-only signals. (A leftover/stale
`api2/bframe` iframe can survive in the DOM after the checkbox already passed,
which is exactly why the ground-truth reads matter.)

Image-grid auto-solve is TWO-PHASE, matching the skill's house style (the agent
supplies vision-reported tile coordinates; the script does the trusted
clicking):
  Phase A  `solve-grid`            -> capture the open challenge (crop + real
                                       instruction text via eval-frame), read
                                       grid geometry, persist pending state, emit
                                       NEED_TILES with instruction + crop + tile
                                       count for the agent's VL read.
  Phase B  `solve-grid --tiles "0 4 7"` -> re-read the LIVE tile geometry
                                       (coords from Phase A go stale if the panel
                                       scrolled or reloaded while the agent read
                                       the crop), click each named tile centre
                                       via trusted click-xy, confirm the clicks
                                       registered, then Verify + re-check. A
                                       dynamic "click verify once there are none
                                       left" challenge re-captures after each
                                       pick instead of Verifying — finalize it
                                       with `--tiles ''` once nothing matches.
                                       New round -> loop to A (capped, plus a
                                       total-capture runaway guard). Passed ->
                                       PASSED. The VL model decides WHICH tiles
                                       match; this code never guesses pixels.

Usage:
    CFX_KEY=... CFX_TAB=... python3 recaptcha.py <command> [args]

  detect                     report whether a reCAPTCHA (checkbox/invisible/grid)
                             is present and its real state; auto-records type.
  click [job_ref]            click the v2 checkbox (or report invisible/nothing).
  wait-token [timeout_s]     for INVISIBLE reCAPTCHA: poll the token post-action.
  recheck [job_ref]          if aria-checked flipped back false (expired),
                             re-click up to 2x with cooldown, then halt.
  challenge-snapshot         crop + real instruction text of an open grid (the
                             Phase-A capture also does this; kept as a standalone).
  solve-grid [--tiles "i.."] the two-phase grid auto-solver (see above).
  check-type <domain>        what CAPTCHA type this domain has shown before.
"""
import csv
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _here)
import cfx  # noqa: E402

ANCHOR_FRAME = 'iframe[src*="api2/anchor"], iframe[src*="enterprise/anchor"]'
BFRAME_FRAME = 'iframe[src*="api2/bframe"], iframe[src*="enterprise/bframe"]'

_ROOT = os.path.join(_here, "..", "..", "..")
CAPTCHA_TYPE_FILE = os.path.join(_ROOT, "captcha-type-memory.csv")
CAPTCHA_AUDIT_FILE = os.path.join(_ROOT, "captcha-audit.csv")
SOLVE_PENDING = os.path.join(_ROOT, "captcha-solve-pending.json")


# --- ground-truth reads -----------------------------------------------------

def _anchor_present() -> bool:
    """Passive main-page check: does the anchor iframe element exist at all?
    Just checking for the iframe ELEMENT's presence is fine from the main page —
    the same-origin wall only blocks reading INSIDE a cross-origin frame, not
    detecting that the iframe tag itself is there."""
    try:
        return bool(cfx.evaluate(
            "!!document.querySelector('iframe[src*=\"api2/anchor\"], iframe[src*=\"enterprise/anchor\"]')"
        ))
    except cfx.CfxError:
        return False


def _badge_present() -> bool:
    """Invisible reCAPTCHA (v2 invisible / v3): no checkbox, just a floating
    badge div — that div lives in the MAIN document even though its own content
    is an iframe, so a plain main-page query is enough to detect it."""
    try:
        return bool(cfx.evaluate("!!document.querySelector('.grecaptcha-badge')"))
    except cfx.CfxError:
        return False


def _anchor_checked():
    """GROUND TRUTH: #recaptcha-anchor's real aria-checked, read directly from
    inside the anchor iframe via eval-frame. Returns True/False, or None if the
    anchor iframe exists but #recaptcha-anchor wasn't found inside it."""
    try:
        raw = cfx.eval_frame(
            ANCHOR_FRAME,
            "(() => { const el = document.querySelector('#recaptcha-anchor'); "
            "return el ? el.getAttribute('aria-checked') : null; })()"
        )
    except cfx.CfxError:
        return None
    if raw == "true":
        return True
    if raw == "false":
        return False
    return None


def _challenge_open() -> bool:
    """Ground truth for 'is an image-grid challenge actually visible', read from
    INSIDE the bframe iframe's own document (real tile table present + a real
    rendered height) — not just 'does a bframe iframe element exist in the main
    DOM', which is exactly the check that reported phantom challenges on a stale
    leftover iframe."""
    try:
        return bool(cfx.eval_frame(
            BFRAME_FRAME,
            "(() => { if (!document.body) return false; "
            "const hasTiles = !!document.querySelector("
            "'.rc-imageselect-table-33, .rc-imageselect-table-44, .rc-imageselect-payload'); "
            "const r = document.body.getBoundingClientRect(); "
            "return hasTiles && r.height > 50; })()"
        ))
    except cfx.CfxError:
        return False  # no bframe iframe at all, or not loaded -- not a challenge


def _token_len() -> int:
    """Secondary signal only (per the module docstring) — kept because it's cheap
    and independent of the ground-truth reads above, not because it's trusted on
    its own. Also the ONLY signal for invisible reCAPTCHA, which has no checkbox
    to read aria-checked from."""
    try:
        n = cfx.evaluate(
            "(() => { const t = document.querySelector("
            "'textarea[name=\"g-recaptcha-response\"], #g-recaptcha-response, .g-recaptcha-response'); "
            "return t ? (t.value||'').length : 0; })()"
        )
        return int(n) if isinstance(n, (int, float)) else 0
    except cfx.CfxError:
        return 0


def _domain() -> str:
    try:
        return urlsplit(cfx.current_url()).netloc or "unknown"
    except Exception:
        return "unknown"


def _save_shot(domain: str) -> str:
    ts = int(time.time())
    path = f"/tmp/recaptcha-{domain.replace('.', '_')}-{ts}.png"
    cfx_sh = os.path.join(_here, "cfx.sh")
    subprocess.run(["bash", cfx_sh, "shot", path], env={**os.environ}, capture_output=True)
    return path


def _clear_pending() -> None:
    """Remove the Phase A -> Phase B handoff file. Called on every terminal
    grid outcome (passed / handed-off) so a later run never picks up stale
    geometry from an already-resolved challenge."""
    try:
        os.remove(SOLVE_PENDING)
    except OSError:
        pass


def _selected_count() -> int:
    """How many grid tiles are currently marked selected, read from inside the
    bframe. reCAPTCHA adds `.rc-imageselect-tileselected` to a <td> the instant
    a click registers — so this is the ground-truth 'did my click actually
    land' signal, independent of whether the eventual Verify passes."""
    try:
        n = cfx.eval_frame(
            BFRAME_FRAME,
            "(() => document.querySelectorAll('.rc-imageselect-tileselected').length)()"
        )
        return int(n) if isinstance(n, (int, float)) else 0
    except cfx.CfxError:
        return 0


# reCAPTCHA's "dynamic" 3x3: picking a match fades it and loads a NEW image in
# the same cell, so you keep selecting until none remain, THEN Verify. The
# canonical instruction phrasing is the reliable signal ("...click verify once
# there are none left"). The static "if there are none, click skip" 4x4 variant
# is deliberately NOT matched here.
_DYNAMIC_RE = re.compile(r"none left|verify once|until there are none", re.I)


def _looks_dynamic(instruction: str) -> bool:
    return bool(_DYNAMIC_RE.search(instruction or ""))


# --- per-domain memory ------------------------------------------------------

def _record_captcha_type(domain: str, captcha_type: str) -> None:
    if not domain or domain == "unknown":
        return
    now = datetime.now(timezone.utc).isoformat()
    header = ["domain", "captcha_type", "last_seen"]
    body = []
    try:
        with open(CAPTCHA_TYPE_FILE, newline="") as f:
            rows = list(csv.reader(f))
        if rows:
            header = rows[0]
            body = [r for r in rows[1:] if r and r[0] != domain]
    except FileNotFoundError:
        pass
    body.append([domain, captcha_type, now])
    # Write via a temp file + atomic replace so a crash mid-write can't truncate
    # the persistent per-domain memory to a partial/empty file (mirrors the
    # tmp+os.replace pattern in board_cooldown.mark()).
    tmp = CAPTCHA_TYPE_FILE + ".tmp"
    with open(tmp, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(body)
    os.replace(tmp, CAPTCHA_TYPE_FILE)


def check_type(domain: str) -> str:
    """What CAPTCHA type has this domain shown before? '' if never seen."""
    try:
        with open(CAPTCHA_TYPE_FILE, newline="") as f:
            for row in csv.reader(f):
                if row and row[0] == domain:
                    return row[1] if len(row) > 1 else ""
    except FileNotFoundError:
        pass
    return ""


# --- audit trail ------------------------------------------------------------

def _audit_log(domain: str, job_ref: str, screenshot_path: str, result: str) -> None:
    is_new = not os.path.exists(CAPTCHA_AUDIT_FILE)
    now = datetime.now(timezone.utc).isoformat()
    with open(CAPTCHA_AUDIT_FILE, "a", newline="") as f:
        w = csv.writer(f)
        if is_new:
            w.writerow(["timestamp", "domain", "job", "screenshot_path", "result"])
        w.writerow([now, domain, job_ref, screenshot_path, result])


# --- commands ---------------------------------------------------------------

def detect():
    if _anchor_present():
        _record_captcha_type(_domain(), "v2-checkbox")
        checked = _anchor_checked()
        if checked is True:
            print("reCAPTCHA v2 present and ALREADY SOLVED (aria-checked=true on #recaptcha-anchor).")
            return 0
        if checked is False:
            challenge = _challenge_open()
            if challenge:
                _record_captcha_type(_domain(), "grid")
            print(f"reCAPTCHA v2 present, unsolved (challenge open: {challenge}).")
            return 0
        token_len = _token_len()
        print(f"reCAPTCHA v2 anchor iframe present but #recaptcha-anchor not found inside it "
              f"— falling back to token signal (len={token_len}).")
        return 0
    if _badge_present():
        _record_captcha_type(_domain(), "invisible")
        token_len = _token_len()
        if token_len > 0:
            print("Invisible reCAPTCHA present, token already populated.")
        else:
            print("Invisible reCAPTCHA present (badge, no checkbox) — nothing to click here. "
                  "The token populates automatically once the real form action (e.g. Submit) "
                  "triggers it. Run `wait-token` right after that action to confirm.")
        return 0
    print("no reCAPTCHA v2 anchor or invisible badge on this page.")
    return 1


def click(job_ref: str = ""):
    domain = _domain()
    if not _anchor_present():
        if _badge_present():
            _record_captcha_type(domain, "invisible")
            print("Invisible reCAPTCHA (badge) — nothing to click; trigger the real form action "
                  "(e.g. Submit), then run `wait-token` to confirm the token populates.")
            return 0
        print("no reCAPTCHA v2 to click.")
        return 1
    _record_captcha_type(domain, "v2-checkbox")
    if _anchor_checked() is True:
        print("already solved (aria-checked=true) — nothing to do.")
        _audit_log(domain, job_ref, "", "ALREADY_SOLVED")
        return 0
    cfx_sh = os.path.join(_here, "cfx.sh")
    subprocess.run(["bash", cfx_sh, "click-frame", ANCHOR_FRAME, "#recaptcha-anchor"],
                   env={**os.environ}, capture_output=True)
    for _ in range(5):
        time.sleep(1.5)
        checked = _anchor_checked()
        if checked is True:
            shot = _save_shot(domain)
            print("PASSED: checkbox aria-checked=true.")
            _audit_log(domain, job_ref, shot, "PASSED")
            return 0
        if checked is False and _challenge_open():
            _record_captcha_type(domain, "grid")
            print("CHALLENGE: image grid opened (the click LANDED). Run `solve-grid` to auto-solve "
                  "(the agent supplies the matching tile indices from the cropped view).")
            _audit_log(domain, job_ref, "", "CHALLENGE")
            return 2
    if _token_len() > 0:
        shot = _save_shot(domain)
        print("PASSED: checkbox accepted (aria-checked read was inconclusive, but the "
              "secondary token signal is non-empty).")
        _audit_log(domain, job_ref, shot, "PASSED_VIA_TOKEN")
        return 0
    print("NO-CHANGE after click: aria-checked still false, no challenge, no token — likely a "
          "fingerprint-distrust situation (as with Turnstile). Hand to the user.")
    _audit_log(domain, job_ref, "", "NO_CHANGE")
    return 3


def wait_token(timeout_s: float = 15.0):
    """For invisible reCAPTCHA: there is nothing to click — poll the main-page
    token until it's non-empty (populates once the real submit/form action
    triggers scoring) or timeout. Call this AFTER that real action, not instead
    of it."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if _token_len() > 0:
            print("TOKEN PRESENT: invisible reCAPTCHA passed.")
            return 0
        time.sleep(1)
    print(f"TIMEOUT after {timeout_s}s: token never appeared. If you haven't triggered the "
          "real form action yet (e.g. clicking Submit), do that first — invisible reCAPTCHA "
          "scores THAT action; there is nothing to click here directly. If you already did "
          "and it still hasn't appeared, hand to the user.")
    return 3


def recheck(job_ref: str = "", max_retries: int = 2, cooldown_s: float = 3.0):
    """v2 tokens expire ("Verification expired" is a real, observed message).
    Call this right before Submit: if aria-checked has flipped back to false since
    it was solved, re-click up to max_retries times with a cooldown between
    attempts (not a tight loop), then halt. Never retries beyond this bound."""
    if not _anchor_present():
        return 0  # nothing to recheck (invisible variant, or no CAPTCHA at all)
    domain = _domain()
    if _anchor_checked() is True:
        return 0  # still good
    print("reCAPTCHA checkbox no longer checked (likely expired) — re-clicking...")
    cfx_sh = os.path.join(_here, "cfx.sh")
    for attempt in range(1, max_retries + 1):
        subprocess.run(["bash", cfx_sh, "click-frame", ANCHOR_FRAME, "#recaptcha-anchor"],
                       env={**os.environ}, capture_output=True)
        time.sleep(cooldown_s)
        if _anchor_checked() is True:
            shot = _save_shot(domain)
            print(f"RE-PASSED on attempt {attempt}.")
            _audit_log(domain, job_ref, shot, f"RE_PASSED_ATTEMPT_{attempt}")
            return 0
        if _challenge_open():
            print("CHALLENGE opened on re-click — run `solve-grid`.")
            _audit_log(domain, job_ref, "", "RECHECK_CHALLENGE")
            return 2
    print(f"Still unchecked after {max_retries} re-click attempts — hand to the user.")
    _audit_log(domain, job_ref, "", "RECHECK_FAILED")
    return 3


def _capture_challenge(out_dir: str = "/tmp"):
    """Read the REAL instruction text directly from inside the bframe via
    eval-frame (exact DOM text, not OCR-guessed), get the challenge's on-screen
    bounding box, take a full screenshot, and crop it to just the challenge for
    a fast, zoomed-in read. Does NOT click any tile. Returns
    {"instruction", "full", "crop"}, or None if no challenge is open.

    This is the single source of truth for a capture — both the standalone
    `challenge-snapshot` CLI command and solve-grid's Phase A call this, so
    solve-grid gets the instruction/crop it JUST took instead of re-reading a
    possibly-stale SOLVE_PENDING file from a previous round."""
    if not _challenge_open():
        return None
    instruction = cfx.eval_frame(
        BFRAME_FRAME,
        "(() => { const el = document.querySelector("
        "'.rc-imageselect-desc-no-canonical, .rc-imageselect-desc, .rc-imageselect-instructions'); "
        "return el ? el.innerText.replace(/\\s+/g,' ').trim() : ''; })()"
    ) or "(instruction text not found in the usual selectors — read the screenshot)"

    bbox_raw = cfx.evaluate(
        "(() => { const el = document.querySelector("
        "'iframe[src*=\"api2/bframe\"], iframe[src*=\"enterprise/bframe\"]'); "
        "if (!el) return null; const r = el.getBoundingClientRect(); "
        "return JSON.stringify({x:r.x,y:r.y,width:r.width,height:r.height}); })()"
    )

    ts = int(time.time())
    full_path = os.path.join(out_dir, f"recaptcha-challenge-{ts}-full.png")
    crop_path = os.path.join(out_dir, f"recaptcha-challenge-{ts}-crop.png")
    cfx_sh = os.path.join(_here, "cfx.sh")
    subprocess.run(["bash", cfx_sh, "shot", full_path], env={**os.environ}, capture_output=True)

    try:
        bbox = json.loads(bbox_raw) if bbox_raw else None
        if bbox:
            from PIL import Image
            img = Image.open(full_path)
            pad = 12
            left = max(0, int(bbox["x"]) - pad)
            top = max(0, int(bbox["y"]) - pad)
            right = min(img.width, int(bbox["x"] + bbox["width"]) + pad)
            bottom = min(img.height, int(bbox["y"] + bbox["height"]) + pad)
            img.crop((left, top, right, bottom)).save(crop_path)
        else:
            crop_path = full_path
    except Exception as e:
        print(f"(crop failed, falling back to the full screenshot: {e})")
        crop_path = full_path

    return {"instruction": instruction, "full": full_path, "crop": crop_path}


def challenge_snapshot(out_dir: str = "/tmp"):
    """CLI-facing wrapper: print the instruction text + screenshot paths for a
    human/agent to read. Does NOT click any tile. See _capture_challenge()."""
    cap = _capture_challenge(out_dir)
    if cap is None:
        print("no challenge currently open.")
        return 1
    print(f"INSTRUCTION: {cap['instruction']}")
    print(f"full screenshot: {cap['full']}")
    print(f"cropped challenge view: {cap['crop']}")
    return 0


# --- grid auto-solve (2026-07-13, standing user authorization) ---------------

def _bframe_geometry():
    """Page-coordinate geometry of the open grid challenge: each tile's click
    centre + the Verify button centre, plus the tile count. Tiles/Verify live
    inside the cross-origin bframe, so their rects are read via eval-frame and
    offset by the bframe iframe's own page position (read from the main page).
    Returns None if no challenge is open."""
    if not _challenge_open():
        return None
    off_raw = cfx.evaluate(
        "(() => { const el = document.querySelector("
        "'iframe[src*=\"api2/bframe\"], iframe[src*=\"enterprise/bframe\"]'); "
        "if (!el) return null; const r = el.getBoundingClientRect(); "
        "return JSON.stringify({x:r.x, y:r.y}); })()"
    )
    if not off_raw:
        return None
    off = json.loads(off_raw)
    tiles_raw = cfx.eval_frame(
        BFRAME_FRAME,
        # Scoped to the actual challenge tables, not a bare 'td' — a bare
        # selector would also pick up any unrelated <td> elsewhere in the
        # bframe (e.g. control/footer layout tables) and throw off every
        # tile index after it.
        "(() => { const t = Array.from(document.querySelectorAll("
        "'.rc-imageselect-table-33 td, .rc-imageselect-table-44 td')); "
        "return JSON.stringify(t.map(td => { const r = td.getBoundingClientRect(); "
        "return {x:r.x, y:r.y, w:r.width, h:r.height}; })); })()"
    )
    verify_raw = cfx.eval_frame(
        BFRAME_FRAME,
        "(() => { const b = document.querySelector('.rc-button-verify, #rc-imagesubmit'); "
        "if (!b) return null; const r = b.getBoundingClientRect(); "
        "return JSON.stringify({x:r.x, y:r.y, w:r.width, h:r.height}); })()"
    )
    # Drop any zero-size tiles (a cell mid-reload can momentarily report 0x0);
    # keeping them would shift every later index off by one relative to what the
    # VL sees in the crop.
    tile_list = [t for t in (json.loads(tiles_raw) if tiles_raw else [])
                 if t.get("w", 0) > 0 and t.get("h", 0) > 0]
    tile_centres = [
        {"x": off["x"] + t["x"] + t["w"] / 2, "y": off["y"] + t["y"] + t["h"] / 2}
        for t in tile_list
    ]
    verify_centre = None
    if verify_raw:
        v = json.loads(verify_raw)
        verify_centre = {"x": off["x"] + v["x"] + v["w"] / 2,
                         "y": off["y"] + v["y"] + v["h"] / 2}
    return {"tiles": tile_centres, "verify": verify_centre, "count": len(tile_centres)}


def _click_xy(x: float, y: float) -> None:
    cfx_sh = os.path.join(_here, "cfx.sh")
    subprocess.run(["bash", cfx_sh, "click-xy", str(int(round(x))), str(int(round(y)))],
                   env={**os.environ}, capture_output=True)


def _click_verify(geo) -> None:
    """Click the Verify/Next/Skip button (same `.rc-button-verify` element
    regardless of its label). Prefer trusted click-xy on the captured centre;
    fall back to a frame-scoped click if geometry never found it."""
    if geo and geo.get("verify"):
        _click_xy(geo["verify"]["x"], geo["verify"]["y"])
    else:
        cfx_sh = os.path.join(_here, "cfx.sh")
        subprocess.run(["bash", cfx_sh, "click-frame", BFRAME_FRAME,
                        ".rc-button-verify, #rc-imagesubmit"],
                       env={**os.environ}, capture_output=True)


# Runaway guard: a dynamic challenge legitimately needs several capture->pick
# cycles, but never this many. Distinct from max_rounds (failed-Verify attempts).
_MAX_CAPTURES = 12


def solve_grid(job_ref: str = "", tiles_arg: "str | None" = None, max_rounds: int = 3):
    domain = _domain()
    round_num = 1     # failed-Verify attempts, bounded by max_rounds
    captures = 1      # total Phase-A captures this solve, bounded by _MAX_CAPTURES
    recapture = False  # Phase B sets this to loop back to a fresh Phase A capture

    # --- Phase B: tile indices supplied, do the trusted clicking ---
    if tiles_arg is not None:
        try:
            with open(SOLVE_PENDING) as _pf:
                pending = json.load(_pf)
        except (FileNotFoundError, json.JSONDecodeError):
            print("no pending grid solve (run `solve-grid` first to capture the challenge).")
            return 1
        # Phase B is normally invoked as `solve-grid --tiles "i.."` with no
        # job_ref of its own (see module Usage) — fall back to the job_ref
        # Phase A already persisted so the audit log doesn't lose it.
        job_ref = job_ref or pending.get("job_ref", "")
        round_num = pending.get("round", 1)
        captures = pending.get("captures", 1)

        # The challenge can pass or vanish while the agent is reading the crop.
        if not _challenge_open():
            if _anchor_checked() is True or _token_len() > 0:
                shot = _save_shot(domain)
                print("GRID SOLVED: challenge already cleared before this click.")
                _audit_log(domain, job_ref, shot, "GRID_SOLVE_PASSED")
                _record_captcha_type(domain, "grid")
                _clear_pending()
                return 0
            print("grid challenge is no longer open and not solved — stale pending state. "
                  "Re-run `solve-grid` to re-capture.")
            _clear_pending()
            return 1

        # Coordinates captured in Phase A go stale if the panel scrolled or
        # reloaded while the agent read the crop — so re-read the LIVE geometry
        # now and click THAT, never the stored coords.
        geo = _bframe_geometry()
        if not geo or not geo.get("tiles"):
            print("couldn't read live grid geometry for the click — hand to the user.")
            _audit_log(domain, job_ref, "", "GRID_SOLVE_NO_GEOMETRY")
            _clear_pending()
            return 3

        stored_count = (pending.get("geometry") or {}).get("count")
        if stored_count is not None and stored_count != geo["count"]:
            # The grid the VL read no longer matches what's on screen, so its
            # indices are meaningless. Re-capture rather than click blindly.
            print(f"grid changed since capture (VL saw {stored_count} tiles, live grid now "
                  f"has {geo['count']}) — re-capturing for a fresh read.")
            recapture = True
        else:
            try:
                idxs = [int(t) for t in tiles_arg.split() if t.strip() != ""]
            except ValueError:
                print(f"couldn't parse tile indices out of --tiles {tiles_arg!r} "
                      "— expected space-separated integers.")
                return 1
            n = len(geo["tiles"])
            bad = [i for i in idxs if not (0 <= i < n)]
            if bad:
                print(f"ignoring out-of-range tile indices {bad} (valid range 0..{n - 1}).")
            idxs = [i for i in idxs if 0 <= i < n]

            for i in idxs:
                _click_xy(geo["tiles"][i]["x"], geo["tiles"][i]["y"])
                time.sleep(0.4)

            dynamic = _looks_dynamic(pending.get("instruction", ""))

            # Ground-truth check that the clicks landed. On a static grid the
            # picked tiles stay selected, so 0 selected after clicking >0 means
            # clicks aren't registering (fingerprint distrust) — bail instead of
            # Verifying an empty selection and burning rounds. (Skipped for
            # dynamic, where a picked tile deselects as its replacement loads.)
            if idxs and not dynamic:
                time.sleep(0.4)
                if _selected_count() == 0:
                    print("clicked tiles but none registered as selected — clicks aren't "
                          "landing (likely fingerprint distrust). Hand to the user.")
                    _audit_log(domain, job_ref, "", "GRID_SOLVE_CLICKS_NOT_LANDING")
                    _clear_pending()
                    return 3

            if dynamic and idxs:
                # Dynamic challenge: each pick fades out and a NEW image loads in
                # its place. Do NOT Verify yet — let the replacements settle and
                # re-capture so the agent looks again. It finalizes by calling
                # `solve-grid --tiles ''` once nothing matches.
                print("dynamic challenge — picked tiles reload with new images; "
                      "re-capturing for another read (finalize later with --tiles '').")
                time.sleep(2.5)
                recapture = True
            else:
                # Static grid, or dynamic finalize (empty selection): Verify now.
                _click_verify(geo)
                time.sleep(2.5)
                if _anchor_checked() is True or _token_len() > 0:
                    shot = _save_shot(domain)
                    print("GRID SOLVED: passed.")
                    _audit_log(domain, job_ref, shot, "GRID_SOLVE_PASSED")
                    _record_captcha_type(domain, "grid")
                    _clear_pending()
                    return 0
                if _challenge_open():
                    round_num += 1
                    if round_num > max_rounds:
                        print(f"GRID FAILED after {max_rounds} rounds — hand to the user.")
                        _audit_log(domain, job_ref, "", "GRID_SOLVE_FAILED_ROUNDS")
                        _clear_pending()
                        return 3
                    print(f"new challenge round {round_num} — re-capturing...")
                    recapture = True
                else:
                    print("GRID: neither passed nor a new round after Verify — likely still "
                          "loading or a misclick. Hand to the user.")
                    _audit_log(domain, job_ref, "", "GRID_SOLVE_AMBIGUOUS")
                    _clear_pending()
                    return 3

        if not recapture:
            # Defensive: every Phase-B branch above either returns or sets
            # recapture. Reaching here means an unforeseen state — hand off.
            _audit_log(domain, job_ref, "", "GRID_SOLVE_UNEXPECTED_STATE")
            _clear_pending()
            return 3

        captures += 1
        if captures > _MAX_CAPTURES:
            print(f"GRID: {_MAX_CAPTURES} captures without solving — stopping to avoid a "
                  "loop. Hand to the user.")
            _audit_log(domain, job_ref, "", "GRID_SOLVE_MAX_CAPTURES")
            _clear_pending()
            return 3

    # --- Phase A: capture the open challenge for the agent's VL read ---
    if not _challenge_open():
        print("no image-grid challenge currently open (checkbox already solved, or no CAPTCHA).")
        return 1
    _record_captcha_type(domain, "grid")
    cap = _capture_challenge()
    geo = _bframe_geometry()
    instruction = cap["instruction"] if cap else ""
    crop = cap["crop"] if cap else ""
    dynamic = _looks_dynamic(instruction)
    state = {
        "domain": domain, "job_ref": job_ref, "round": round_num, "captures": captures,
        "instruction": instruction, "crop": crop, "geometry": geo, "dynamic": dynamic,
    }
    with open(SOLVE_PENDING, "w") as _sf:
        json.dump(state, _sf)
    count = geo["count"] if geo else 0
    print(f"GRID CHALLENGE CAPTURED (round {round_num}, capture {captures}): {count} tiles"
          f"{' [DYNAMIC]' if dynamic else ''}.")
    print(f"INSTRUCTION: {instruction}")
    print(f"CROP: {crop}")
    if count == 0:
        print("WARNING: 0 tiles read from the grid geometry despite an open challenge — "
              "geometry capture likely failed. Re-run `solve-grid` before trusting this "
              "round, or hand to the user if it repeats.")
    else:
        print("VL step: read the crop, decide which tile indices (0-based, row-major, "
              f"0..{count - 1}) match the instruction, then run:")
        print(f"  python3 {os.path.basename(__file__)} solve-grid --tiles '<indices>'")
        if dynamic:
            print("DYNAMIC challenge: after each pick the tiles reload and you'll be asked "
                  "again — when no tiles match anymore, finalize with --tiles '' to Verify.")
    return 4  # NEED_TILES


def main():
    a = sys.argv[1:]
    if not a:
        print(__doc__)
        return 1
    try:
        if a[0] == "detect":
            return detect()
        if a[0] == "click":
            return click(job_ref=a[1] if len(a) > 1 else "")
        if a[0] == "wait-token":
            # Guard the parse: a non-numeric timeout (typo) would otherwise raise a
            # ValueError that escapes the `except cfx.CfxError` below as a traceback.
            try:
                timeout = float(a[1]) if len(a) > 1 else 15.0
            except ValueError:
                print(f"Usage: recaptcha.py wait-token [timeout_seconds] (got {a[1]!r})")
                return 1
            return wait_token(timeout)
        if a[0] == "recheck":
            return recheck(job_ref=a[1] if len(a) > 1 else "")
        if a[0] == "challenge-snapshot":
            return challenge_snapshot()
        if a[0] == "solve-grid":
            # Parse from the positional args MINUS "--tiles <value>", not by
            # fixed index — a fixed a[2] check previously mis-parsed
            # `solve-grid --tiles "0 4 7"` (the form in this module's own
            # Usage) by reading the tiles VALUE itself as job_ref, and never
            # picked up job_ref at all from `solve-grid <job_ref>` (Phase A).
            rest = a[1:]
            tiles: "str | None" = None
            if "--tiles" in rest:
                i = rest.index("--tiles")
                tiles = rest[i + 1] if i + 1 < len(rest) else ""
                del rest[i:i + 2]
            job_ref = rest[0] if rest else ""
            return solve_grid(job_ref=job_ref, tiles_arg=tiles)
        if a[0] == "check-type":
            if len(a) < 2:
                print("Usage: recaptcha.py check-type <domain>")
                return 1
            print(check_type(a[1]) or "(never seen)")
            return 0
    except cfx.CfxError as e:
        print(f"ERROR: {e}")
        return 2
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
