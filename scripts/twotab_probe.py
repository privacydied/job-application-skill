#!/usr/bin/env python3
"""
twotab_probe.py — a BOUNDED, guarded experiment: does ONE process interleaving exactly
TWO tabs trip the camofox wedge? (Tier-3, explicitly risky.)

The documented wedge (references/camofox-concurrent-tab-wedge.md) came from MULTIPLE
processes each opening tabs, hitting ~10 live tabs -> POST /tabs 500 / navigate 410/404.
The one-tab rule was written from that. But 2-tabs-in-1-process (a 'source' tab and an
'apply' tab, interleaved) is UNTESTED — and if stable it could roughly halve wall-clock
by overlapping a JD screen on one tab with a form fill on the other. This probe measures
it SAFELY and reports a verdict; it does NOT change the loop's one-tab default.

GUARDS (why this can't damage a real run):
  * It uses its OWN two fresh tabs and closes them at the end (even on error).
  * It only navigates to about:blank + example.com-style control URLs by default — no
    logins, no job boards, no forms. (`--urls a,b` to override for a realistic probe.)
  * Any wedge signal (500/410/404 on open or navigate, or an unexpected tab count jump)
    stops it IMMEDIATELY, closes tabs, and reports WEDGED with the round it happened.
  * Bounded rounds (default 12) and a hard per-op timeout — it can't loop forever.

Verdict -> append the result to references/camofox-concurrent-tab-wedge.md yourself; do
NOT flip the one-tab rule on a single green run.

Usage: CFX_KEY=… python3 scripts/twotab_probe.py [--rounds N] [--urls urlA,urlB]
"""
import os
import sys
import time

_here = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_here)
sys.path.insert(0, os.path.join(_ROOT, "sites", "_common", "scripts"))
import cfx  # noqa: E402

WEDGE_SIGNS = ("500", "410", "404", "internal server error", "browser was restarted",
               "tab not found", "tab no longer exists")


def _is_wedge(err):
    e = str(err).lower()
    return any(s in e for s in WEDGE_SIGNS)


def main():
    argv = sys.argv[1:]
    if not os.environ.get("CFX_KEY"):
        print("SKIP: no CFX_KEY in env")
        return 0
    rounds = int(argv[argv.index("--rounds") + 1]) if "--rounds" in argv and argv.index("--rounds") + 1 < len(argv) else 12
    urls = (argv[argv.index("--urls") + 1].split(",")
            if "--urls" in argv and argv.index("--urls") + 1 < len(argv)
            else ["https://example.com/", "https://example.org/"])
    urlA, urlB = (urls + urls)[:2]

    tabA = tabB = None
    verdict, detail = "STABLE", ""
    try:
        base = len(cfx.list_tabs())
        tabA = cfx.open_tab("about:blank")
        tabB = cfx.open_tab("about:blank")
        print(f"opened 2 tabs (base tab count {base}): A={tabA} B={tabB}")
        for r in range(1, rounds + 1):
            for tab, url in ((tabA, urlA), (tabB, urlB)):
                try:
                    cfx.navigate(url, tab=tab, pace_tier="light", timeout=30)
                except cfx.CfxError as e:
                    if _is_wedge(e):
                        verdict, detail = "WEDGED", f"round {r} nav {tab}: {e}"
                        raise
                    # a non-wedge nav error (e.g. a site 4xx) isn't the thing we test
                    print(f"  round {r} {tab}: non-wedge nav error: {e}")
            # sanity: a runaway tab count is itself a wedge precursor
            n = len(cfx.list_tabs())
            if n > base + 4:
                verdict, detail = "WEDGED", f"round {r}: tab count jumped to {n} (base {base})"
                break
            print(f"  round {r}/{rounds}: OK (tabs={n})")
            time.sleep(0.5)
    except cfx.CfxError as e:
        if verdict != "WEDGED":
            verdict, detail = "ERROR", str(e)
    finally:
        for t in (tabA, tabB):
            if t:
                try:
                    cfx.close_tab(t)
                except Exception:
                    pass

    print(f"\nVERDICT: {verdict}" + (f" — {detail}" if detail else ""))
    print("Record this in references/camofox-concurrent-tab-wedge.md. Do NOT change the "
          "one-tab loop default on a single run.")
    return 0 if verdict == "STABLE" else 1


if __name__ == "__main__":
    sys.exit(main())
