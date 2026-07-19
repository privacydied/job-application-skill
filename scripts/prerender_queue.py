#!/usr/bin/env python3
"""
prerender_queue.py — pre-render the per-family resume bases OFF the apply hot path (async
compute overlap). Run by cron alongside warm_queue.py (code only, no model, no camofox).

WHY THIS EXISTS. PDF render is pure, deterministic wall-clock (serve HTML on the LAN, drive
the Playwright container, verify the text extracts — several seconds each). It is a DIFFERENT
resource from the single anti-detection camofox tab, so it can run in parallel with the
browser apply loop and between firings. Tailoring a posting starts from its family base
(pipeline.py stamps `family` on every queue row) plus ~3 company subs; if that family's base
HTML has no rendered PDF yet, the first application in that family pays the render on the
critical path. This warms every family present in the current queue so:
  * the render step is off the per-application critical path for the common case, and
  * a set-and-forget fallback exists: if a tailoring turn is ever skipped, every family has a
    ready, correctly-positioned base resume.pdf to submit as-is.

It is idempotent and cheap: it only (re)renders a family base whose resume.pdf is missing or
older than its resume.html, and it renders them all in ONE parallel pass (prerender-pdfs.sh).

  --stage   ALSO pre-stage each queued row's applications/<slug>/ dir with the family base
            resume.html + resume.pdf as a fallback (skips any dir that already has a
            resume.pdf). Tailoring still overwrites these with the company-tailored version;
            this just guarantees a submittable artifact exists even before/without tailoring.

Needs NO camofox tab (render runs on the Playwright container, a separate resource), so it
never contends with the apply loop and needs no CFX_KEY / .jobenv in its cron line.

CRON (hourly at :20 — after warm_queue.py's :00 pass has refreshed queue.jsonl):
  20 * * * * cd /…/job-application && python3 scripts/prerender_queue.py \
             >> prerender-queue.log 2>&1

Usage: prerender_queue.py [--stage] [--queue path] [--limit N]
"""
import json
import os
import shutil
import subprocess
import sys

_here = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_here)
_COMMON = os.path.join(_ROOT, "sites", "_common", "scripts")
sys.path.insert(0, _COMMON)

import journal  # noqa: E402  — slugify (same applications/<slug>/ convention as the loop)

QUEUE = os.path.join(_ROOT, "queue.jsonl")
BASES = os.path.join(_ROOT, "applications", "_bases")
APPS = os.path.join(_ROOT, "applications")
PRERENDER = os.path.join(_COMMON, "prerender-pdfs.sh")
TAILOR = os.path.join(_COMMON, "tailor.py")


def _read_queue(path):
    rows = []
    try:
        with open(path, encoding="utf-8") as f:
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


def _needs_render(app_dir):
    """True if <app_dir>/resume.html exists but resume.pdf is missing or stale."""
    html = os.path.join(app_dir, "resume.html")
    pdf = os.path.join(app_dir, "resume.pdf")
    if not os.path.isfile(html):
        return False
    if not os.path.isfile(pdf):
        return True
    try:
        return os.path.getmtime(pdf) < os.path.getmtime(html)
    except OSError:
        return True


def _ensure_bases():
    """Build applications/_bases/<family>/ if it's missing/empty (tailor.py build-bases is
    the single source of truth for the derived bases). Best-effort; returns True if bases
    exist afterwards."""
    have = os.path.isdir(BASES) and any(
        os.path.isfile(os.path.join(BASES, d, "resume.html"))
        for d in os.listdir(BASES) if os.path.isdir(os.path.join(BASES, d)))
    if have:
        return True
    try:
        subprocess.run([sys.executable, TAILOR, "build-bases"],
                       cwd=_ROOT, timeout=120, capture_output=True)
    except (subprocess.SubprocessError, OSError):
        pass
    return os.path.isdir(BASES)


def _render(dirs):
    """Render every <dir>/resume.html -> resume.pdf in ONE parallel pass. Returns rc."""
    if not dirs:
        return 0
    try:
        p = subprocess.run([PRERENDER] + dirs, cwd=_ROOT, timeout=600)
        return p.returncode
    except (subprocess.SubprocessError, OSError) as e:
        print(f"prerender_queue: render pass failed: {e}", file=sys.stderr)
        return 1


def main():
    argv = sys.argv[1:]
    stage = "--stage" in argv
    qpath = QUEUE
    if "--queue" in argv:
        i = argv.index("--queue")
        if i + 1 < len(argv):
            qpath = argv[i + 1]
    limit = None
    if "--limit" in argv:
        i = argv.index("--limit")
        if i + 1 < len(argv) and argv[i + 1].isdigit():
            limit = int(argv[i + 1])

    rows = _read_queue(qpath)
    if not rows:
        print("prerender_queue: queue empty — nothing to pre-render.")
        return 0
    if not _ensure_bases():
        print("prerender_queue: no family bases (family-bases.json missing?) — skipping.")
        return 0

    families = []
    for r in rows:
        fam = r.get("family")
        if fam and fam not in families:
            families.append(fam)

    # 1) render each queued family's BASE pdf if missing/stale
    base_dirs = []
    for fam in families:
        d = os.path.join(BASES, fam)
        if _needs_render(d):
            base_dirs.append(d)
    if base_dirs:
        print(f"prerender_queue: rendering {len(base_dirs)} family base(s): "
              f"{', '.join(os.path.basename(d) for d in base_dirs)}")
        _render(base_dirs)
    else:
        print(f"prerender_queue: all {len(families)} queued family base(s) already rendered.")

    if not stage:
        return 0

    # 2) --stage: pre-seed each queued row's app dir with its family base (fallback artifact)
    staged = []
    for r in rows[: limit or len(rows)]:
        fam = r.get("family")
        slug = journal.slugify(r.get("company", ""), r.get("title", ""))
        if not fam or not slug:
            continue
        app_dir = os.path.join(APPS, slug)
        if os.path.isfile(os.path.join(app_dir, "resume.pdf")):
            continue  # already has an artifact (tailored or previously staged) — leave it
        base_dir = os.path.join(BASES, fam)
        base_html = os.path.join(base_dir, "resume.html")
        base_pdf = os.path.join(base_dir, "resume.pdf")
        if not os.path.isfile(base_html):
            continue
        try:
            os.makedirs(app_dir, exist_ok=True)
            if not os.path.isfile(os.path.join(app_dir, "resume.html")):
                shutil.copyfile(base_html, os.path.join(app_dir, "resume.html"))
            if os.path.isfile(base_pdf):
                shutil.copyfile(base_pdf, os.path.join(app_dir, "resume.pdf"))
            staged.append(slug)
        except OSError:
            continue
    print(f"prerender_queue: staged {len(staged)} app dir(s) with a family-base fallback"
          + (f" (e.g. {staged[0]})" if staged else "") + ".")
    return 0


if __name__ == "__main__":
    sys.exit(main())
