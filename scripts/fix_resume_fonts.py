#!/usr/bin/env python3
"""fix_resume_fonts.py — make a Google-Docs-export resume HTML self-contained.

The resumes rely on `@import url(https://themes.googleusercontent.com/fonts/css?kit=…)` for
Raleway/Lato/Roboto Mono. That kit is flaky: it doesn't reliably load, so any offline view or
HTML→PDF conversion falls back to plain system fonts ("lost styling"). This swaps that broken
import for base64-embedded @font-face rules (scripts/resume-fonts-embedded.css) — zero network,
so the resume looks identical in any browser AND when printed to PDF from a browser.

Usage: python3 scripts/fix_resume_fonts.py <file-or-glob> [...]   (edits in place; idempotent)
"""
import sys, os, glob, re
HERE = os.path.dirname(os.path.abspath(__file__))
FONTS = open(os.path.join(HERE, "resume-fonts-embedded.css"), encoding="utf-8").read()
MARK = "/* self-contained-fonts */"
IMPORT_RE = re.compile(r"@import url\(https://themes\.googleusercontent\.com[^;]*;")

def fix(path):
    html = open(path, encoding="utf-8").read()
    if MARK in html:
        return "already-embedded"
    if not IMPORT_RE.search(html):
        return "no-themes-import (skipped)"
    html = IMPORT_RE.sub(MARK + FONTS, html, count=1)
    open(path, "w", encoding="utf-8").write(html)
    return "FIXED"

if __name__ == "__main__":
    # generic globs (no personal filename — keeps this tool PII-free / committable)
    args = sys.argv[1:] or ["*resume*.html", "applications/*/resume.html",
                            "applications/_bases/*/resume.html"]
    paths = []
    for a in args:
        paths += glob.glob(a) if any(c in a for c in "*?[") else [a]
    for p in paths:
        if os.path.isfile(p):
            print(f"{fix(p):32} {p}")
