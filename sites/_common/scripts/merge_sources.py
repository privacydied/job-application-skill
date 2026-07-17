#!/usr/bin/env python3
"""
merge_sources.py — merge several feed.py JSON outputs into ONE deduped candidate list.

Promoted from a Hermes run's /tmp/li_queue.py (2026-07-14) — but reduced to its
reusable kernel. The original also carried session-specific junk that does NOT
belong in the skill and is deliberately dropped here:
  - hardcoded /tmp input paths            -> now positional file args
  - a frozen set of already-attempted ids -> use --drop-tracked (the live tracker)
  - inline SENIOR/AGENCY/KEEP regexes     -> that is precheck.py's job; run the
                                             merged list through precheck/jd, don't
                                             fork the screening logic here.
This tool does exactly one thing: combine + dedupe (and optionally drop rows the
tracker already has). Screening stays in precheck.py; sourcing stays in feed.py.

Why it exists: a sourcing run often makes several feed.py passes (multiple boards,
or repeated LinkedIn passes after clearing board-cooldown) and there was no
first-class "merge the batches" step — people hand-rolled it each time.

Usage:
    merge_sources.py <feed1.json> [feed2.json ...] [--drop-tracked]
                     [--tracker <path>] [-o <out.json>]

Each input file may be either a JSON list of postings, or a dict of
{board: [postings]} / {candidates: [...]} (feed harvesters write both shapes) —
both are flattened. A leading non-JSON status line (Indeed's feed.py, or the
`NN FRESH jobs…` banner) is stripped before parsing so those files still merge.
Dedupe key = precheck.canon_ids(url) (board-agnostic stable id), falling back to
the posting's `id` / url tail when a URL yields no canonical id. With
--drop-tracked, any posting whose canonical id OR (company,role) already appears
in application-tracker.csv is removed — the SAME keys the rest of the pipeline
dedupes on (precheck.load_tracker), not a substring hack.

Output: merged JSON list to -o (default: stdout). A count summary goes to stderr.
Exit codes: 0 ok · 2 bad input/IO.
"""
import csv
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from precheck import canon_ids, load_tracker, _norm  # noqa: E402


