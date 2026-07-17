#!/usr/bin/env python3
"""httpfeed.py — the shared runtime every declarative board feed is built on.

WHY: before this, each `sites/<board>/scripts/feed.py` re-implemented the same ~200 lines
(arg parsing, cooldown gate, tracker dedup, pagination, JSON emit, exhaustion marking) and
only ~30 of those lines were actually board-specific. That duplication is why adding a
board used to be a day's work. Here the *runtime* lives once and each board ships a small
declarative `Board` spec: how to build a search URL, how to pull rows out of a response,
and how to map one row to the shared posting shape.

A board feed is therefore:

    import httpfeed
    BOARD = httpfeed.Board(
        board="dwp", base="https://findajob.dwp.gov.uk", ...,
        search_url=..., parse=..., seen_pattern=...,
    )
    if __name__ == "__main__":
        sys.exit(httpfeed.run(BOARD))

Fetch strategy (`Board.fetch`):
  - "http"   plain urllib GET. No browser → runs anywhere (Hermes cron, CI, Claude Code).
  - "cfx"    render through camofox (bot-walled boards). Requires CFX_KEY/CFX_TAB.
  - "auto"   try http; if it fails/looks walled, fall back to cfx when available.

Every feed built on this keeps the established contract the loop depends on:
  - prints a JSON list of postings to stdout (the ONLY thing on stdout),
  - prints human status to stderr,
  - exit 0 = fresh jobs, 1 = none/cooldown, 2 = error,
  - honours --all (include tracked + bypass cooldown) and --force (bypass cooldown only),
  - records yields + auto-marks an adaptive cooldown on a dry pass.

The posting shape (shared with every pre-existing feed; `precheck.py` consumes it):
    {id, url, title, company, location, salary, source[, created, ats_hint, redirect_url]}
"""
import gzip
import html
import json
import os
import re
import sys
import time
import zlib
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse, parse_qs  # noqa: F401  (re-exported for boards)
from urllib.request import Request, urlopen

_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)
import board_cooldown  # noqa: E402
from precheck import load_seen  # noqa: E402

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

TRACKER = os.path.join(_here, "..", "..", "..", "application-tracker.csv")


# ── the board spec ───────────────────────────────────────────────────────────
class Board:
    """Declarative description of one job board.

    board        cooldown/`--boards` slug (e.g. "dwp") — must match pipeline.FEEDS key.
    name         human label for stderr messages.
    base         site origin, used to absolutise relative hrefs.
    search_url   fn(what, where, page) -> url. `page` is 1-based.
    parse        fn(text, ctx) -> list[dict] of *raw* rows (board-shaped, not normalised).
    normalize    fn(raw, ctx) -> posting dict | None. Pure — this is what tests target.
    seen_pattern regex w/ ONE group capturing this board's id as it appears in the tracker.
    fetch        "http" | "cfx" | "auto".
    headers      extra request headers (e.g. Accept: application/json).
    default_where default location when the caller passes none.
    per_page     rows/page; a short page ends pagination early.
    render_wait  seconds to wait after a cfx navigate before scraping.
    apply_hint   one-line stderr note telling the agent how applying works here.
    body         fn(what, where, page) -> dict, for POST-only JSON APIs (jooble). When set,
                 the fetch becomes a JSON POST to `search_url` with this as the body.
                 Default None = ordinary GET.
    sparse       True when a page can legitimately normalise to ZERO keepers — i.e. the board
                 is an unfiltered firehose and `normalize` does the location/eligibility
                 filtering client-side (himalayas: ~12% of rows are UK-eligible, so a barren
                 page is normal, not the end of the results). Default False preserves the
                 original "a page that adds nothing new ends pagination" behaviour.
    """

    def __init__(self, board, name, base, search_url, parse, normalize, seen_pattern,
                 fetch="http", headers=None, default_where="London", per_page=None,
                 render_wait=5, apply_hint="", query_from_nav=None, needs=None,
                 sparse=False, body=None):
        self.board = board
        self.name = name
        self.base = base
        self.search_url = search_url
        self.parse = parse
        self.normalize = normalize
        self.seen_pattern = seen_pattern
        self.fetch = fetch
        self.headers = headers or {}
        self.default_where = default_where
        self.per_page = per_page
        self.render_wait = render_wait
        self.apply_hint = apply_hint or "Iterate each .url; apply resolves per-listing."
        self.query_from_nav = query_from_nav
        self.needs = needs or (lambda: None)   # -> error string if a credential is missing
        self.sparse = sparse
        self.body = body


