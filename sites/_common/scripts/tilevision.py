#!/usr/bin/env python3
"""
tilevision.py — the reCAPTCHA v2 image-grid auto-solver: VISION + CLICKING.

Closes the one explicitly unbuilt step in `recaptcha.py solve-grid`: Phase A
captures the challenge and emitted NEED_TILES (exit 4) for "the agent's VL
read". THIS module is now the whole solver — it reads the grid with a VLM AND
does the trusted clicking (its own `solve` command), while `recaptcha.py
solve-grid --auto` is a one-line delegation into it. The low-level primitives
(ground-truth frame reads, trusted click-xy, Verify, audit trail) stay IN
recaptcha.py — imported here, never duplicated.

Architecture (validated against a real reCAPTCHA grid, 2026-08-26): whole-grid
indexing ("reply with the tile numbers") FAILS on small open VLMs — three
models returned wrong or degenerate index sets. Per-tile BINARY classification
("does this one tile contain X? YES/NO") was exact on the same challenge,
including the canonical trap case (a road SIGN depicting a traffic light,
where reCAPTCHA convention says the sign counts). So: slice the crop into
tiles using the LIVE DOM geometry, classify each tile independently, union the
YES tiles into an index list, hand that to `recaptcha.py solve-grid --tiles`.

Provider chain (first configured entry wins; a dead/unreachable entry falls
through to the next):
  1. NVIDIA NIM (`NVIDIA_API_KEY`, meta/llama-3.2-90b-vision-instruct) —
     validated working from this host.
  2. Nous inference (`~/.hermes/auth.json` providers.nous.access_token) —
     token is refreshed by any running Hermes gateway; flaky from raw scripts,
     so it is a fallback, not the default.
  3. Any OpenAI-compatible endpoint via TILEVISION_BASE_URL + TILEVISION_MODEL
     (+ optional TILEVISION_API_KEY).

The VLM only decides YES/NO per tile; geometry, slicing, Verify and the audit
trail stay deterministic local code. On any hard failure the script exits
non-zero and tells the caller to fall back to the agent's own vision read of
the SAME crop — the old NEED_TILES path still works unchanged.

Usage:
    CFX_KEY=... CFX_TAB=... python3 tilevision.py <command> [args]

  solve [job_ref] [--max-rounds N]   FULL AUTO-SOLVE of the open grid: capture
                                     (delegated to recaptcha.solve_grid Phase A)
                                     -> classify -> trusted-click the picks ->
                                     Verify, looping rounds (bounded). PASSED ->
                                     exit 0; failed/hand-off -> non-zero.
  solve-pending [pending_json]       vision-only: classify the crop recorded by
                                     Phase A using its persisted tile rects;
                                     prints PICKED "<indices>" and returns 0
                                     (indices found), 5 (none match — legitimate
                                     for dynamic grids / empty grids), non-zero
                                     on failure.
  classify-crop <crop.png> <cols> <rows> [--task "..."]
                                     standalone: slice ANY image into a cols x rows
                                     grid and classify it. Same exit contract.

Env:
  TILEVISION_MODEL      override the model id
  TILEVISION_TIMEOUT    per-request timeout, seconds (default 60)
"""
import base64
import io
import json
import os
import re
import sys
import time

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _here)

DEFAULT_NVIDIA_MODEL = "meta/llama-3.2-90b-vision-instruct"
NOUS_AUTH = os.path.expanduser("~/.hermes/auth.json")
REQUEST_TIMEOUT = float(os.environ.get("TILEVISION_TIMEOUT", "60"))

EXIT_OK = 0            # at least one tile picked
EXIT_NONE_MATCHED = 5  # classified fine; zero tiles matched (a valid answer)
EXIT_NO_CROP = 2       # pending state/crop missing or unreadable
EXIT_NO_PROVIDER = 3   # no usable vision provider/key
EXIT_HTTP_ERROR = 4    # provider(s) reachable but every request failed


# --- task extraction ---------------------------------------------------------

_DEFAULT_TASK = "the object named in the challenge instruction"


