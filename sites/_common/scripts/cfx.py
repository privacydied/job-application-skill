#!/usr/bin/env python3
"""cfx.py — shared camofox REST helper for the Python site scripts.

The bash sibling `cfx.sh` (same directory) is the primary shared helper used
when Claude Code drives the browser by hand. This is its **Python analog**, for
the site-specific scripts (`opts.py`, `pick.py`, `nav_to_link.py`,
`set_textarea.py`) that need richer DOM logic than bash comfortably expresses.
Before it existed, each of those scripts re-implemented `post()` from scratch and
called `/navigate` and `/click` DIRECTLY — bypassing the anti-detection layer
`cfx.sh` provides, so e.g. `nav_to_link.py` navigated to an apply URL with an
empty Referer + `Sec-Fetch-Site: none` (a textbook bot tell). Routing them
through this module gives every script the same hardening for free:

  * **Randomized human_pause pacing** before page-affecting actions (mirror of
    cfx.sh's `human_pause`).
  * **Automatic Referer chains** on navigate (mirror of cfx.sh's
    `compute_referer` / browser_camofox.py's `_compute_referer`) so a direct nav
    to a deep posting URL looks like a real click-through, not an address-bar
    teleport.

Keep the pacing + referer logic in sync with `cfx.sh` and
`~/.hermes/hermes-agent/tools/browser_camofox.py` — all three must match.

Env: `CFX_KEY` (required), `CFX_TAB` (required for tab actions), `CFX_USER`
(default `nasirjones`). Testing-only escape hatches (never for real
applications): `CFX_NO_PACING`, `CFX_NO_REFERER`.
"""
import json
import os
import random
import socket
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

U = os.environ.get("CFX_URL", "http://localhost:9377")

# skill root = …/_common/scripts -> _common -> sites -> root (for the tab-pointer files).
_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))

# ── tab-budget guard (prevents the ~8-tab backend wedge) ─────────────────────
# The camofox backend WEDGES above ~8 live tabs: POST /tabs starts 500ing and every
# in-flight nav 410s, costing a ~90s restart + re-login (references/camofox-session-
# stability.md, camofox-concurrent-tab-wedge.md). warm.py caps ITS OWN fan-out, but
# nothing stopped STRAY tabs (a crashed warm pass, a background feed that opened its
# own, a human-driven tab) from accumulating until the next open wedged unattended.
# `ensure_tab` now self-throttles below this budget by reaping the oldest stale tabs
# BEFORE opening — preventing the wedge is far cheaper than the restart that recovers it.
TAB_BUDGET = int(os.environ.get("CFX_TAB_BUDGET") or 7)


class CfxError(RuntimeError):
    """A camofox REST call failed (HTTP error, or an /evaluate JS throw)."""


def _parse_json(raw: bytes, path: str) -> dict:
    """Parse a REST response body into a dict. An EMPTY body (some endpoints
    return 200 with no content) becomes `{}` rather than blowing up; a
    non-empty body that isn't valid JSON (e.g. an HTML error page served with a
    200) becomes a CfxError instead of a bare json.JSONDecodeError escaping the
    wrapper — the whole point of post()/get()/delete() is that every failure
    surfaces as CfxError, and an uncaught ValueError here defeated that."""
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except ValueError:
        snippet = raw[:200].decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)[:200]
        raise CfxError(f"{path} -> non-JSON response: {snippet!r}") from None


def _key() -> str:
    key = os.environ.get("CFX_KEY")
    if not key:
        raise CfxError("Set CFX_KEY to the CAMOFOX_ACCESS_KEY bearer token")
    return key


def _tab(explicit: str = None) -> str:
    """Resolve the target tab id. An explicit id (passed by callers that drive a
    tab OTHER than the ambient CFX_TAB — e.g. warm.py pre-loading apply pages in
    background tabs) always wins; otherwise fall back to the CFX_TAB env."""
    tab = explicit or os.environ.get("CFX_TAB")
    if not tab:
        raise CfxError("Set CFX_TAB to the target tab ID (from POST /tabs)")
    return tab


def set_tab(tid: str) -> str:
    """Set the ambient CFX_TAB so CHILD subprocess calls (feed.py / easyapply.py /
    jd.py) inherit the live tab after a self-heal. This is the ONE sanctioned place a
    non-cfx module's need to write CFX_TAB is centralized — drivers call cfx.set_tab()
    instead of touching os.environ directly, so the codebase invariant 'all CFX_TAB
    access goes through cfx' holds (a raw os.environ['CFX_TAB'] read/write elsewhere is
    the bug the test guards against). Returns the id for chaining."""
    if tid:
        os.environ["CFX_TAB"] = tid
    return tid


def _uid() -> str:
    return os.environ.get("CFX_USER", "nasirjones")


def human_pause(tier: str = "full") -> None:
    """Randomized pre-action delay so page-affecting actions don't land at a
    mechanical, evenly-spaced cadence (a textbook bot signature Cloudflare
    scores on the whole session). Mirror of cfx.sh's human_pause — keep in sync.
    `CFX_NO_PACING=1` disables it (test loops only).

    PACING TIERS (2026-07-15). Default 'full' is the original behavior and stays the
    posture for anything that MUTATES a form (click/type/submit) — the high-value,
    high-scrutiny actions. A 'light' tier (shorter jitter, no long reading-pause) is
    available for pure READ navigations (screening a JD you won't act on) where the
    anti-detect budget is better spent elsewhere. Conservative by design: 'light' is
    OPT-IN — callers must ask for it, and the env `CFX_PACE_TIER` can force a tier
    globally for A/B measurement without code changes. Unknown tier => 'full' (safe)."""
    if os.environ.get("CFX_NO_PACING"):
        return
    tier = (os.environ.get("CFX_PACE_TIER") or tier or "full").lower()
    if tier == "none":
        return
    if tier == "light":
        time.sleep(random.uniform(0.4, 1.2))
        return
    # 'full' (default, unchanged)
    delay = random.uniform(0.7, 2.9)
    if random.random() < (1.0 / 6.0):  # ~1 in 6: longer "reading" pause
        delay += random.uniform(2.0, 6.0)
    time.sleep(delay)