# ── helpers boards reuse ─────────────────────────────────────────────────────
def absolutise(href, base):
    """Relative href -> absolute URL, query/fragment stripped."""
    if not href:
        return ""
    href = href.strip()
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("http"):
        return href.split("#")[0]
    return base.rstrip("/") + "/" + href.lstrip("/")


def clean(s):
    """Strip tags, decode HTML entities, collapse whitespace.

    Uses stdlib `html.unescape`, which handles ALL three entity forms — named
    (`&pound;`), decimal (`&#163;`) and **hex (`&#xA3;`)**.

    WHY NOT A HAND-ROLLED TABLE: the original did named + decimal only, so GOV.UK's
    hex-encoded pound sign leaked through verbatim and salaries came out as
    `"&#xA3;19,747"` (hit independently on the apprenticeships and Escape the City
    feeds, 2026-07-17). `html.unescape` is the whole table, correct by construction.
    NBSP is normalised to a plain space afterwards so `\\s+` collapses it.
    """
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", str(s))
    s = html.unescape(s)
    s = s.replace("\xa0", " ")          # unescape turns &nbsp; into U+00A0
    return re.sub(r"\s+", " ", s).strip()


def strip_html(s):
    """Full text extraction from an HTML fragment (drops script/style first)."""
    if not s:
        return ""
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", s)
    return clean(s)


def money(smin, smax, cur="£"):
    """(min,max) -> '£30,000–£40,000' / '£30,000' / ''. Tolerates None + strings."""
    def _n(v):
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return None
    a, b = _n(smin), _n(smax)
    if a and b and a != b:
        return f"{cur}{a:,}–{cur}{b:,}"
    if a:
        return f"{cur}{a:,}"
    if b:
        return f"{cur}{b:,}"
    return ""


def jsonpath(obj, *keys, default=""):
    """Safe nested get: jsonpath(row, 'company', 'name') -> '' when any hop is missing."""
    cur = obj
    for k in keys:
        if isinstance(cur, dict):
            cur = cur.get(k)
        elif isinstance(cur, (list, tuple)) and isinstance(k, int) and -len(cur) <= k < len(cur):
            cur = cur[k]
        else:
            return default
    return cur if cur is not None else default


def query_param(nav, *names):
    """First matching query param value from a URL (case-insensitive)."""
    if not nav:
        return ""
    try:
        qs = parse_qs(urlparse(nav).query)
    except ValueError:
        return ""
    low = {k.lower(): v for k, v in qs.items()}
    for n in names:
        v = low.get(n.lower())
        if v:
            return v[0].replace("+", " ").strip()
    return ""


def creds_row(site_prefix):
    """(email, password) from the shared ats-credentials.csv row whose `site` starts with
    `site_prefix`. This is the ONLY sanctioned credential source — never grep env for board
    keys (documented false-negative that has repeatedly cost whole sessions)."""
    import csv
    path = os.path.join(_here, "..", "..", "..", "ats-credentials.csv")
    try:
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if (row.get("site") or "").strip().startswith(site_prefix):
                    return (row.get("email") or "").strip(), (row.get("password") or "").strip()
    except (FileNotFoundError, OSError):
        pass
    return "", ""


def cards(html, pattern):
    """Split an HTML document into repeated card chunks by a regex. Returns list[str]."""
    return re.findall(pattern, html or "", re.S | re.I)


def first(html, *patterns):
    """First capture group that matches any of `patterns` in `html`, cleaned."""
    for p in patterns:
        m = re.search(p, html or "", re.S | re.I)
        if m:
            return clean(m.group(1))
    return ""