def extract_task(instruction):
    """Pull the target-object phrase out of a reCAPTCHA instruction line.

    Real instructions are imperative ("Select all squares with traffic lights",
    "Click each image containing a bus", ...). The object is whatever follows
    the last 'with' / 'containing' / 'containing a' style marker; if none
    matches, fall back to the full instruction minus the leading verb phrase so
    the classifier prompt stays truthful to what the grid actually asked.
    """
    text = re.sub(r"\s+", " ", (instruction or "").strip())
    if not text:
        return _DEFAULT_TASK
    m = re.search(
        r"\b(?:with|containing|showing|of|featuring)\s+(?:all\s+|each\s+|any\s+)*(?:an?\s+|the\s+)?(.+?)\s*$",
        text, re.I)
    if m and m.group(1).strip():
        return m.group(1).strip().rstrip(".")
    # No known marker (e.g. "traffic lights" alone, or an unusual phrasing):
    # strip a leading imperative verb if there is one, else use the whole line.
    stripped = re.sub(r"^(?:please\s+)?select\s+", "", text, flags=re.I)
    return stripped.rstrip(".") or _DEFAULT_TASK


def tile_prompt(task):
    """The per-tile binary prompt. Deliberately rigid: YES/NO only."""
    return (
        f'This is ONE tile cropped from a photo-grid challenge whose task is to select '
        f'tiles containing: "{task}". '
        "Does THIS single tile contain any part of such an object? "
        "A sign or drawing that depicts the object also counts; partial views count. "
        "Answer ONLY the word YES or the word NO."
    )


def parse_bool_answer(text):
    """YES/NO verdict parser. Returns True/False, or None when unparseable
    (garbage, refusal, empty). None must be treated as 'no answer', never as NO."""
    t = (text or "").strip().upper()
    if not t:
        return None
    # Hedge/refusal guards FIRST: phrases where YES/NO words appear but mean
    # neither ("NO IDEA", "NOT SURE", "I DON'T KNOW", "CANNOT").
    if re.search(r"\b(IDEA|SURE|KNOW|MAYBE|CANNOT|CAN'T|CAN NOT|UNABLE)\b", t):
        return None
    yes = bool(re.search(r"\bYES\b", t))
    no = bool(re.search(r"\bNO\b", t))
    if yes and not no:
        return True
    if no and not yes:
        return False
    return None  # both, or neither: ambiguous -> unanswered


# --- tile slicing ------------------------------------------------------------

def slice_tiles(crop_path, cols=3, rows=3, tile_rects=None):
    """Slice the challenge crop into tile images.

    Preferred input is `tile_rects`: the CROP-RELATIVE pixel rects captured from
    the live DOM (see recaptcha.py `_tile_crops_relative`), which handle the
    bframe's own header/button chrome around the grid. When omitted, falls back
    to an even cols x rows split of the image — right for bare grid screenshots
    (classify-crop), approximate for real captures.
    Returns a list of PNG bytes, row-major (same order as the DOM rect list).
    """
    from PIL import Image
    img = Image.open(crop_path).convert("RGB")
    W, H = img.size
    out = []
    if tile_rects:
        for r in tile_rects:
            left = max(0, min(W - 1, int(round(r["x"]))))
            top = max(0, min(H - 1, int(round(r["y"]))))
            right = max(left + 1, min(W, int(round(r["x"] + r["w"]))))
            bottom = max(top + 1, min(H, int(round(r["y"] + r["h"]))))
            out.append(_png_bytes(img.crop((left, top, right, bottom))))
        return out
    for row in range(rows):
        for col in range(cols):
            box = (round(col * W / cols), round(row * H / rows),
                   round((col + 1) * W / cols), round((row + 1) * H / rows))
            out.append(_png_bytes(img.crop(box)))
    return out


def _png_bytes(img):
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


# --- providers ---------------------------------------------------------------

class Provider(object):
    def __init__(self, name, base_url, api_key, model):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    def describe(self):
        return f"{self.name}:{self.model}"


def _env_key(name):
    v = os.environ.get(name)
    if v:
        return v.strip()
    # ~/.hermes/.env fallback (KEY=value lines) — never logged.
    try:
        with open(os.path.expanduser("~/.hermes/.env")) as f:
            for ln in f:
                if ln.startswith(name + "="):
                    return ln.split("=", 1)[1].strip()
    except OSError:
        pass
    return None


def _nous_token():
    """The Hermes gateway refreshes this token whenever Hermes runs; it may be
    expired when read from a raw script — callers treat failures as fallthrough."""
    try:
        with open(NOUS_AUTH) as f:
            prov = json.load(f)["providers"]["nous"]
        tok = prov.get("access_token") or ""
        return tok if len(tok) > 50 else None
    except (OSError, ValueError, KeyError):
        return None


