#!/usr/bin/env python3
"""Regenerate the gitignored application-log markdown from application-tracker.csv.

Writes (both gitignored — they carry the applicant's application history):
  docs/job-application-summary.md      all-time status totals, per-date table,
                                       Applied rows grouped by date
  docs/applied-since-<SINCE>.md        numbered table of Applied rows dated >= SINCE
                                       (tracker order)

Read-only on the tracker. Usage:
  python3 scripts/gen_application_docs.py [--since 2026-09-04]
"""
import argparse
import collections
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRACKER = ROOT / "application-tracker.csv"
DOCS = ROOT / "docs"


def cell(s):
    return (s or "").replace("|", "\\|").replace("\r", " ").replace("\n", " ").strip()


def summary(rows):
    st = collections.Counter(r["Status"] for r in rows)
    by_date = collections.defaultdict(list)
    for r in rows:
        by_date[r["Date"]].append(r)
    dates = sorted(by_date)
    out = [
        "# Job Application Log — Summary by Date",
        "",
        f"_Generated from `application-tracker.csv` — {len(rows)} total tracked rows across {len(dates)} dates._",
        "",
        "## Grand totals (all-time)",
        "",
        "| Status | Count |",
        "|---|---|",
    ]
    for k, v in st.most_common():
        out.append(f"| {k or '(blank)'} | {v} |")
    out += [f"| **Total rows** | **{len(rows)}** |", "",
            f"**Strict `Applied` count: {st['Applied']}**", "", "---", "",
            "## Per-date breakdown", "",
            "| Date | Applied | Skipped | Blocked | Applied? / Other | Total |",
            "|---|---|---|---|---|---|"]
    for d in dates:
        c = collections.Counter(r["Status"] for r in by_date[d])
        other = len(by_date[d]) - c["Applied"] - c["Skipped"] - c["Blocked"]
        out.append(f"| {d or '(no date)'} | {c['Applied']} | {c['Skipped']} | {c['Blocked']} | {other} | {len(by_date[d])} |")
    out += ["", "---", "", "## Detailed log — Applied rows only, grouped by date", "",
            "_(Skipped/Blocked rows are omitted here for brevity — see the per-date table above for their counts, "
            "or `application-tracker.csv` directly for full detail including reasons.)_", ""]
    for d in dates:
        ap = [r for r in by_date[d] if r["Status"] == "Applied"]
        if not ap:
            continue
        out += [f"### {d} — {len(ap)} applied", "", "| Company | Role | Source |", "|---|---|---|"]
        out += [f"| {cell(r['Company'])} | {cell(r['Role'])} | {cell(r['Source'])} |" for r in ap]
        out.append("")
    return "\n".join(out)


def since(rows, since_date):
    ap = [r for r in rows if r["Status"] == "Applied" and r["Date"] >= since_date]
    out = ["| # | Date | Company | Role | Source | URL |", "|---|---|---|---|---|---|"]
    out += [f"| {i} | {r['Date']} | {cell(r['Company'])} | {cell(r['Role'])} | {cell(r['Source'])} | {cell(r['URL'])} |"
            for i, r in enumerate(ap, 1)]
    return "\n".join(out) + "\n", len(ap)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-09-04")
    a = ap.parse_args()
    with open(TRACKER, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    DOCS.mkdir(exist_ok=True)
    (DOCS / "job-application-summary.md").write_text(summary(rows), encoding="utf-8")
    text, n = since(rows, a.since)
    (DOCS / f"applied-since-{a.since}.md").write_text(text, encoding="utf-8")
    print(f"summary: {len(rows)} rows; applied-since-{a.since}: {n} rows")


if __name__ == "__main__":
    main()