def ld_json(html):
    """Every JSON-LD blob in a page, parsed. Many boards ship JobPosting schema.org data —
    far more stable than CSS selectors."""
    out = []
    for m in re.finditer(r'(?is)<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html or ""):
        try:
            v = json.loads(m.group(1).strip())
        except (ValueError, TypeError):
            continue
        out.extend(v if isinstance(v, list) else [v])
    return out


def next_data(html):
    """Next.js `__NEXT_DATA__` payload (many modern boards embed the full job list here)."""
    m = re.search(r'(?is)<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', html or "")
    if not m:
        return {}
    try:
        return json.loads(m.group(1))
    except ValueError:
        return {}


def deep_find(obj, pred, limit=5000):
    """Walk a nested JSON blob and yield every dict matching `pred`. Used to locate job
    arrays inside __NEXT_DATA__/Nuxt payloads without hardcoding their (unstable) paths."""
    out, stack, n = [], [obj], 0
    while stack and n < limit:
        cur = stack.pop()
        n += 1
        if isinstance(cur, dict):
            if pred(cur):
                out.append(cur)
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)
    return out


# ── fetching ─────────────────────────────────────────────────────────────────
class FetchError(RuntimeError):
    pass


def http_get(url, headers=None, timeout=30, data=None):
    """Plain GET returning decoded text. Handles gzip/deflate + charset fallback.

    `data` (a dict) switches the call to a JSON POST — some job APIs are POST-only
    (jooble posts its whole query as a JSON body). GET stays the default and is unchanged.
    """
    h = {"User-Agent": UA, "Accept-Language": "en-GB,en;q=0.9",
         "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
         "Accept-Encoding": "gzip, deflate"}
    h.update(headers or {})
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        h.setdefault("Content-Type", "application/json")
    req = Request(url, data=body, headers=h)
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            enc = (resp.headers.get("Content-Encoding") or "").lower()
    except HTTPError as e:
        raise FetchError(f"HTTP {e.code}") from e
    except (URLError, OSError, ValueError) as e:
        raise FetchError(str(e)) from e
    if enc == "gzip":
        try:
            raw = gzip.decompress(raw)
        except (OSError, zlib.error):
            pass
    elif enc == "deflate":
        try:
            raw = zlib.decompress(raw)
        except zlib.error:
            try:
                raw = zlib.decompress(raw, -zlib.MAX_WBITS)
            except zlib.error:
                pass
    return raw.decode("utf-8", errors="replace")


def cfx_get(url, wait=5):
    """Render a URL in camofox and return its HTML.

    ⚠️ Uses the open-tab(about:blank) + EXPLICIT nav recipe — `open_tab("<url>")`'s
    auto-navigate silently never fires (SKILL.md's documented false-'external-route' trap).
    """
    import cfx
    cfx.ensure_tab()
    cfx.navigate(url)
    time.sleep(wait)
    html = cfx.evaluate("document.documentElement.outerHTML")
    if not isinstance(html, str) or len(html) < 200:
        raise FetchError("cfx render empty (backend degraded? re-check tab health)")
    return html


def _cfx_available():
    return bool(os.environ.get("CFX_KEY"))


def fetch_page(board, url, data=None):
    """Fetch one page per the board's strategy. Raises FetchError.

    `data` is the JSON body for POST-based APIs (see Board.body); it is meaningless for the
    cfx path, which can only navigate.
    """
    mode = board.fetch
    if mode == "http":
        return http_get(url, board.headers, data=data)
    if mode == "cfx":
        return cfx_get(url, board.render_wait)
    # auto: prefer plain HTTP (fast, browser-free); fall back to camofox when walled.
    try:
        txt = http_get(url, board.headers, data=data)
        if len(txt) > 1000:
            return txt
        err = "response too small"
    except FetchError as e:
        err = str(e)
    if _cfx_available():
        return cfx_get(url, board.render_wait)
    raise FetchError(f"{err}; no CFX_KEY for browser fallback")


# ── the runner ───────────────────────────────────────────────────────────────
def parse_args(argv):
    args = list(argv)

    def opt(name, default=None):
        if name in args:
            i = args.index(name)
            if i + 1 < len(args):
                return args[i + 1]
        return default

    def intopt(name, default):
        try:
            return max(1, int(opt(name, str(default))))
        except (TypeError, ValueError):
            return default

    return {
        "nav": opt("--nav"),
        "what": opt("--what"),
        "where": opt("--where"),
        "pages": intopt("--pages", 1),
        "all": "--all" in args or "--all-pages" in args,
        "force": "--force" in args or "--all" in args,
        "raw": args,
    }