def provider_chain():
    """Ordered candidate providers. Entries without usable credentials are
    skipped here; unreachable/erroring entries are skipped at request time."""
    chain = []
    nk = _env_key("NVIDIA_API_KEY")
    if nk:
        chain.append(Provider("nvidia", "https://integrate.api.nvidia.com/v1",
                              nk, DEFAULT_NVIDIA_MODEL))
    nt = _nous_token()
    if nt:
        chain.append(Provider("nous", "https://inference-api.nousresearch.com/v1",
                              nt, "deepseek/deepseek-v4-flash-vision-exp"))
    bk = _env_key("TILEVISION_API_KEY") or _env_key("OPENROUTER_API_KEY")
    bb = os.environ.get("TILEVISION_BASE_URL", "").strip()
    if bb and bk:
        bm = os.environ.get("TILEVISION_MODEL", "").strip() or "google/gemini-3-flash"
        chain.append(Provider("custom", bb, bk, bm))
    return chain


def _chat_once(provider, prompt, png_bytes):
    import urllib.request
    body = {
        "model": provider.model,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url",
             "image_url": {"url": "data:image/png;base64,"
                                + base64.b64encode(png_bytes).decode()}}]}],
        "max_tokens": 8,
        "temperature": 0,
    }
    req = urllib.request.Request(
        provider.base_url + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + provider.api_key,
                 "Content-Type": "application/json"})
    import urllib.error
    try:
        resp = urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT)
        payload = json.loads(resp.read())
    except Exception as e:
        raise RuntimeError(f"{provider.describe()} HTTP {e}")
    content = ((payload.get("choices") or [{}])[0].get("message") or {}).get("content", "")
    verdict = parse_bool_answer(content)
    if verdict is None:
        raise RuntimeError(f"{provider.describe()} unparseable answer {content!r}")
    return verdict


def classify_tiles(png_tiles, task, log=None):
    """Classify every tile; returns (picks, ok, detail).

    picks : sorted list of tile indices answered YES
    ok    : False only when NO provider could answer ANY tile
    detail: human-readable summary of provider health for the audit log
    Per-tile errors fall through provider -> next; a tile answered by nobody
    counts as 'no answer' (never silently as NO).
    """
    chain = provider_chain()
    if not chain:
        return [], False, "no vision provider credentials found"
    picks = []
    answered = 0
    notes = []
    prompt = tile_prompt(task)
    for idx, png in enumerate(png_tiles):
        verdict = None
        errs = []
        for prov in chain:
            try:
                verdict = _chat_once(prov, prompt, png)
                break
            except RuntimeError as e:
                errs.append(str(e))
        if verdict is None:
            notes.append(f"tile {idx}: UNANSWERED ({'; '.join(errs[-1:] )})" if errs
                         else f"tile {idx}: UNANSWERED")
        else:
            answered += 1
            if verdict:
                picks.append(idx)
                notes.append(f"tile {idx}: YES")
            else:
                notes.append(f"tile {idx}: no")
        if log:
            log(f"  {notes[-1]}")
    detail = "; ".join(notes)
    return sorted(picks), answered > 0, detail


# --- commands ----------------------------------------------------------------

def _load_pending(path):
    p = path or os.path.join(_here, "..", "..", "..", "captcha-solve-pending.json")
    try:
        with open(p) as f:
            return json.load(f), p
    except (OSError, ValueError):
        return None, p


