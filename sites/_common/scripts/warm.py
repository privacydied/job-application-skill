#!/usr/bin/env python3
"""
warm.py — speculative page-warming: overlap browser page-load latency UNDER the
model-compute phase (speed lever #2).

THE INSIGHT. SKILL.md step 4 (tailor résumés + write cover letters) is pure
model-compute — the browser sits completely idle the whole time. Meanwhile step
5 (`atsform.py apply`) will, per posting, pay the full cost of navigating to that
posting's apply form and waiting for it to render before a single field can be
filled. That page-load latency is dead wall-clock stacked AFTER the compute
phase. This script spends the otherwise-idle browser time DURING compute: it
pre-opens each apply URL in its own background tab so, by the time fills start,
the page is already loaded and `atsform.py` just points CFX_TAB at the warm tab.

It costs nothing you weren't already spending (the browser was idle) and adds NO
detection risk: each page gets a paced navigate with a real referer chain
(cfx.navigate) — a human's per-tab random `human_pause` naturally staggers the
loads, exactly like middle-clicking a few search results. The tabs warm
CONCURRENTLY (threads): wall-clock is the SLOWEST single page-load, not the sum,
so a large work list still fits under one compute turn. Tab CREATION is
serialized (open_tab's flaky-500 list-diff recovery isn't thread-safe); only the
slow navigate+settle overlaps. Cap keeps it sane (default 8 tabs).

USAGE
  # 1) BEFORE the tailor/compute turn — warm every apply URL in the work list:
  CFX_KEY=… python3 warm.py open urls.txt        # file: one apply URL per line
  CFX_KEY=… feed→precheck→... | python3 warm.py open -     # or stdin
  CFX_KEY=… python3 warm.py open <url1> <url2> …           # or inline args
      -> opens background tabs, writes warm-map.json {url: tabId}, prints a summary.
         On Claude Code, launch this in a background Bash right before step 4 so it
         overlaps the writing; on Hermes (no subagents) run it as its own step
         immediately before step 4 — the tabs keep loading while the model writes.

  # 2) In step 5, per posting — point atsform at the pre-warmed tab:
  export CFX_TAB="$(python3 warm.py lookup "<apply url>")"   # empty => not warmed
  python3 atsform.py apply applications/<dir>/apply.json     # page already loaded

  # 3) After the run (or if warming a stale set) — reclaim the tabs:
  python3 warm.py close        # closes every tab in warm-map.json, clears the map

OPTIONS (open): --cap N (default 8), --map <path> (default <skillroot>/warm-map.json),
                --settle S (per-tab post-nav readyState wait cap, default 8s)

NOTES
  * Warming is best-effort: a URL that fails to open is recorded with an error and
    the rest still warm. `lookup` on an unknown/failed URL prints nothing (empty),
    so step 5 falls back to a normal cold `atsform` nav — warming is a pure
    optimisation, never a dependency.
  * The map is keyed by the EXACT url string you pass; pass step 5 the same string.
  * Tabs live under listItemId "job-apply" (same session as the main loop). `close`
    never touches a tab that isn't in the map, so the live loop tab is safe.
"""
import json
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cfx  # noqa: E402

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
DEFAULT_MAP = os.path.join(_ROOT, "warm-map.json")
DEFAULT_CAP = 8


def _read_urls(srcs):
    """URLs from inline args, a file, or '-' (stdin). One per line for files/stdin;
    blanks and #-comments ignored; de-duplicated preserving order."""
    raw_lines = []
    for s in srcs:
        if s == "-":
            raw_lines.extend(sys.stdin.read().splitlines())
        elif os.path.exists(s):
            with open(s, encoding="utf-8") as f:
                raw_lines.extend(f.read().splitlines())
        else:
            raw_lines.append(s)  # treat as a literal URL
    seen, urls = set(), []
    for line in raw_lines:
        u = line.strip()
        if not u or u.startswith("#"):
            continue
        if u not in seen:
            seen.add(u); urls.append(u)
    return urls


