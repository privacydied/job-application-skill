#!/usr/bin/env python3
"""
nav_to_link.py — navigate straight to a link-like element's `href` instead of
clicking it.

ROOT CAUSE (confirmed 2026-07-11 on a Lloyds Workday posting): Workday's "Apply"
control is a real `<a role="button" href="...">`, not a `<button>`. Workday's
job page also renders an async sidebar of "related jobs" cards that mount/shift
near it. Both `click` by a11y ref/CSS-selector AND a direct JS `element.click()`
reliably fail to navigate — `location.href` never changes, because Workday's SPA
router intercepts the click without acting on it in this automated context (or
the click lands on the async-shifting sidebar by the time the event fires).

THE FIX: skip clicking entirely. The `<a>`'s `href` is a real, directly-navigable
URL (Workday routes are plain URLs, e.g. `.../job/London/UX-Designer_160015-1/apply`).
Read the href off the matching element and navigate the tab there directly.

Usage:
    CFX_KEY=... CFX_TAB=... python3 nav_to_link.py "<link text substring>"

Improvements over the old version:
  * Routes through the shared cfx.navigate(), so the navigation carries a
    realistic **Referer (the current posting page)** and human pacing — a direct
    nav to an /apply URL with an empty Referer is a bot tell (see cfx.sh's
    "Referer chains" note). This is exactly the deep-link case that matters.
  * If more than one distinct link matches the text, it does NOT silently take
    the first — it prints all candidates and picks the first, so a wrong match
    (e.g. "Apply" also matching "Apply on company website") is visible.
  * Polls for the URL to actually change instead of a blind fixed sleep.

Prints the href found and the URL after navigating, so you can confirm it landed
on the expected apply-flow page (e.g. "Start Your Application" / "Autofill with
Resume" / "Apply Manually").
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "_common", "scripts"))
import cfx  # noqa: E402


def find_hrefs(text: str):
    expr = f"""
    (() => {{
      const want = {json.dumps(text)};
      const els = [...document.querySelectorAll('a[href]')]
        .filter(x => x.textContent.trim().includes(want));
      return [...new Set(els.map(x => x.href))];
    }})()
    """
    r = cfx.evaluate(expr)
    return r if isinstance(r, list) else []


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    text = sys.argv[1]

    try:
        before = cfx.current_url()
        hrefs = find_hrefs(text)
        if not hrefs:
            print("Link not found on the current page — re-snapshot and check for a different "
                  "label, or confirm the element is actually an <a> (not a <button>).")
            sys.exit(1)
        if len(hrefs) > 1:
            print(f"NOTE: {len(hrefs)} links matched {text!r}; using the first. "
                  f"Candidates: {json.dumps(hrefs, ensure_ascii=False)}")
        href = hrefs[0]
        print("locate:", href)

        # cfx.navigate auto-sets Referer to the current posting page (the page
        # we found the link on) — the realistic click-through chain.
        print("nav:", cfx.navigate(href))

        after = cfx.poll(
            "location.href",
            predicate=lambda u: isinstance(u, str) and u.rstrip("/") != before.rstrip("/"),
            timeout=8.0,
        )
        print("post-nav URL:", after)
        if isinstance(after, str) and after.rstrip("/") == before.rstrip("/"):
            print("WARNING: URL did not change — the navigation may not have landed.")
            sys.exit(1)
    except cfx.CfxError as e:
        print(f"ERROR: {e}")
        sys.exit(2)


if __name__ == "__main__":
    main()