def cmd_solve_pending(pending_path=None):
    state, p = _load_pending(pending_path)
    if not state or not state.get("crop"):
        print(f"TILEVISION: no pending solve-state / crop path (looked at {p}). "
              "Run `recaptcha.py solve-grid` first.")
        return EXIT_NO_CROP
    crop = state["crop"]
    if not os.path.exists(crop):
        print(f"TILEVISION: crop file missing on disk: {crop}")
        return EXIT_NO_CROP
    task = extract_task(state.get("instruction", ""))
    rects = state.get("tile_rects")
    n = len(rects) if rects else int(state.get("geometry", {}).get("count") or 9)
    print(f"TILEVISION: task={task!r} tiles={n} crop={crop}")
    tiles = slice_tiles(crop, tile_rects=rects)
    if len(tiles) != n and rects:
        print(f"TILEVISION WARNING: sliced {len(tiles)} tiles but pending state "
              f"says {n} — geometry drift; refusing to guess.")
        return EXIT_NO_CROP
    picks, ok, detail = classify_tiles(tiles, task, log=print)
    # Persist the verdict into the SAME pending file recaptcha.py Phase B reads,
    # so the pick survives as part of the solve's audit trail.
    try:
        with open(p) as f:
            fresh = json.load(f)
        fresh["picked"] = " ".join(str(i) for i in picks)
        fresh["tilevision_detail"] = detail[:2000]
        tmp = p + ".tmp"
        with open(tmp, "w") as f:
            json.dump(fresh, f)
        os.replace(tmp, p)
    except (OSError, ValueError):
        pass  # non-fatal: the PICKED line below still carries the answer
    if not ok:
        print("TILEVISION FAILED: every provider failed on every tile. Fall back to "
              "reading the crop yourself (NEED_TILES flow) — do NOT retry blindly.")
        print(f"DETAIL: {detail}")
        return EXIT_HTTP_ERROR
    if not picks:
        print('TILEVISION: no tiles matched. For a DYNAMIC challenge finalize with '
              '`solve-grid --tiles \'\'`; for a static grid this means VERIFY now.')
        print('PICKED ""')
        return EXIT_NONE_MATCHED
    joined = " ".join(str(i) for i in picks)
    print(f'PICKED "{joined}"')
    print(f"Next: python3 sites/_common/scripts/recaptcha.py solve-grid --tiles '{joined}'")
    return EXIT_OK


def cmd_classify_crop(crop, cols, rows, task_arg=None):
    if not os.path.exists(crop):
        print(f"TILEVISION: no such file: {crop}")
        return EXIT_NO_CROP
    task = task_arg or _DEFAULT_TASK
    print(f"TILEVISION: task={task!r} grid={cols}x{rows} crop={crop}")
    tiles = slice_tiles(crop, cols=cols, rows=rows)
    picks, ok, detail = classify_tiles(tiles, task, log=print)
    if not ok:
        print("TILEVISION FAILED: no provider could answer.")
        print(f"DETAIL: {detail}")
        return EXIT_HTTP_ERROR
    if not picks:
        print('PICKED ""')
        return EXIT_NONE_MATCHED
    print('PICKED "' + " ".join(str(i) for i in picks) + '"')
    return EXIT_OK


# --- full solve: vision + trusted clicking -----------------------------------