def post(path: str, body: dict, timeout: int = 30) -> dict:
    """POST JSON to the camofox REST API and return the parsed response.
    Raises CfxError with the server's message on any HTTP/transport error
    instead of leaking a raw urllib traceback."""
    req = urllib.request.Request(
        f"{U}{path}",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {_key()}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return _parse_json(r.read(), path)
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = json.loads(e.read()).get("error", "")
        except Exception:
            pass
        raise CfxError(f"{path} -> HTTP {e.code} {detail}".strip()) from None
    except socket.timeout:
        # Read-phase timeout is a raw socket.timeout (OSError), NOT a URLError, so
        # it would otherwise escape uncaught and crash the caller. Common when a
        # camofox /click hangs on a post-click re-render — callers catch CfxError
        # and fall back (e.g. to a JS click).
        raise CfxError(f"{path} -> timed out after {timeout}s") from None
    except urllib.error.URLError as e:
        reason = getattr(e, "reason", e)
        raise CfxError(f"{path} -> cannot reach camofox at {U}: {reason}") from None
    except OSError as e:
        # Verified live (2026-07-13): a connection reset WHILE READING the response
        # (e.g. the server process restarts mid-request, such as during
        # restart_engine()'s own health poll) raises a bare ConnectionResetError, not
        # a urllib.error.URLError -- URLError only reliably wraps failures at the
        # connect/open stage, not read-phase drops on an already-open connection. An
        # uncaught OSError here crashed restart_engine()'s poll loop outright instead
        # of being treated as "not ready yet, keep polling." Catch generically so any
        # OSError subclass (reset/refused/broken-pipe) becomes a normal CfxError.
        raise CfxError(f"{path} -> connection error: {e}") from None


def evaluate(expression: str, timeout: int = 30, tab: str = None):
    """Run JS in the page and return the UNWRAPPED result value (not the
    `{ok,result}` envelope). Raises CfxError if the JS threw. Passive read —
    JS-in-page generates no input telemetry, so no human_pause here. `tab`
    overrides the ambient CFX_TAB for callers driving a specific tab."""
    resp = post(f"/tabs/{_tab(tab)}/evaluate", {"userId": _uid(), "expression": expression}, timeout)
    if isinstance(resp, dict) and resp.get("error"):
        raise CfxError(f"evaluate failed: {resp['error']}")
    return resp.get("result") if isinstance(resp, dict) else resp


def eval_frame(frame_selector: str, expression: str, timeout: int = 30):
    """Same as `evaluate()`, but scoped to the Frame behind a cross-origin iframe —
    `frame_selector` matches the IFRAME ELEMENT in the main document (same selector
    semantics as `click_and_follow`'s frameSelector, e.g.
    `'iframe[src*="recaptcha/api2/anchor"]'`), and `expression` runs inside THAT
    frame's own document. THIS EXISTS (2026-07-13) so callers can read REAL state
    out of a cross-origin widget — e.g. reCAPTCHA v2's `#recaptcha-anchor` actual
    `aria-checked` — instead of inferring pass/fail from the main-page
    `g-recaptcha-response` token or a screenshot, both of which can go stale (a
    leftover `api2/bframe` iframe can make token/DOM-presence checks report a
    phantom "still open" on an already-passed checkbox). See `recaptcha.py` for the
    concrete before/after. Passive read, no human_pause."""
    resp = post(f"/tabs/{_tab()}/eval-frame",
                {"userId": _uid(), "frameSelector": frame_selector, "expression": expression}, timeout)
    if isinstance(resp, dict) and resp.get("error"):
        raise CfxError(f"eval-frame failed: {resp['error']}")
    return resp.get("result") if isinstance(resp, dict) else resp


def current_url(tab: str = None) -> str:
    """The tab's live location.href (passive), or '' on failure. Sources the
    Referer for the next navigate()."""
    try:
        r = evaluate("location.href", timeout=10, tab=tab)
        return r if isinstance(r, str) and r.startswith(("http://", "https://")) else ""
    except CfxError:
        return ""


def compute_referer(target: str, current: str, explicit: str = "") -> str:
    """Decide the Referer for a navigate. Mirror of cfx.sh's compute_referer /
    browser_camofox.py's _compute_referer — keep all three in sync.
      1. explicit    -> verbatim.
      2. current URL -> if a real http(s) page and not the same URL (mimics a
                        link-click on the page you're actually on).
      3. deep cold   -> https://www.google.com/ (target has a path/query but no
                        history: looks like a search-result click).
      4. else        -> '' (bare homepage: legitimately sends no Referer).
    `CFX_NO_REFERER=1` disables and sends a bare navigate."""
    if explicit:
        return explicit
    if current.startswith(("http://", "https://")) and current.rstrip("/") != target.rstrip("/"):
        return current
    try:
        parts = urlsplit(target)
        deep = parts.path not in ("", "/") or bool(parts.query)
    except Exception:
        deep = False
    return "https://www.google.com/" if deep else ""


def navigate(url: str, referer: str = "", timeout: int = 60, tab: str = None,
             pace_tier: str = "full") -> dict:
    """Navigate the tab, attaching a realistic Referer automatically (see
    compute_referer) unless CFX_NO_REFERER is set. Paces first like a human.
    `tab` overrides CFX_TAB (warm.py navigates background tabs this way — a
    fresh about:blank tab has no http current URL, so compute_referer yields the
    google deep-link Referer, exactly as a real cold click-through would).
    `pace_tier` ('full'|'light'|'none') lets a pure read-navigation (JD screening)
    opt into lighter pacing; default 'full' keeps the current anti-detect posture."""
    ref = "" if os.environ.get("CFX_NO_REFERER") else compute_referer(url, current_url(tab), referer)
    human_pause(pace_tier)
    body = {"userId": _uid(), "url": url}
    if ref:
        body["referer"] = ref
    try:
        return post(f"/tabs/{_tab(tab)}/navigate", body, timeout)
    except CfxError as e:
        # Self-heal the recurring dead-tab flake: camofox restarted and dropped the
        # tab, so this 404s. Reopen a fresh CFX_TAB and retry ONCE. Only for the
        # ambient tab — an explicit `tab` belongs to the caller (e.g. a warm tab),
        # so re-raise rather than silently redirect its navigation elsewhere.
        if tab is None and _looks_like_dead_tab(e):
            new = ensure_tab()
            return post(f"/tabs/{new}/navigate", body, timeout)
        raise


def goto(url: str, tab: str = None, verify: bool = True, tries: int = 2,
         settle: float = 1.5) -> dict:
    """Navigate and VERIFY the page actually rendered — the scar-killing wrapper (X.1).

    SKILL.md burned ~10 passes on the open-tab-auto-nav-silent-failure trap: a tab that
    stays at about:blank (title='', innerText.length=0) so every job page reads EMPTY →
    a FALSE 'NO APPLY BUTTON' → FALSE 'external-route' → FALSE 'backend dead'. The fix was
    always the same recipe — explicit navigate() (never open_tab's auto-nav), then confirm
    innerText>0, and re-nav once if it didn't take. This makes that recipe the DEFAULT so
    the failure is unreachable instead of a paragraph a future agent must remember.

    Returns {url, ok, innerText_len, title_len, attempts}. `ok` is True when the page has
    real content (or verify=False). On a blank render it re-navigates up to `tries` times.
    Never raises for a blank page — a blank result with ok=False is the signal to act on."""
    last = {"url": url, "ok": False, "innerText_len": 0, "title_len": 0, "attempts": 0}
    for attempt in range(1, max(1, tries) + 1):
        last["attempts"] = attempt
        try:
            navigate(url, tab=tab)
        except CfxError as e:
            last["error"] = str(e)
            time.sleep(settle)
            continue
        if not verify:
            last["ok"] = True
            return last
        time.sleep(settle)
        try:
            raw = evaluate(
                "JSON.stringify({t:(document.title||'').length,"
                "l:(document.body?document.body.innerText.length:0)})", tab=tab, timeout=10)
            import json as _json
            d = _json.loads(raw) if isinstance(raw, str) else (raw or {})
            last["title_len"] = int(d.get("t") or 0)
            last["innerText_len"] = int(d.get("l") or 0)
        except CfxError as e:
            last["error"] = str(e)
            continue
        if last["innerText_len"] > 0:
            last["ok"] = True
            return last
        # blank render — the documented trap. Re-nav once more (loop).
    return last


def open_tab(url: str = "about:blank", session_key: str = None, timeout: int = 60,
             before: set = None, guard: bool = False) -> str:
    """Open a NEW managed tab for CFX_USER and return its tabId. Mirrors the
    hermes browser tool's `_ensure_tab` contract: POST /tabs with
    {userId, listItemId:<session_key>, url}. `session_key` defaults to
    CFX_SESSION_KEY, else "job-apply" (the session key this skill's tabs run
    under — verify with list_tabs()[*].listItemId). Used by warm.py to pre-open
    apply pages in the background during the compute phase; prefer opening at
    about:blank and then navigate(url, tab=...) so the load carries a referer
    chain instead of a bare deep-link open."""
    sk = session_key or os.environ.get("CFX_SESSION_KEY", "job-apply")
    # Tab-budget self-throttle (guard=True only — ensure_tab's single-tab path). Reap
    # stale tabs BEFORE creating so this open can't be the one that crosses the wedge
    # threshold. warm.py's bounded fan-out calls open_tab with guard=False so its
    # deliberately-concurrent tabs are never reaped out from under it.
    if guard:
        try:
            prune_tabs()
        except Exception:  # noqa: BLE001 — a prune hiccup must never block opening a tab
            pass
    # Snapshot BEFORE the create so we can recover the id by diffing if the POST
    # returns a broken envelope — this backend intermittently answers a create
    # with `{"error":"Internal server error"}` while STILL creating the tab
    # (verified live 2026-07-14 under a concurrent session). Diffing on tabId +
    # matching listItemId turns that flaky 500 into a reliable open.
    # B.4: ensure_tab already listed the tabs to decide aliveness — it passes that
    # (genuinely pre-create) snapshot in as `before` so we don't re-list here. A
    # standalone caller passes None and we snapshot now (still before the create).
    if before is None:
        before = {t.get("tabId") for t in list_tabs() if isinstance(t, dict)}
    try:
        resp = post("/tabs", {"userId": _uid(), "listItemId": sk, "url": url}, timeout)
    except CfxError:
        resp = {}
    tab_id = resp.get("tabId") if isinstance(resp, dict) else None
    if tab_id:
        return tab_id
    for _ in range(6):
        time.sleep(0.5)
        new = [t.get("tabId") for t in list_tabs()
               if isinstance(t, dict) and t.get("tabId") not in before
               and t.get("listItemId") == sk]
        if new:
            return new[0]
    raise CfxError(f"open_tab: tab not created (last response {resp!r})")


def _looks_like_dead_tab(err) -> bool:
    """Does this CfxError look like the tab id went stale (camofox restarted and
    dropped every tab), as opposed to a real page/JS failure?"""
    m = str(err).lower()
    return any(s in m for s in ("tab not found", "unknown tab", "no tab", "404",
                                "target closed", "target page, context or browser has been closed"))


def is_tab_alive(tab: str = None) -> bool:
    """Is `tab` (default CFX_TAB) a live managed tab right now? Liveness is decided
    by MEMBERSHIP in list_tabs() — there is NO `GET /tabs/{id}` endpoint on this
    backend (it Express-404s "Cannot GET" for every id, live or not; the old
    open_tab.sh probed it and so ALWAYS thought the tab was dead and churned a fresh
    one every call). Retries the list a couple of times, and if the list itself is
    unreachable (transient 500/reset) returns True rather than declare a live tab
    dead — that avoids needless tab churn; navigate()'s self-heal is the real
    backstop if the tab is genuinely gone. False only on unset, or a successful list
    that doesn't contain it."""
    try:
        t = _tab(tab)
    except CfxError:
        return False
    for attempt in range(2):
        try:
            tabs = list_tabs()
        except CfxError:
            time.sleep(0.3)
            continue
        return any(isinstance(x, dict) and x.get("tabId") == t for x in tabs)
    return True  # couldn't reach the list at all — don't churn; navigate() self-heals if truly dead


def _write_tab_env(path: str, tab_id: str) -> bool:
    """Atomically rewrite one env file with the standard CFX_* exports so a shell that
    re-sources it picks up `tab_id`. Returns True on success. The ONE writer shared by
    _persist_tab and sync_tab, so every pointer file gets an identical, complete block
    (never a half-written one that drops CFX_KEY — the .jobenv.persist clobber scar)."""
    try:
        body = ('export CFX_KEY="%s"\nexport CFX_USER="%s"\nexport CFX_URL="%s"\n'
                'export CFX_TAB="%s"\n' % (os.environ.get("CFX_KEY", ""), _uid(), U, tab_id))
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            f.write(body)
        os.replace(tmp, path)
        return True
    except OSError:
        return False


def _persist_tab(tab_id: str) -> None:
    """Write the (re)opened tab id back to the env file named by CFX_TAB_FILE, if
    set — rewriting the standard CFX_* exports so a shell that re-sources it before
    each call picks up the new tab. This is exactly what open_tab.sh's `.runtab`
    writer did; folding it here means ONE implementation every script shares."""
    path = os.environ.get("CFX_TAB_FILE")
    if path:
        _write_tab_env(path, tab_id)


# The scattered shell-sourced pointer files that scripts read to learn the live CFX_TAB.
# They DRIFT — each written by a different code path at a different time — and a stale
# pointer is the #1 "Session expired" cause (references/browser-session-reality.md,
# camofox-session-stability.md found all six carrying DIFFERENT tab ids at once). These
# all use the `export CFX_*` shell format; sync_tab() rewrites every one that exists in a
# single call so `cfx.py sync-tab` reconciles the whole set to one live tab. (Bare-id,
# board-specific pointers like `.reed_tab` are deliberately NOT touched — different format.)
_TAB_POINTER_FILES = (".jobenv.run", ".jobenv.persist", ".jobenv.apply", ".runenv")


def sync_tab(tab_id: str = None, extra_files=None) -> list:
    """Reconcile every standard pointer file to ONE live tab in a single call — the fix
    for the divergent-CFX_TAB hazard that silently kills unattended runs. `tab_id`
    defaults to a freshly ENSURED live tab (so this both heals a dead tab AND propagates
    it everywhere). Writes each `_TAB_POINTER_FILES` entry that already exists at the
    skill root, plus CFX_TAB_FILE, any colon-separated CFX_TAB_FILES, and `extra_files`.
    Returns the list of files written. Only ever writes the REAL live tab — never a guess."""
    if tab_id is None:
        tab_id = ensure_tab(persist=False)
    os.environ["CFX_TAB"] = tab_id
    targets = []
    for name in _TAB_POINTER_FILES:
        p = os.path.join(_ROOT, name)
        if os.path.exists(p):
            targets.append(p)
    if os.environ.get("CFX_TAB_FILE"):
        targets.append(os.environ["CFX_TAB_FILE"])
    for p in (os.environ.get("CFX_TAB_FILES", "").split(":") if os.environ.get("CFX_TAB_FILES") else []):
        if p.strip():
            targets.append(p.strip())
    if extra_files:
        targets.extend(extra_files)
    written = []
    for p in dict.fromkeys(targets):  # de-dup, preserve order
        if _write_tab_env(p, tab_id):
            written.append(p)
    return written


def prune_tabs(budget: int = None, keep: str = None) -> list:
    """Close the OLDEST stale managed tabs so a subsequent open won't cross `budget` and
    wedge the backend. Never closes `keep` (defaults to the current CFX_TAB — the tab the
    run is using) and never touches a tab it can't identify. Returns the closed ids.
    Best-effort: any list/close hiccup is swallowed (a prune must never break the caller).
    The backend lists tabs in creation order, so reaping from the front drops the stalest
    (an abandoned warm/scratch tab) and keeps the freshest. Called by ensure_tab before it
    opens a fresh tab; warm.py's deliberate bounded fan-out passes its own tabs and is not
    affected (it calls open_tab directly, which only prunes when guard=True)."""
    budget = TAB_BUDGET if budget is None else budget
    if budget <= 0:
        return []
    keep = keep if keep is not None else os.environ.get("CFX_TAB")
    try:
        tabs = [t.get("tabId") for t in list_tabs()
                if isinstance(t, dict) and t.get("tabId")]
    except CfxError:
        return []
    # Reap enough that opening ONE more still lands at/under budget.
    excess = len(tabs) - (budget - 1)
    if excess <= 0:
        return []
    closed = []
    for tid in tabs:                       # oldest first
        if excess <= 0:
            break
        if tid == keep:
            continue                        # never reap the active tab
        try:
            close_tab(tid)
            closed.append(tid)
            excess -= 1
        except CfxError:
            continue
    if closed:
        print(f"cfx: tab-budget guard reaped {len(closed)} stale tab(s) "
              f"(had {len(tabs)}, budget {budget})", file=sys.stderr)
    return closed


def _browser_running() -> bool:
    """Is the actual camoufox/Firefox BROWSER process alive (not just the REST
    server)? On a browser crash/OOM the REST server stays up and /health keeps
    returning ok:true, but browserRunning/browserConnected go false and NO tab can
    be created until the engine is restarted.

    Polls up to 3× before concluding DOWN: a `False` here triggers an engine
    restart (which drops in-flight work), and /health briefly reports the browser
    as not-connected right after a (re)launch — verified live 2026-07-14. Returns
    True on the first healthy read; only False if it's down/unreachable across all
    attempts, so a momentary blip never causes a needless restart."""
    for _ in range(3):
        try:
            h = get("/health", timeout=5)
            if isinstance(h, dict) and h.get("browserRunning") and h.get("browserConnected"):
                return True
        except CfxError:
            pass
        time.sleep(0.5)
    return False


def ensure_tab(persist: bool = True) -> str:
    """Guarantee a live CFX_TAB and return it. If the current one is dead or unset
    — the recurring "camofox restarted, every call 404s with Tab not found" flake —
    open a fresh job-apply tab, set os.environ['CFX_TAB'], and (persist=True) write
    it back to CFX_TAB_FILE. Call once at the top of a run, and/or rely on
    navigate()'s automatic self-heal. Supersedes the standalone open_tab.sh.

    Also self-heals a full BROWSER crash: if opening a tab fails AND /health says
    the browser process is down (crashed/OOM — verified live 2026-07-14: a long
    crawl under host memory pressure killed camoufox and every subsequent
    ensure-tab failed because a dead browser can't make tabs), restart the engine
    ONCE and retry. Gated on browserRunning:false so a healthy browser is never
    restarted out from under in-flight work."""
    cur = os.environ.get("CFX_TAB")
    # B.4: list the tabs ONCE — decide aliveness from it AND reuse it as open_tab's
    # pre-create snapshot, instead of is_tab_alive() and open_tab() each doing their own
    # list. (get() now retries transient blips, B.5, so a single list is resilient.)
    try:
        tabs0 = list_tabs()
    except CfxError:
        tabs0 = None
    if cur and tabs0 is not None and any(isinstance(x, dict) and x.get("tabId") == cur for x in tabs0):
        return cur
    if cur and tabs0 is None:
        # Couldn't reach the list — don't churn a fresh tab (is_tab_alive's backstop);
        # navigate()'s self-heal handles a genuinely-dead tab.
        return cur
    before = {t.get("tabId") for t in tabs0 if isinstance(t, dict)} if tabs0 is not None else None
    try:
        new = open_tab("about:blank", before=before, guard=True)
    except CfxError:
        if _browser_running():
            raise  # browser is up — tab-create failed for some other reason; don't mask it
        restart_engine()          # browser is down — the only recovery
        new = open_tab("about:blank", guard=True)  # post-restart: tabs0 is stale, snapshot fresh
    os.environ["CFX_TAB"] = new
    if persist:
        _persist_tab(new)
    return new


_COOKIE_FIND_JS = r"""
(() => {
  // Recognised consent-banner containers — an accept-ish button is only clicked
  // if it lives INSIDE one of these, so we never hit a bare "Accept"/"Continue"
  // on an application form.
  const CONSENT = ['#onetrust-banner-sdk','#onetrust-consent-sdk','#ccc',
    '#cookie-banner','#cookie-notice','#cookie-law-info-bar','.cc-window','.cky-consent-bar',
    '[id*="cookie" i]','[class*="cookie" i]','[id*="consent" i]','[class*="consent" i]',
    '[id*="gdpr" i]','[class*="gdpr" i]','[aria-label*="cookie" i]','[aria-label*="consent" i]'];
  // Well-known one-click accept handlers (fast path).
  const KNOWN = ['#onetrust-accept-btn-handler','#accept-recommended-btn-handler',
    '.cc-allow','[data-cc-action="accept"]','#cookie_action_close_header',
    '#wt-cli-accept-all-btn','.cky-btn-accept','#hs-eu-confirmation-button'];
  const vis = el => el && el.offsetParent !== null;
  for (const sel of KNOWN) { const b = document.querySelector(sel); if (vis(b)) return sel; }
  const inBanner = el => CONSENT.some(s => { try { return !!el.closest(s); } catch (e) { return false; } });
  const RE = /^(accept all( cookies)?|accept( all)?( cookies)?|allow all( cookies)?|allow cookies|agree|i agree|got it|ok,? got it|okay|i understand|understood|continue)$/i;
  for (const b of document.querySelectorAll('button,a[role=button],input[type=button],input[type=submit],a')) {
    const t = (b.innerText || b.value || '').replace(/\s+/g, ' ').trim();
    if (!t || t.length > 30 || !RE.test(t) || !vis(b) || !inBanner(b)) continue;
    if (b.id) { try { return '#' + CSS.escape(b.id); } catch (e) {} }
    b.setAttribute('data-cfx-cookie', '1');
    return '[data-cfx-cookie="1"]';
  }
  return '';
})()
"""


def dismiss_cookie_banner(tab: str = None) -> bool:
    """If a cookie/consent banner is overlaying the page, click its accept/allow
    control so it stops swallowing subsequent clicks and stops dominating the a11y
    snapshot (Hermes drives by snapshot, so an overlay banner can wholly block a
    site — verified as the Hackney "can't get past the cookie window" symptom,
    2026-07-14). Returns True iff it dismissed one. CONSERVATIVE by construction:
    only an accept-ish button INSIDE a recognised consent container is clicked, so
    it never fires on an application form's own "Accept"/"Continue". Passive no-op
    (returns False) when no banner is present, so it's safe to call after ANY
    navigate()."""
    try:
        sel = evaluate(_COOKIE_FIND_JS, tab=tab)
    except CfxError:
        return False
    if not isinstance(sel, str) or not sel:
        return False
    try:
        click_selector(sel, pace=False)  # trusted click via the anti-detection layer
    except CfxError:
        try:  # fall back to a JS click if the trusted click 500s on the overlay
            evaluate(f"(()=>{{const b=document.querySelector({json.dumps(sel)});"
                     f"if(b){{b.click();return true;}}return false;}})()", tab=tab)
        except CfxError:
            return False
    time.sleep(0.6)  # let the banner tear down before the caller reads/clicks
    return True


def click_selector(selector: str, pace: bool = True, timeout: int = 30) -> dict:
    """Click by CSS selector (react-select openers etc. that expose no a11y
    ref). Paced like a human click by default. `timeout` bounds the /click round-trip:
    a *trusted* Playwright click on some React controls (Greenhouse remix comboboxes) can
    otherwise hang ~30s waiting for actionability — callers on a hot path (the combobox
    ladder's trusted-click rung) pass a short timeout so a stuck widget can't stall the run."""
    if pace:
        human_pause()
    return post(f"/tabs/{_tab()}/click", {"userId": _uid(), "selector": selector}, timeout)


def click_ref(ref: str, pace: bool = True) -> dict:
    if pace:
        human_pause()
    return post(f"/tabs/{_tab()}/click", {"userId": _uid(), "ref": ref})


def press(key: str, pace: bool = False) -> dict:
    """Press a key (Escape/Enter/Tab). Not paced by default — often used as a
    fast cleanup step (e.g. Escape to close a stale dropdown)."""
    if pace:
        human_pause()
    return post(f"/tabs/{_tab()}/press", {"userId": _uid(), "key": key})


def poll(expression, predicate=bool, timeout: float = 3.0, interval: float = 0.2, tab: str = None):
    """Repeatedly evaluate `expression` until `predicate(result)` is truthy or
    `timeout` elapses. Returns the last result either way. Replaces fragile
    fixed `sleep()`s that race async DOM mounts (e.g. a react-select option
    list appearing)."""
    deadline = time.time() + timeout
    result = None
    while True:
        try:
            result = evaluate(expression, tab=tab)
        except CfxError:
            result = None
        if predicate(result):
            return result
        if time.time() >= deadline:
            return result
        time.sleep(interval)


def _read_method(method: str, path: str, params: dict, timeout: int, tries: int) -> dict:
    """Shared GET/DELETE with a bounded retry on TRANSIENT transport errors (B.5).
    GET/DELETE are idempotent, so retrying a socket.timeout / connection-reset (the
    exact blips that happen during the engine's restart/reset windows) is safe and
    stops a momentary flake from surfacing as a hard CfxError to a one-shot caller
    (list_tabs inside click_and_follow / find_popup). An HTTPError is a real server
    response — never retried. POST is deliberately NOT routed here (a click/type/submit
    must never auto-retry: double-submit risk on a live form)."""
    from urllib.parse import urlencode
    qs = f"?{urlencode(params)}" if params else ""
    req = urllib.request.Request(
        f"{U}{path}{qs}", headers={"Authorization": f"Bearer {_key()}"}, method=method)
    last = None
    for attempt in range(max(1, tries)):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return _parse_json(r.read(), path)
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = json.loads(e.read()).get("error", "")
            except Exception:
                pass
            raise CfxError(f"{path} -> HTTP {e.code} {detail}".strip()) from None
        except socket.timeout:
            last = CfxError(f"{path} -> timed out after {timeout}s")
        except urllib.error.URLError as e:
            last = CfxError(f"{path} -> cannot reach camofox at {U}: {getattr(e, 'reason', e)}")
        except OSError as e:
            # Read-phase connection reset (mid-restart) raises bare OSError, not
            # URLError — see the matching comment in post().
            last = CfxError(f"{path} -> connection error: {e}")
        if attempt + 1 < tries:
            time.sleep(0.3)
    raise last from None


def get(path: str, params: dict = None, timeout: int = 15, tries: int = 2) -> dict:
    """GET from the camofox REST API (idempotent → bounded retry, B.5)."""
    return _read_method("GET", path, params, timeout, tries)


def delete(path: str, params: dict = None, timeout: int = 15, tries: int = 2) -> dict:
    """DELETE from the camofox REST API (idempotent → bounded retry, B.5)."""
    return _read_method("DELETE", path, params, timeout, tries)


def close_tab(tab_id: str) -> dict:
    """Close a tab (DELETE requires `userId` as a query param — a real bug in an
    earlier version of this function omitted it, causing the server's resulting
    `{"error":"userId required"}` HTTPError to be silently swallowed by the
    idempotent-success fallback below, so tabs that should have closed didn't and
    `list_tabs()` kept showing them — verified live 2026-07-13). Genuinely
    idempotent server-side once userId IS passed — treated as success even if the
    tab is already gone."""
    try:
        return delete(f"/tabs/{tab_id}", {"userId": _uid()})
    except CfxError:
        return {"ok": True}


def list_tabs() -> list:
    """All managed tabs for CFX_USER: [{"tabId": "...", "url": "..."}, ...]."""
    data = get("/tabs", {"userId": _uid()})
    tabs = data.get("tabs") if isinstance(data, dict) else data
    return tabs or []


def find_popup(exclude: str = None) -> list:
    """Tabs other than `exclude` (default: current CFX_TAB) — a genuine popup
    (CAPTCHA challenge, external-ATS handoff) shows up here."""
    exclude = exclude or os.environ.get("CFX_TAB", "")
    return [t for t in list_tabs() if isinstance(t, dict) and t.get("tabId") != exclude]


# Command used to restart the browser container when the engine wedges (see
# CAPABILITY-GAPS.md's "ALL mouse endpoints ... 500 across every tab" section).
# The default assumes a `compose.yaml` in the current directory; override via
# CFX_RESTART_CMD (space-separated) for your own path / docker binary / sudo rule, e.g.
#   export CFX_RESTART_CMD="sudo -n docker compose -f /path/to/compose.yaml restart camofox-browser"
_RESTART_CMD = os.environ.get("CFX_RESTART_CMD", "").split() or [
    "docker", "compose", "-f", "compose.yaml", "restart", "camofox-browser",
]


def engine_click_healthy(timeout_s: float = 6.0) -> bool:
    """Is the click endpoint actually delivering real clicks right now — anywhere —
    or is the whole engine's mouse-input path broken? This is a REAL, CONFIRMED
    fault (2026-07-13): every click/hover/scroll 500'd on every tab, on every
    element, while `press`/`evaluate` kept working and `/health` looked perfectly
    normal throughout. From the outside that fault looks IDENTICAL to a genuine
    site-side dead button (no popup, no nav, click endpoint may even 500) — a
    prior investigation conflated the two and burned a whole session concluding a
    LinkedIn button was unfixably dead before this check existed.

    Requires an already-open CFX_TAB with some page loaded (any page — it does NOT
    need to be a fresh/blank one). Injects a tiny, invisible, throwaway button into
    the CURRENT page via `evaluate` (a real DOM node, not a new tab/navigation —
    `POST /tabs` with a `data:` URL 500s on this backend, which is why an earlier
    version of this function used a scratch tab and got a false negative), clicks
    it, and confirms via a JS flag that the click actually landed — not just that
    the endpoint returned `ok`. Always removes the injected node afterward, leaving
    the page exactly as it was. `click_and_follow` calls this automatically before
    reporting `no_change`; call it directly for a standalone diagnostic
    (`cfx.py check-engine`)."""
    try:
        # NOTE: must be a normal-sized, on-screen target. An earlier version used a
        # 1x1px/off-screen button and got a false "unhealthy" — the click endpoint's
        # own position-jitter anti-detection logic (see ENDPOINT-CAPABILITIES.md) can
        # miss a target that tiny even when the click path is completely healthy, which
        # is indistinguishable from a real fault unless you know to look for it. 24x24
        # in the corner is real estate real UIs use for icon buttons and clicks
        # reliably on it; kept low-opacity so it's not visually distracting if a
        # screenshot is taken mid-check.
        evaluate(
            "(function(){"
            "var b=document.createElement('button');"
            "b.id='__cfxSanity';"
            "b.style.cssText='position:fixed;top:0;left:0;width:24px;height:24px;"
            "opacity:0.01;z-index:2147483647;';"
            "b.onclick=function(){window.__cfxSanityClicked=true};"
            "document.body.appendChild(b);"
            "window.__cfxSanityClicked=false;"
            "return true;"
            "})()"
        )
    except CfxError:
        return False  # can't even run JS on the current page -- treat as unhealthy/unknown, the safe default
    try:
        try:
            click_selector("#__cfxSanity", pace=False)
        except CfxError:
            pass  # a 500 here is exactly the symptom under test; the flag read below is the real verdict
        return poll("window.__cfxSanityClicked", predicate=lambda r: r is True,
                    timeout=timeout_s, interval=0.3) is True
    finally:
        try:
            evaluate("(function(){var e=document.getElementById('__cfxSanity'); "
                     "if(e) e.remove(); return true;})()")
        except CfxError:
            pass


def restart_engine(health_timeout_s: float = 90.0) -> bool:
    """Restart camofox-browser via the passwordless sudoers rule set up specifically
    for this fault, then poll `/health` until it reports `browserConnected` again.
    Works identically on Hermes (real terminal_tool) and Claude Code (real Bash) —
    both have a genuine shell, which is all this needs; no browser-tool wrapper
    involved. **Drops every open tab** (a real restart, not a config no-op) — this
    is expected and cheap; login persists (cookies live in the camoufox profile,
    not the tab). Returns False (never raises) if the restart command itself fails
    (e.g. the sudoers rule isn't present on this host) or the engine never comes
    back healthy within the timeout — callers must surface that to a human rather
    than silently giving up, since it means the self-heal path itself needs
    attention, not just this one click."""
    import subprocess
    try:
        # 90s, not 30s: verified live (2026-07-13) that `docker compose restart` run
        # through subprocess (pipes, no TTY) can take noticeably longer to return than
        # it appears to interactively — the restart itself succeeded server-side
        # (confirmed via /health going browserConnected:false then true a few seconds
        # later) even though a 30s subprocess timeout fired first and reported failure.
        # The health poll below is the real completion signal either way; this timeout
        # just needs to comfortably outlast the CLI call itself.
        subprocess.run(_RESTART_CMD, check=True, timeout=90,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except subprocess.TimeoutExpired:
        pass  # the restart may still have gone through server-side -- let the health poll decide
    except Exception:
        return False
    deadline = time.time() + health_timeout_s
    while time.time() < deadline:
        try:
            h = get("/health", timeout=5)
            if isinstance(h, dict) and h.get("browserConnected"):
                return True
        except CfxError:
            pass
        time.sleep(2)
    return False


def health_fingerprint(tab: str = None) -> dict:
    """A cheap, READ-ONLY snapshot of backend liveness — the primitive behind
    feature-roadmap H.1 (health-fingerprinted verdicts). SKILL.md's CONTAMINATION
    META-RULE says a DEGRADED camofox backend (blank renders, document.title='',
    innerText.length=0, eval hangs, /health up but tabs render blank) mints FALSE
    terminal verdicts ('exhausted' / 'external-route' / 'wedge') that have cost whole
    sessions. This lets a driver STAMP every terminal negative with the backend's health
    at verdict time, so a verdict recorded while degraded can be quarantined and re-tested
    after recovery instead of trusted.

    Does NOT navigate (so it never disturbs an in-progress apply) — it reads /health and
    runs ONE tiny evaluate on the CURRENT tab. Returns:
      {ts, browser_connected: bool|None, eval_ok: bool|None, innerText_len, title_len,
       url, blank_render: bool, degraded: bool|None}
    Interpretation:
      degraded=True  — backend is provably unhealthy (not connected, or eval failed): any
                       terminal negative recorded now is SUSPECT.
      degraded=False — backend answered and ran JS: the verdict is trustworthy.
      degraded=None  — health unknown (no CFX_KEY / probe couldn't run): neither confirm
                       nor deny; a caller may treat as non-suspect but should note it.
      blank_render   — eval ran but the page has empty title AND empty body text (the
                       documented open-tab-nav / degraded-render tell). A caller that KNOWS
                       the tab should have content (just screened/filled a real page) should
                       treat blank_render as degraded too.
    Best-effort; never raises."""
    import os as _os
    fp = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "browser_connected": None,
          "eval_ok": None, "innerText_len": 0, "title_len": 0, "url": "",
          "blank_render": False, "degraded": None}
    if not _os.environ.get("CFX_KEY"):
        return fp  # health unknown — no browser configured in this process
    try:
        h = get("/health", timeout=5)
        fp["browser_connected"] = bool(h.get("browserConnected")) if isinstance(h, dict) else None
    except Exception:  # noqa: BLE001
        fp["browser_connected"] = None
    try:
        raw = evaluate(
            "JSON.stringify({t:(document.title||'').length,"
            "l:(document.body?document.body.innerText.length:0),"
            "u:location.href})", tab=tab, timeout=10)
        import json as _json
        d = _json.loads(raw) if isinstance(raw, str) else (raw or {})
        fp["eval_ok"] = True
        fp["title_len"] = int(d.get("t") or 0)
        fp["innerText_len"] = int(d.get("l") or 0)
        fp["url"] = d.get("u") or ""
        fp["blank_render"] = (fp["title_len"] == 0 and fp["innerText_len"] == 0
                              and not fp["url"].startswith("about:"))
    except Exception:  # noqa: BLE001
        fp["eval_ok"] = False
    # degraded verdict: connected==False OR eval failed => provably degraded.
    if fp["browser_connected"] is False or fp["eval_ok"] is False:
        fp["degraded"] = True
    elif fp["browser_connected"] or fp["eval_ok"]:
        fp["degraded"] = False
    return fp


def _click_through_confirmation_dialog() -> dict:
    """Look for a pre-redirect confirmation dialog (main document OR inside any
    shadow root, one level of `document.querySelectorAll('*')` deep — same pattern
    as LinkedIn's Easy Apply modal) and click its "Continue"-style control if one
    is unambiguously present.

    THIS EXISTS because of a real, confirmed bug (2026-07-13): LinkedIn's external
    "Apply on company website" button genuinely opens a "Share your profile?"
    consent dialog before handing off to the destination ATS — it was NOT a dead
    button. The camofox server's own post-click housekeeping (`dismissConsentDialogs`,
    meant only for cookie/GDPR banners) was silently auto-closing it via an overly
    generic "any modal's close button" selector, inside the SAME `/click` request
    that opened it — before any caller-side snapshot/screenshot could ever see it.
    Fixed in `server.js` (narrowed those selectors to be cookie/consent-specific
    only); this function is the other half — once the dialog is allowed to survive,
    something has to actually click "Continue" instead of leaving it sitting there
    forever masquerading as `no_change`.

    Returns `{"found": False}` if no dialog-like element exists. If one exists:
    `{"found": True, "dialog_text": "...", "clicked": True, "button_text": "..."}`
    if a button/link whose text matches an affirmative continue-pattern (continue/
    agree/accept/proceed/got it/ok) — and NOT a decline pattern (cancel/close/no
    thanks/not now/decline/skip) — was found and clicked; `{"found": True,
    "dialog_text": "...", "clicked": False}` if a dialog is present but nothing
    inside it could be safely identified as the affirmative action (deliberately
    does NOT guess in that case — a wrong click here could decline a real
    application step)."""
    js = r"""
    (function(){
      function findDialogs(root, out) {
        var all = root.querySelectorAll('*');
        for (var i=0;i<all.length;i++) {
          var el = all[i];
          if (el.matches && el.matches('[role="dialog"],[role="alertdialog"]')) out.push(el);
          if (el.shadowRoot) findDialogs(el.shadowRoot, out);
        }
        return out;
      }
      var dialogs = findDialogs(document, []);
      if (!dialogs.length) return JSON.stringify({found: false});
      var dlg = dialogs[0];
      var text = (dlg.innerText||'').slice(0, 300);
      var candidates = Array.from(dlg.querySelectorAll('button, a, [role="button"]'));
      var chosen = null, label = '';
      for (var i=0;i<candidates.length;i++) {
        var t = (candidates[i].innerText||candidates[i].getAttribute('aria-label')||'').trim();
        if (/\b(continue|agree|accept|proceed|got it|ok)\b/i.test(t) &&
            !/\b(cancel|close|no thanks|not now|decline|skip)\b/i.test(t)) {
          chosen = candidates[i]; label = t; break;
        }
      }
      if (!chosen) return JSON.stringify({found: true, dialogText: text, clicked: false});
      chosen.click();
      return JSON.stringify({found: true, dialogText: text, clicked: true, buttonText: label});
    })()
    """
    try:
        raw = evaluate(js)
        result = json.loads(raw) if isinstance(raw, str) else (raw or {})
    except (CfxError, ValueError):
        result = {}
    return {
        "found": bool(result.get("found")),
        "dialog_text": result.get("dialogText", ""),
        "clicked": bool(result.get("clicked")),
        "button_text": result.get("buttonText", ""),
    }


def _page_state():
    """ONE evaluate returning (href, has_dialog): the current URL AND whether a
    [role=dialog]/[role=alertdialog] exists anywhere (incl. shadow roots) — read-only,
    no click. B.2: lets click_and_follow's poll do its URL check AND gate the
    side-effecting dialog-click probe in a single round-trip instead of two per
    iteration. The dialog detection mirrors _click_through_confirmation_dialog's
    findDialogs EXACTLY (same selector), so gating on it never hides a real dialog."""
    js = r"""
    (function(){
      function has(root){
        var all = root.querySelectorAll('*');
        for (var i=0;i<all.length;i++){
          var el=all[i];
          if (el.matches && el.matches('[role="dialog"],[role="alertdialog"]')) return true;
          if (el.shadowRoot && has(el.shadowRoot)) return true;
        }
        return false;
      }
      return JSON.stringify({href: location.href, dialog: has(document)});
    })()
    """
    try:
        raw = evaluate(js)
        d = json.loads(raw) if isinstance(raw, str) else (raw or {})
    except (CfxError, ValueError):
        d = {}
    return d.get("href", ""), bool(d.get("dialog"))


def click_and_follow(ref: str = None, selector: str = None,
                      timeout_s: float = 8.0, poll_interval: float = 0.4,
                      auto_heal: bool = True) -> dict:
    """Click `ref` or `selector` and report what actually happened next, instead
    of leaving the caller to remember a multi-step "click, then check
    find-popup, then check the URL" procedure by hand.

    THIS EXISTS because that manual procedure is exactly what a real
    investigation needed 2026-07-13 to tell "opened a new tab I can switch to"
    apart from "did nothing at all" (see sites/linkedin/NOTES.md's "CONFIRMED
    SYSTEMIC" section and sites/_common/CAPABILITY-GAPS.md's "AGENT TOOL-WRAPPER
    GAP" section) — an agent without every one of those individual steps handy
    (or without the patience to run them all) can misdiagnose a genuine dead
    click as a "camofox limitation" or vice versa. One call, one of three
    unambiguous outcomes, on ANY agent that can run a Python script:

        {"outcome": "new_tab", "tab_id": "...", "url": "..."}   -> switch CFX_TAB to tab_id and continue there
        {"outcome": "same_tab_nav", "url": "..."}                -> current tab navigated in place, keep going
        {"outcome": "no_change", "url": "<unchanged>"}           -> engine confirmed healthy (see below), no dialog
                                                                     seen, and still nothing happened; this is a
                                                                     genuine site-side dead button — needs a human
                                                                     via VNC or Blocked
        {"outcome": "unhandled_dialog", "dialog_text": "...", "url": "..."}
                                                                  -> a real dialog appeared (e.g. LinkedIn's "Share
                                                                     your profile?" before an external-ATS handoff)
                                                                     but nothing inside it was safely identifiable
                                                                     as "continue" — read dialog_text and handle it
                                                                     manually (snapshot the tab, click the right
                                                                     control yourself). NOT proof of a dead button —
                                                                     do NOT log Blocked for "unresolved gap" reasons.
        {"outcome": "engine_broken_needs_restart", "url": "...", "note": "..."}
                                                                  -> see auto_heal below; NOT proof of a dead button.
                                                                     Does NOT restart anything itself — read `note`.

    **Automatically clicks through a recognized pre-redirect confirmation dialog**
    (e.g. LinkedIn's "Share your profile?" step before handing off to an external
    ATS — see `_click_through_confirmation_dialog`'s docstring for the full,
    previously-misdiagnosed-as-a-dead-button story) before ever reaching `no_change`.
    If a dialog appears with an unambiguous "Continue"/"Agree"/etc. control, it's
    clicked automatically and polling continues with a fresh timeout budget. If a
    dialog appears with NO safely-identifiable continue control, that's reported as
    `unhandled_dialog` (see above) rather than silently guessed at or reported as
    `no_change`.

    Handles the confirmed real quirk where the underlying /click endpoint can
    itself hang or 500 for exactly these buttons (suspected: it internally waits
    on a navigation/network-idle signal that never arrives when nothing
    happens) — that error is swallowed and treated as "click landed, now
    checking for effects," not a hard failure, since a raw CfxError there is NOT
    proof the click had no effect.

    **auto_heal (default True) — DIAGNOSES automatically, never RESTARTS automatically.**
    Before reporting `no_change`, this is EXACTLY the situation a real, confirmed fault
    produces (2026-07-13: every mouse endpoint 500'ing on every tab while /health looks
    fine) — which is indistinguishable from a genuine dead button without checking. So
    `no_change` first runs `engine_click_healthy()` (a cheap, isolated control-click,
    read-only, touches nothing):
      - Healthy -> the original `no_change` really does mean a dead button. Reported
        as-is.
      - NOT healthy -> this is the engine fault, not this button. Returns
        `engine_broken_needs_restart` — a pure diagnosis, no side effects. **Does NOT
        call `restart_engine()` itself** (an EARLIER version of this function did, and
        it killed a tab mid-navigation during a real live application because nothing
        had checked whether that was safe first — a restart drops every open tab,
        including any in-progress form on this one, and must never fire unprompted
        mid-flow). The caller must explicitly decide it's safe (nothing valuable in
        flight, here or on any other open tab) and call `restart_engine()` /
        `python3 cfx.py restart-engine` itself, or ask the user first if unsure.
    Pass `auto_heal=False` to skip the diagnosis entirely and get the raw old behavior
    (e.g. for testing).
    """
    before_url = current_url()
    before_tabs = {t.get("tabId") for t in list_tabs() if isinstance(t, dict)}

    try:
        if selector:
            click_selector(selector)
        else:
            click_ref(ref)
    except CfxError:
        pass  # a hang/500 here is not proof of "nothing happened" -- keep polling

    dialog_seen = None
    deadline = time.time() + timeout_s
    while True:
        tabs_now = list_tabs()
        now_ids = {t.get("tabId") for t in tabs_now if isinstance(t, dict)}
        new_ids = now_ids - before_tabs
        if new_ids:
            new_id = next(iter(new_ids))
            url = next((t.get("url", "") for t in tabs_now
                        if isinstance(t, dict) and t.get("tabId") == new_id), "")
            return {"outcome": "new_tab", "tab_id": new_id, "url": url}
        # B.2: one evaluate returns the href AND whether a dialog exists, so the URL
        # check and the dialog gate share a single round-trip; the side-effecting
        # click-through probe fires only on the (rare) iteration a dialog is present.
        url_now, has_dialog = _page_state()
        if url_now and url_now != before_url:
            return {"outcome": "same_tab_nav", "url": url_now}
        if dialog_seen is None and has_dialog:
            # A pre-redirect confirmation dialog (e.g. LinkedIn's "Share your
            # profile?") looks EXACTLY like no_change/timeout until this checks for
            # it — see _click_through_confirmation_dialog's docstring for the full
            # story. Keep checking every iteration until one shows up or we give up.
            probe = _click_through_confirmation_dialog()
            if probe.get("found"):
                dialog_seen = probe
                if probe.get("clicked"):
                    # Clicking through may trigger its own redirect/new tab -- give
                    # it the full original budget again from here, not whatever's left.
                    deadline = time.time() + timeout_s
                    time.sleep(poll_interval)
                    continue
                # Found a dialog but nothing inside it looked like an affirmative
                # continue action -- do NOT guess (a wrong click could decline a
                # real step). Fall through to report it below once the deadline hits.
        if time.time() >= deadline:
            if dialog_seen and not dialog_seen.get("clicked"):
                return {"outcome": "unhandled_dialog", "dialog_text": dialog_seen.get("dialog_text", ""),
                        "url": before_url}
            if not auto_heal or engine_click_healthy():
                return {"outcome": "no_change", "url": before_url}
            # Engine confirmed broken, not this button -- BUT restarting is destructive
            # (drops EVERY open tab, including any in-progress form on THIS one) and must
            # never fire unprompted mid-application. Verified live 2026-07-13: an earlier
            # version of this code auto-restarted here, and it killed a tab mid-navigation
            # during a real apply flow (LinkedIn -> Adzuna -> Workable) -- no data was lost
            # only because nothing had been filled in yet on that specific run, but the
            # same auto-restart on a form that WAS mid-fill would have destroyed real
            # progress. Report the diagnosis; never act on it automatically.
            return {
                "outcome": "engine_broken_needs_restart",
                "url": before_url,
                "note": "Click endpoint confirmed broken globally (not this button) -- "
                        "verified via a control click, not a guess. This is NOT a dead "
                        "button/site issue, do not log Blocked for it. Restarting "
                        "camofox-browser fixes it but DROPS EVERY OPEN TAB, including any "
                        "in-progress form on this one -- confirm nothing valuable is in "
                        "flight (this tab and any others) before restarting, or ask the "
                        "user if unsure. Then call restart_engine() / `python3 cfx.py "
                        "restart-engine` yourself. After it's back (browserConnected:true), "
                        "re-open this posting's URL fresh and retry -- login persists in "
                        "the camoufox profile, nothing else does.",
            }
        time.sleep(poll_interval)


def _get_bytes(path: str, timeout: int = 30) -> bytes:
    """Raw GET returning the response body as bytes (for the screenshot endpoint,
    which serves a PNG, not JSON). Same auth + error mapping as post()."""
    req = urllib.request.Request(f"{U}{path}",
                                 headers={"Authorization": f"Bearer {_key()}"}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        raise CfxError(f"{path} -> HTTP {e.code}") from None
    except (urllib.error.URLError, OSError) as e:
        raise CfxError(f"{path} -> {getattr(e, 'reason', e)}") from None


def shot(outfile: str = "/tmp/cfx-shot.png", selector: str = None,
         clip: tuple = None, pad: int = 14, tab: str = None) -> str:
    """Screenshot the tab to `outfile`. With `selector` OR `clip=(x,y,w,h)` (CSS px),
    crop to that region CLIENT-SIDE (Pillow) — the pre-submit vision gate only needs
    the email/radio/CAPTCHA area, and a region crop is ~80% fewer vision tokens than a
    full page (and fewer misses — the model isn't hunting a 2000px page). `selector`
    is resolved to a box via getBoundingClientRect × devicePixelRatio. No server
    change: we fetch the full PNG and crop locally; if Pillow is missing or the region
    can't be resolved, the full screenshot is written and a note returned. Returns the
    path written (with a ' (full: <reason>)' suffix if the crop was skipped)."""
    png = _get_bytes(f"/tabs/{_tab(tab)}/screenshot?userId={_uid()}")
    box = clip
    if box is None and selector:
        try:
            r = evaluate(
                "(() => { const e=document.querySelector(%s); if(!e) return null;"
                " const b=e.getBoundingClientRect(); const d=window.devicePixelRatio||1;"
                " return [b.x,b.y,b.width,b.height,d]; })()" % json.dumps(selector), tab=tab)
            if isinstance(r, (list, tuple)) and len(r) == 5 and r[2] and r[3]:
                dpr = r[4] or 1
                box = (r[0] * dpr, r[1] * dpr, r[2] * dpr, r[3] * dpr)
                pad = pad * dpr
        except CfxError:
            box = None
    if box is None:
        with open(outfile, "wb") as f:
            f.write(png)
        return outfile + ("" if (not selector and not clip) else " (full: region not resolved)")
    try:
        import io
        from PIL import Image
        im = Image.open(io.BytesIO(png))
        x, y, w, h = box
        left = max(0, int(x - pad)); top = max(0, int(y - pad))
        right = min(im.width, int(x + w + pad)); bottom = min(im.height, int(y + h + pad))
        im.crop((left, top, right, bottom)).save(outfile)
        return outfile
    except Exception as e:  # noqa: BLE001 — Pillow missing / decode error -> full shot
        with open(outfile, "wb") as f:
            f.write(png)
        return outfile + f" (full: crop failed: {e})"


def _cli():
    import sys
    if len(sys.argv) < 2:
        print("Usage: cfx.py <list-tabs|find-popup|open-tab|ensure-tab|sync-tab|prune-tabs|"
              "dismiss-cookies|click-follow|shot|check-engine|restart-engine|eval-frame> "
              "[args...]", file=sys.stderr)
        return 1
    cmd = sys.argv[1]
    try:
        if cmd == "list-tabs":
            print(json.dumps(list_tabs(), indent=2))
        elif cmd == "find-popup":
            print(json.dumps(find_popup(), indent=2))
        elif cmd == "open-tab":
            # cfx.py open-tab [url]  -> prints the new tabId (robust against the
            # flaky create-500). Handy for a scratch/warm tab from the shell.
            print(open_tab(sys.argv[2] if len(sys.argv) > 2 else "about:blank"))
        elif cmd == "ensure-tab":
            # cfx.py ensure-tab  -> guarantee a live CFX_TAB, reopening if camofox
            # restarted and dropped it; prints the (possibly new) tabId and persists
            # it to CFX_TAB_FILE if set. Supersedes open_tab.sh — one implementation.
            print(ensure_tab())
        elif cmd == "sync-tab":
            # cfx.py sync-tab  -> ensure a live tab, then rewrite EVERY standard pointer
            # file (.jobenv.run/.persist/.apply/.runenv + CFX_TAB_FILE[S]) to it in one
            # call. Fixes the divergent-CFX_TAB "Session expired" trap where each env file
            # carried a different (often stale) tab id. Prints the tab + the files written.
            written = sync_tab()
            print(json.dumps({"tab": os.environ.get("CFX_TAB"),
                              "synced": written}, indent=2))
        elif cmd == "prune-tabs":
            # cfx.py prune-tabs [budget]  -> proactively close stale tabs down to headroom
            # under the ~8-tab wedge threshold (never the active CFX_TAB). Preventive
            # maintenance a cron/loop can run so background tabs never accumulate to a wedge.
            b = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else None
            closed = prune_tabs(budget=b)
            print(json.dumps({"reaped": len(closed), "closed": closed,
                              "budget": b if b is not None else TAB_BUDGET}, indent=2))
        elif cmd == "dismiss-cookies":
            # cfx.py dismiss-cookies  -> accept a cookie/consent overlay on CFX_TAB
            # if present. For hand-driving a site (Hackney etc.) before snapshotting;
            # the feed/jd/apply scripts already call this automatically.
            print(json.dumps({"dismissed": dismiss_cookie_banner()}, indent=2))
        elif cmd == "eval-frame":
            if len(sys.argv) < 4:
                print("Usage: cfx.py eval-frame <frameSelector> '<js expression>'", file=sys.stderr)
                return 1
            print(json.dumps(eval_frame(sys.argv[2], sys.argv[3]), indent=2))
        elif cmd == "shot":
            # cfx.py shot [outfile] [--selector <css>] [--clip x,y,w,h]
            # Region crop (selector/clip) -> the pre-submit vision gate reads only the
            # email/radio/CAPTCHA area (far fewer vision tokens). No arg -> full page.
            rest, out, sel, clip = sys.argv[2:], "/tmp/cfx-shot.png", None, None
            k = 0
            while k < len(rest):
                a = rest[k]
                if a == "--selector" and k + 1 < len(rest):
                    sel = rest[k + 1]; k += 2
                elif a == "--clip" and k + 1 < len(rest):
                    try:
                        parts = tuple(float(x) for x in rest[k + 1].split(","))
                        clip = parts if len(parts) == 4 else None
                    except ValueError:
                        clip = None
                    k += 2
                elif not a.startswith("--"):
                    out = a; k += 1
                else:
                    k += 1
            print(shot(out, selector=sel, clip=clip))
        elif cmd == "click-follow":
            if len(sys.argv) < 3:
                print("Usage: cfx.py click-follow <ref>  (or --selector <css>) [--no-heal]", file=sys.stderr)
                return 1
            auto_heal = "--no-heal" not in sys.argv
            if sys.argv[2] == "--selector":
                result = click_and_follow(selector=sys.argv[3], auto_heal=auto_heal)
            else:
                result = click_and_follow(ref=sys.argv[2], auto_heal=auto_heal)
            print(json.dumps(result, indent=2))
        elif cmd == "goto":
            # cfx.py goto <url> [--no-verify]  — navigate + verify the page rendered (X.1).
            # Exit 3 on a blank render (the open-tab-nav trap) so a shell caller can branch.
            if len(sys.argv) < 3:
                print("Usage: cfx.py goto <url> [--no-verify]", file=sys.stderr)
                return 1
            res = goto(sys.argv[2], verify="--no-verify" not in sys.argv)
            print(json.dumps(res, indent=2))
            return 0 if res.get("ok") else 3
        elif cmd == "persist-env":
            # cfx.py persist-env [file]  — write BOTH CFX_KEY and CFX_TAB to the persist file
            # ATOMICALLY (X.1). Kills the `.jobenv.persist` clobber scar: `echo CFX_TAB= >
            # .jobenv.persist` overwrote the whole file and destroyed CFX_KEY. This always
            # writes both vars (reading the key from env), so the file is never half-written.
            dest = sys.argv[2] if len(sys.argv) > 2 else os.environ.get(
                "CFX_TAB_FILE", os.path.join(os.getcwd(), ".jobenv.persist"))
            key = os.environ.get("CFX_KEY", "")
            tab = os.environ.get("CFX_TAB", "")
            if not key:
                print("REFUSING: CFX_KEY not in env — persisting would write a keyless file. "
                      "source .jobenv.run first.", file=sys.stderr)
                return 2
            body = f'export CFX_KEY="{key}"\nexport CFX_TAB="{tab}"\n'
            tmp = dest + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(body)
            os.replace(tmp, dest)
            print(f"persisted CFX_KEY + CFX_TAB -> {dest}")
            return 0
        elif cmd == "health-fingerprint":
            # H.1: cheap read-only backend-liveness snapshot to STAMP a terminal verdict
            # with (so a verdict recorded during a degraded window can be quarantined).
            # Exit 3 when provably degraded, so a shell caller can branch on it.
            fp = health_fingerprint()
            print(json.dumps(fp, indent=2))
            return 3 if fp.get("degraded") else 0
        elif cmd == "check-engine":
            # Standalone diagnostic: is the click endpoint actually working right now?
            # Useful before starting a run, or when something feels stuck for no visible
            # reason. Does NOT restart anything by itself -- see restart-engine.
            healthy = engine_click_healthy()
            print(json.dumps({"click_endpoint_healthy": healthy}, indent=2))
            if not healthy:
                print("Click endpoint is broken (every mouse action fails, not just one "
                      "button/tab) even though /health may look fine. Run "
                      "'python3 cfx.py restart-engine' to self-heal.", file=sys.stderr)
                return 3
        elif cmd == "restart-engine":
            print("Restarting camofox-browser (drops all open tabs; login persists)...",
                  file=sys.stderr)
            ok = restart_engine()
            print(json.dumps({"restarted_and_healthy": ok}, indent=2))
            if not ok:
                print("Restart failed or engine never came back healthy -- check "
                      "'sudo -n -l' for the camofox-restart rule, or restart manually.",
                      file=sys.stderr)
                return 3
        else:
            print(f"Unknown command: {cmd}", file=sys.stderr)
            return 1
    except CfxError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_cli())