def _load_map(path):
    try:
        with open(path, encoding="utf-8") as f:
            m = json.load(f)
        return m if isinstance(m, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_map(path, m):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(m, f, indent=1)
    os.replace(tmp, path)


def cmd_open(urls, map_path, cap, settle):
    if not urls:
        print("warm open: no URLs given.", file=sys.stderr)
        return 1
    if len(urls) > cap:
        print(f"warm: {len(urls)} URLs given, capping at {cap} (raise with --cap).",
              file=sys.stderr)
        urls = urls[:cap]
    warm = _load_map(map_path)  # merge, so a second `open` adds to the set
    todo = [u for u in urls if u not in warm]
    reused = len(urls) - len(todo)
    opened_urls, failed = [], []
    open_lock = threading.Lock()   # serialize the race-prone tab CREATE only
    state_lock = threading.Lock()  # guard the shared result dicts

    def _warm_one(u):
        try:
            with open_lock:
                tab = cfx.open_tab("about:blank")        # blank first, then paced nav
            cfx.navigate(u, timeout=60, tab=tab)         # referer chain + human_pause
            # brief settle so the load actually starts under our idle window; don't
            # block long — the point is to OVERLAP compute, not to fully await render.
            # Runs concurrently across tabs, so this wait overlaps the others'.
            cfx.poll("document.readyState", predicate=lambda r: r == "complete",
                     timeout=float(settle), tab=tab)
            with state_lock:
                warm[u] = tab
                opened_urls.append(u)
            print(f"  warm  {tab}  {u}", file=sys.stderr)
        except Exception as e:  # noqa: BLE001 — a non-CfxError (JSON/transport) used to kill the
            # worker thread and drop the URL from BOTH warm-map and `failed`, so cmd_open still
            # returned 0 while silently under-warming. Record every failure so the summary is honest.
            with state_lock:
                failed.append(u)
            print(f"  FAIL  {u}  ({e})", file=sys.stderr)

    workers = [threading.Thread(target=_warm_one, args=(u,), name=f"warm-{i}")
               for i, u in enumerate(todo)]
    for t in workers:
        t.start()
    for t in workers:
        t.join()
    opened, errors = len(opened_urls), len(failed)
    _save_map(map_path, warm)
    print(json.dumps(warm, indent=1))
    print(f"warm: {opened} opened, {reused} already-warm, {errors} failed; "
          f"map -> {map_path}", file=sys.stderr)
    return 0 if errors == 0 else 1


def cmd_lookup(url, map_path):
    tab = _load_map(map_path).get(url, "")
    if tab:
        print(tab)          # stdout: consumable by `export CFX_TAB=$(warm.py lookup …)`
        return 0
    return 1                # nonzero + empty stdout => caller cold-navs as usual


def cmd_close(map_path):
    warm = _load_map(map_path)
    if not warm:
        print("warm close: nothing to close (empty/absent map).", file=sys.stderr)
        return 0
    closed = 0
    for u, tab in warm.items():
        cfx.close_tab(tab)  # idempotent server-side
        closed += 1
        print(f"  close {tab}  {u}", file=sys.stderr)
    try:
        os.remove(map_path)
    except OSError:
        pass
    print(f"warm: closed {closed} tab(s), cleared {map_path}", file=sys.stderr)
    return 0


def main():
    a = sys.argv[1:]
    if not a:
        print(__doc__)
        return 1
    cmd, rest = a[0], a[1:]
    map_path, cap, settle = DEFAULT_MAP, DEFAULT_CAP, 8
    srcs = []
    i = 0
    while i < len(rest):
        if rest[i] == "--map" and i + 1 < len(rest):
            map_path = rest[i + 1]; i += 2
        elif rest[i] == "--cap" and i + 1 < len(rest):
            cap = int(rest[i + 1]); i += 2
        elif rest[i] == "--settle" and i + 1 < len(rest):
            settle = float(rest[i + 1]); i += 2
        else:
            srcs.append(rest[i]); i += 1

    try:
        if cmd == "open":
            return cmd_open(_read_urls(srcs), map_path, cap, settle)
        if cmd == "lookup" and len(srcs) == 1:
            return cmd_lookup(srcs[0], map_path)
        if cmd == "close":
            return cmd_close(map_path)
    except cfx.CfxError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