def cmd_solve(job_ref="", max_rounds=3):
    """End-to-end grid solve, looping capture->classify->click->Verify.

    The low-level half (challenge ground truth, capture, live geometry,
    trusted click-xy, Verify click, audit log) is recaptcha.py's — imported
    and reused here so there is exactly ONE copy of the clicking machinery.
    tilevision owns only the DECIDE step. Bounded by max_rounds plus
    recaptcha's own capture runaway guard; every failure hands off loudly.
    """
    import recaptcha as rc

    domain = rc._domain()
    for rnd in range(1, max_rounds + 1):
        if not rc._challenge_open():
            if rc._anchor_checked() is True or rc._token_len() > 0:
                shot = rc._save_shot(domain)
                print(f"SOLVED: grid passed after {rnd - 1} pick round(s).")
                rc._audit_log(domain, job_ref, shot, "TILEVISION_SOLVED")
                return 0
            print("no image-grid challenge currently open (and nothing passed) "
                  "— run `recaptcha.py click` first if the checkbox is unsolved.")
            return 2

        # --- Phase A equivalent: capture + geometry + persist pending state ---
        cap = rc._capture_challenge()
        geo = rc._bframe_geometry()
        instruction = cap["instruction"] if cap else ""
        crop = cap["crop"] if cap else ""
        dynamic = rc._looks_dynamic(instruction)
        rects = rc._tile_crops_relative()
        pending_path = rc.SOLVE_PENDING
        state = {
            "domain": domain, "job_ref": job_ref, "round": rnd, "captures": rnd,
            "instruction": instruction, "crop": crop,
            "geometry": geo, "dynamic": dynamic, "tile_rects": rects,
        }
        with open(pending_path, "w") as f:
            json.dump(state, f)
        count = len(rects) or (geo or {}).get("count", 0)
        print(f"ROUND {rnd}: captured {count} tiles"
              f"{' [DYNAMIC]' if dynamic else ''} — INSTRUCTION: {instruction}")

        # --- DECIDE (the VLM step) ---
        picks, ok, detail = classify_tiles(slice_tiles(crop, tile_rects=rects),
                                           extract_task(instruction), log=print)
        try:
            with open(pending_path) as f:
                fresh = json.load(f)
            fresh["picked"] = " ".join(str(i) for i in picks)
            fresh["tilevision_detail"] = detail[:2000]
            tmp = pending_path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(fresh, f)
            os.replace(tmp, pending_path)
        except (OSError, ValueError):
            pass
        if not ok:
            print("TILEVISION FAILED: no provider answered any tile — handing off. "
                  "Read the crop yourself and run `recaptcha.py solve-grid --tiles`.")
            rc._audit_log(domain, job_ref, "", "TILEVISION_NO_PROVIDER")
            return EXIT_HTTP_ERROR
        if not picks:
            # Nothing matches: legitimate finalize for dynamic grids; for a
            # static grid it means Verify an empty selection once.
            print("nothing matched — Verifying an empty selection.")
            tiles_arg = ""
        else:
            tiles_arg = " ".join(str(i) for i in picks)

        # --- ACT: re-read LIVE geometry and trusted-click it (never Phase-A coords) ---
        geo_live = rc._bframe_geometry()
        if not geo_live or not geo_live.get("tiles"):
            print("couldn't read live grid geometry for the click — hand to the user.")
            rc._audit_log(domain, job_ref, "", "TILEVISION_NO_GEOMETRY")
            rc._clear_pending()
            return 3
        try:
            idxs = [int(t) for t in tiles_arg.split() if t.strip() != ""]
        except ValueError:
            idxs = []
        n = len(geo_live["tiles"])
        bad = [i for i in idxs if not (0 <= i < n)]
        if bad:
            print(f"dropping out-of-range indices {bad} (live grid has {n} tiles).")
            idxs = [i for i in idxs if 0 <= i < n]
        for i in idxs:
            rc._click_xy(geo_live["tiles"][i]["x"], geo_live["tiles"][i]["y"])
            time.sleep(0.4)
        if idxs and not dynamic:
            time.sleep(0.4)
            if rc._selected_count() == 0:
                print("clicked tiles but none registered as selected — clicks aren't "
                      "landing (likely fingerprint distrust). Hand to the user.")
                rc._audit_log(domain, job_ref, "", "TILEVISION_CLICKS_NOT_LANDING")
                rc._clear_pending()
                return 3

        # --- Verify / loop ---
        rc._click_verify(geo_live)
        time.sleep(2.5)
        if rc._anchor_checked() is True or rc._token_len() > 0:
            shot = rc._save_shot(domain)
            print(f"GRID SOLVED: passed on round {rnd}.")
            rc._audit_log(domain, job_ref, shot, "TILEVISION_SOLVED")
            rc._record_captcha_type(domain, "grid")
            rc._clear_pending()
            return 0
        if not rc._challenge_open():
            print("GRID: neither passed nor a new round after Verify — likely still "
                  "loading or a misclick. Hand to the user.")
            rc._audit_log(domain, job_ref, "", "TILEVISION_AMBIGUOUS")
            rc._clear_pending()
            return 3
        print(f"new challenge round {rnd + 1}...")
    print(f"TILEVISION GRID FAILED after {max_rounds} rounds — hand to the user.")
    rc._audit_log(domain, "", "", "TILEVISION_FAILED_ROUNDS")
    rc._clear_pending()
    return 3


def main():
    a = sys.argv[1:]
    if not a or a[0] in ("-h", "--help"):
        print(__doc__)
        return 1
    cmd = a[0]
    if cmd == "solve":
        rest = a[1:]
        rounds = 3
        if "--max-rounds" in rest:
            i = rest.index("--max-rounds")
            try:
                rounds = int(rest[i + 1]) if i + 1 < len(rest) else 3
            except ValueError:
                print("Usage: tilevision.py solve [job_ref] [--max-rounds N]")
                return 1
            del rest[i:i + 2]
        job_ref = rest[0] if rest else ""
        return cmd_solve(job_ref=job_ref, max_rounds=rounds)
    if cmd == "solve-pending":
        return cmd_solve_pending(a[1] if len(a) > 1 else None)
    if cmd == "classify-crop":
        if len(a) < 4:
            print("Usage: tilevision.py classify-crop <image> <cols> <rows> [--task \"...\"]")
            return 1
        task = None
        rest = a[4:]
        if "--task" in rest:
            i = rest.index("--task")
            task = rest[i + 1] if i + 1 < len(rest) else None
        try:
            cols, rows = int(a[2]), int(a[3])
        except ValueError:
            print("Usage: tilevision.py classify-crop <image> <cols> <rows>")
            return 1
        return cmd_classify_crop(a[1], cols, rows, task)
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
