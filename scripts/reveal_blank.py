#!/usr/bin/env python3
"""reveal_blank.py — recover title/company for LinkedIn result cards that
feed.py returned with blank title/company (a LinkedIn virtualization quirk: the
list card renders with no inner text even though the JD exists). Navigates each
JD page and reads the first two lines of the job-detail <main>/<article> text
(line 0 = company, line 1 = title). Note: the top-card selector
`.jobs-unified-top-card__job-title` ALSO misses these same cards, so read
`main`/`article` instead. See references/linkedin-blank-title-recovery.md.

Usage (from the skill root):
    CFX_KEY=... CFX_TAB=... python3 scripts/reveal_blank.py <id> [<id> ...]
Prints:  <id>  |  <company>  |  <title>
"""
import os
import sys
import time

_here = os.path.dirname(os.path.abspath(__file__))
_skill_root = os.path.dirname(_here)
for _p in (
    os.path.join(_skill_root, "sites", "_common", "scripts"),
    os.path.join(_skill_root, "_common", "scripts"),
):
    if os.path.isdir(_p):
        sys.path.insert(0, _p)
import cfx  # noqa: E402


def reveal(jid):
    url = f"https://www.linkedin.com/jobs/view/{jid}/"
    cfx.navigate(url)
    time.sleep(2.5)
    txt = cfx.evaluate(
        "(()=>{const m=document.querySelector('main, .jobs-details, article'); "
        "return m ? m.innerText : '';})()"
    ) or ""
    lines = [l.strip() for l in txt.split("\n") if l.strip()]
    company = lines[0] if len(lines) > 0 else "(unknown)"
    title = lines[1] if len(lines) > 1 else "(unknown)"
    return company, title


def main():
    ids = sys.argv[1:]
    if not ids:
        print("usage: reveal_blank.py <id> [<id> ...]")
        return 2
    for jid in ids:
        try:
            c, t = reveal(jid)
            print(f"{jid}  |  {c}  |  {t}")
        except cfx.CfxError as e:
            print(f"{jid}  |  ERROR  |  {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