def _tracker_maps(tracker):
    """(id set, (company,role) set) for --drop-tracked. Uses precheck.load_tracker
    for the default tracker; for an explicit --tracker path, build the same maps
    with the SAME primitives (canon_ids/_norm) rather than forking the logic."""
    if tracker is None:
        id_map, pair_map = load_tracker()
        return set(id_map), set(pair_map)
    ids, pairs = set(), set()
    try:
        with open(tracker, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if not (row.get("Status") or "").strip():
                    continue
                ids |= canon_ids(row.get("URL") or "")
                pair = (_norm(row.get("Company")), _norm(row.get("Role")))
                if pair[0] and pair[1]:
                    pairs.add(pair)
    except (OSError, csv.Error) as e:
        print(f"WARN: --tracker {tracker!r} unreadable: {e}", file=sys.stderr)
    return ids, pairs


def _flatten(obj):
    """A feed file is a list of postings, or {board: [postings], ...}. Yield postings."""
    if isinstance(obj, list):
        for x in obj:
            if isinstance(x, dict):
                yield x
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _flatten(v)


def _keys(post):
    """Dedupe keys for a posting: canonical ids if the URL yields any, else a
    single fallback (explicit id, or the last url path segment)."""
    url = (post.get("url") or "").strip()
    ids = canon_ids(url) if url else set()
    if ids:
        return ids
    fb = post.get("id")
    if fb is None and url:
        fb = url.rstrip("/").split("/")[-1]
    return {str(fb)} if fb not in (None, "") else set()


def _load_tolerant(path):
    """Parse a feed file, tolerating a leading non-JSON prefix line. Some feeds
    (notably Indeed's feed.py, and the `NN FRESH jobs…` banner LinkedIn's prints)
    emit a status line BEFORE the JSON array — a bare json.load then fails and the
    whole file would be silently dropped. Fall back to parsing from the first
    '['/'{' so those files still merge. See references/indeed-feed-json-prefix.md."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    try:
        return json.loads(text)
    except ValueError:
        pass
    for br in "[{":
        i = text.find(br)
        if i > 0:
            try:
                return json.loads(text[i:])
            except ValueError:
                continue
    raise ValueError("no JSON array/object found (even after stripping a prefix)")


def load_postings(paths):
    posts = []
    for p in paths:
        try:
            posts.extend(_flatten(_load_tolerant(p)))
        except (OSError, ValueError) as e:
            print(f"WARN: skipping {p!r}: {e}", file=sys.stderr)
    return posts


_CO_SUFFIX_RE = re.compile(
    r"\b(ltd|limited|inc|incorporated|llc|l\.?l\.?c|plc|co|corp|corporation|gmbh|"
    r"group|holdings|uk|global)\b")


def _norm_company(s):
    """Company key with legal-suffix noise stripped so 'Acme Ltd' == 'Acme Limited' ==
    'Acme Ltd UK' (the cross-board dup case). Mirrors company_cache's Ltd/Limited-normalize
    intent, extended to the common suffixes that vary by board."""
    base = _norm(s)                       # lowercase, non-alnum -> space
    base = _CO_SUFFIX_RE.sub(" ", base)
    return " ".join(base.split())


def _location_bucket(loc):
    low = (loc or "").lower()
    if re.search(r"(?<!new )\blondon\b", low):
        return "london"
    if re.search(r"\bremote\b|work from home|anywhere|worldwide", low):
        return "remote"
    return "other" if low else ""


def fingerprint(post):
    """M.2 — a FUZZY cross-board vacancy key: (norm company, norm title, location bucket).
    canon_ids only dedups URL VARIANTS of one board's posting; the SAME vacancy sourced from
    two boards (Reed + Adzuna + LinkedIn) mints three different ids and slips past canon-id
    dedup — a real double-apply risk. Two postings with the same company, same normalized
    title AND same location bucket are almost certainly the same role (distinct SENIORITY
    survives because 'Senior Product Designer' normalizes differently from 'Product Designer').
    Returns None when company or title is missing (can't fingerprint → never collapse)."""
    comp = _norm_company(post.get("company"))
    title = _norm(post.get("title") or post.get("role"))
    if not comp or not title:
        return None
    return (comp, title, _location_bucket(post.get("location")))


def merge_lists(posts, drop_tracked=False, tracker=None, cross_board=False):
    """Dedupe an IN-MEMORY list of postings (C.1: pipeline already holds `all_posts`,
    so serializing it to a tmp file just to read+re-parse it back is pure waste). Same
    kernel as merge(); stashes the canonical-id set on each kept post as `_canon_ids`
    (C.5) so precheck/jd don't re-run the 10-regex sweep on the same URL.

    cross_board=True (M.2) additionally collapses fuzzy cross-board duplicates by
    fingerprint() AFTER canonical-id dedup — the same vacancy reached via two boards is kept
    ONCE, with the other board's URL recorded on the kept post as `_dup_urls` so the tracker
    check still catches 'already applied via the other board'. Off by default to preserve the
    original id-only semantics for existing callers/tests; pipeline enables it."""
    tracked_ids, tracked_pairs = (set(), set())
    if drop_tracked:
        tracked_ids, tracked_pairs = _tracker_maps(tracker)

    seen, out = set(), []
    fp_index = {}          # fingerprint -> kept post (for cross_board collapse)
    n_dupe = n_tracked = n_nokey = n_fuzzy = 0
    for post in posts:
        keys = _keys(post)
        if not keys:
            n_nokey += 1
            continue
        if keys & seen:
            n_dupe += 1
            continue
        if drop_tracked:
            pair = (_norm(post.get("company")), _norm(post.get("role") or post.get("title")))
            if (keys & tracked_ids) or (pair[0] and pair[1] and pair in tracked_pairs):
                seen |= keys
                n_tracked += 1
                continue
        if cross_board:
            fp = fingerprint(post)
            if fp is not None and fp in fp_index:
                # same vacancy already kept from another board — collapse, keep the alt URL
                kept = fp_index[fp]
                alt = (post.get("url") or "").strip()
                if alt and isinstance(kept, dict):
                    kept.setdefault("_dup_urls", [])
                    if alt not in kept["_dup_urls"] and alt != kept.get("url"):
                        kept["_dup_urls"].append(alt)
                seen |= keys
                n_fuzzy += 1
                continue
        seen |= keys
        if isinstance(post, dict):
            post["_canon_ids"] = sorted(keys)  # C.5: reused by precheck + jd cache key
        out.append(post)
        if cross_board:
            fp = fingerprint(post)
            if fp is not None:
                fp_index[fp] = post
    stats = {"in": len(posts), "out": len(out), "dupes": n_dupe,
             "tracked_dropped": n_tracked, "no_key": n_nokey, "fuzzy_dropped": n_fuzzy}
    return out, stats


def merge(paths, drop_tracked=False, tracker=None):
    return merge_lists(load_postings(paths), drop_tracked=drop_tracked, tracker=tracker)


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 2
    drop_tracked = "--drop-tracked" in args

    def opt(flag):
        return args[args.index(flag) + 1] if flag in args and args.index(flag) + 1 < len(args) else None

    out_path = opt("-o")
    tracker = opt("--tracker")
    consumed = {"--drop-tracked", "-o", out_path, "--tracker", tracker}
    files = [a for a in args if a not in consumed and not a.startswith("-")]
    if not files:
        print("FAIL: no input JSON files given", file=sys.stderr)
        return 2

    merged, stats = merge(files, drop_tracked=drop_tracked, tracker=tracker)
    blob = json.dumps(merged, indent=None)
    if out_path:
        try:
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(blob)
        except OSError as e:
            print(f"FAIL: write {out_path!r}: {e}", file=sys.stderr)
            return 2
    else:
        print(blob)
    print(f"MERGED {stats['in']} -> {stats['out']} unique "
          f"(dropped {stats['dupes']} dupes, {stats['tracked_dropped']} already-tracked, "
          f"{stats['no_key']} no-key)"
          + (f" -> {out_path}" if out_path else ""), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
