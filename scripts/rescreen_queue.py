#!/usr/bin/env python3
"""rescreen_queue.py — finish screening queue rows left past pipeline --screen-limit,
and optionally remove rows the apply lane must not touch. Uses the shipped primitives.

Usage (needs a live camofox tab: source .jobenv.run first):
  python3 scripts/rescreen_queue.py                      # just finish the capped rows
  python3 scripts/rescreen_queue.py --drop-greenhouse --drop-non-uk

Never hand-roll a JD scraper here: jd.screen_one is the canonical screen+extract step.
"""
import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMMON = os.path.join(ROOT, "sites", "_common", "scripts")
sys.path.insert(0, COMMON)
import fit_score  # noqa: E402
import fsutil  # noqa: E402
import jd  # noqa: E402

DEFAULT_QUEUE = os.path.join(ROOT, "queue.jsonl")
NON_UK = re.compile(
    r"(?i)\b(united states|usa|u\.s\.|us|india|ireland|germany|mexico|canada|"
    r"china|singapore|apac|amer|americas|shenzhen|ohio|pennsylvania|pa)\b"
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", default=DEFAULT_QUEUE)
    ap.add_argument("--drop-greenhouse", action="store_true",
                    help="exclude Greenhouse rows when the user is skipping emailed-code ATS")
    ap.add_argument("--drop-non-uk", action="store_true",
                    help="exclude region-restricted remote roles outside the UK")
    args = ap.parse_args()

    rows = [json.loads(line) for line in open(args.queue, encoding="utf-8") if line.strip()]
    before = len(rows)
    kept, otp, geo = [], 0, 0
    for r in rows:
        if args.drop_greenhouse and r.get("ats_hint") == "greenhouse":
            otp += 1
            continue
        if args.drop_non_uk and (NON_UK.search(r.get("location") or "")
                                 or "non-uk" in (r.get("verdict_reason") or "").lower()):
            geo += 1
            continue
        kept.append(r)

    n_screened = n_errors = 0
    for r in kept:
        if r.get("jd") is not None or r.get("screen_skipped") != "screen-limit":
            continue
        url = r.get("url")
        if not url:
            continue
        try:
            data = jd.screen_one(url)
            if not data.get("error") and (data.get("jd_text_full_len") or 0) < 300:
                data = jd.screen_one(url, use_cache=False)
            if data.get("error"):
                r["jd_error"] = str(data["error"])
                n_errors += 1
            else:
                r["jd"] = jd.compact(data)
                r["jd_error"] = None
                n_screened += 1
            r["screen_skipped"] = None
        except Exception as exc:  # noqa: BLE001 - one bad posting must not sink the batch
            r["jd_error"] = str(exc)
            n_errors += 1
        r["fit_score"] = fit_score.fit_row(r)

    for r in kept:
        if r.get("fit_score") is None:
            r["fit_score"] = fit_score.fit_row(r)

    def _write(f):
        for r in kept:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    with fsutil.file_lock(args.queue):
        fsutil.atomic_write(args.queue, _write)

    print(json.dumps({
        "before": before,
        "greenhouse_dropped": otp,
        "non_uk_dropped": geo,
        "screened_now": n_screened,
        "screen_errors": n_errors,
        "final_queue": len(kept),
        "still_unscreened": sum(r.get("jd") is None for r in kept),
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