def run(board, argv=None):
    """Execute one sourcing pass for `board`. Returns a process exit code."""
    a = parse_args(argv if argv is not None else sys.argv[1:])

    missing = board.needs()
    if missing:
        print(f"ERROR: {missing}", file=sys.stderr)
        return 2

    nav = a["nav"]
    what = a["what"] or (board.query_from_nav(nav) if (board.query_from_nav and nav)
                         else query_param(nav, "q", "what", "keywords", "query", "search", "k"))
    where = a["where"] or query_param(nav, "where", "w", "location", "l") or board.default_where

    query = board_cooldown.query_from_url(nav) if nav else ""
    query = query or what or board.board

    # COOLDOWN GATE — bail before any network cost when this board+query was proven dry.
    if not a["force"]:
        rem = board_cooldown.remaining_hours(board.board, query)
        if rem > 0:
            print("[]")
            print(f"\nCOOLDOWN: {board.board}/{query!r} confirmed exhausted ({rem:.1f}h "
                  f"remaining). Skipped WITHOUT re-fetching. --force to override.",
                  file=sys.stderr)
            return 1

    ctx = {"what": what, "where": where, "base": board.base, "nav": nav, "board": board.board}

    pool = {}
    for page in range(1, a["pages"] + 1):
        url = nav if (nav and page == 1) else board.search_url(what, where, page)
        if not url:
            break
        try:
            text = fetch_page(board, url, board.body(what, where, page) if board.body else None)
        except FetchError as e:
            if page == 1:
                print(f"ERROR: {board.name} fetch failed: {e}", file=sys.stderr)
                return 2
            print(f"WARN: {board.name} page {page} fetch failed: {e}", file=sys.stderr)
            break
        except Exception as e:                                    # cfx.CfxError etc.
            if page == 1:
                print(f"ERROR: {board.name} fetch failed: {e}", file=sys.stderr)
                return 2
            break

        try:
            rows = board.parse(text, ctx) or []
        except Exception as e:
            print(f"ERROR: {board.name} parse failed on page {page}: {e}", file=sys.stderr)
            return 2

        before = len(pool)
        for raw in rows:
            try:
                n = board.normalize(raw, ctx)
            except Exception:
                continue
            if n and n.get("id") and n["id"] not in pool:
                n.setdefault("source", board.board)
                pool[n["id"]] = n
        # Stop paginating once a page adds nothing new or is short. `sparse` boards opt out
        # of the first rule: their pages can normalise to zero keepers and still be followed
        # by pages that don't (client-side eligibility filtering), so only a SHORT raw page
        # (below) proves the result set is exhausted.
        if len(pool) == before and not board.sparse:
            break
        if board.per_page and len(rows) < board.per_page:
            break
        if page < a["pages"]:
            time.sleep(1)

    all_jobs = list(pool.values())
    if a["all"]:
        jobs = all_jobs
    else:
        seen = load_seen(board.seen_pattern, tracker=TRACKER) if board.seen_pattern else set()
        jobs = [j for j in all_jobs if j["id"] not in seen]
    filtered = len(all_jobs) - len(jobs)

    track = not a["all"]
    if track:
        board_cooldown.record_yield(board.board, query, len(jobs))

    print(json.dumps(jobs, ensure_ascii=False, indent=2))
    if jobs:
        print(f"\n{len(jobs)} FRESH {board.name} jobs ({filtered} already tracked, filtered). "
              f"{board.apply_hint}", file=sys.stderr)
    else:
        marked = ""
        if track and all_jobs:
            hrs = board_cooldown.adaptive_hours(board.board, query)
            until = board_cooldown.mark(board.board, query, hrs)
            marked = f" Auto-marked {board.board}/{query!r} cooldown until {until} ({hrs:.0f}h)."
        print(f"\nEXHAUSTED: all {len(all_jobs)} {board.name} results for {query!r} already "
              f"tracked.{marked}", file=sys.stderr)
    return 0 if jobs else 1


def main(board):
    """Entry point with the standard stage timer wrapper."""
    try:
        import stagetimer
        _src = stagetimer.timed("source")
    except Exception:
        import contextlib
        _src = contextlib.nullcontext()
    with _src:
        return run(board)
