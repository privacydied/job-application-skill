#!/usr/bin/env python3
"""feed.py — Wellfound (ex-AngelList Talent) sourcing (feature-roadmap P.4).

Wellfound carries startup UX/product/eng inventory the aggregators under-carry, and SKILL.md
already name-checks it in the board rotation. BUT it has NO public, keyless API: its job
search is a login-gated GraphQL endpoint, and in-platform quick-apply requires an account.
That makes it a **downstream-account wall**, exactly the class the N.4 account-provisioning
queue exists to attack — not a keyless HTTP feed like Remotive/Jobicy.

So this feed is honest about the wall instead of faking a scrape:
  * with NO account (no `wellfound.com` row in ats-credentials.csv), it records the wall to
    the account-provisioning queue (accounts.py) and exits 2 naming the exact unblock — the
    same contract the key-gated feeds (reedapi/jooble/careerjet) use.
  * once an account exists, the logged-in GraphQL search + in-platform apply can be driven
    through camofox (a future driver); until then, sourcing here is blocked by design.

This keeps Wellfound VISIBLE in the funnel's board set and its unblock RANKED against the
other account walls (so a human account-session is spent where it unlocks the most), rather
than silently absent.

Usage:
    python3 feed.py [--what "ux designer"] [--all] [--force]
"""
import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_here, "..", "..", "_common", "scripts"))
import httpfeed  # noqa: E402  (creds_row helper — the sanctioned credential source)
import accounts  # noqa: E402  (N.4 account-provisioning queue)


def main():
    email, _pw = httpfeed.creds_row("wellfound.com")
    if not email:
        # Record/refresh the account wall so `accounts.py ranked` surfaces it, then exit 2
        # with the concrete unblock (mirrors the key-gated feeds' "exit 2 naming the row").
        accounts.record("wellfound", board="wellfound",
                        url="https://wellfound.com/ (create an account; in-platform quick apply)",
                        note="login-gated GraphQL search + in-platform apply; needs an account")
        print("[]")
        print("ERROR: Wellfound needs an account — no `wellfound.com` row in "
              "ats-credentials.csv. This is a downstream-ACCOUNT wall (recorded to the N.4 "
              "queue; see `accounts.py ranked`). Create an account at https://wellfound.com/, "
              "add a `wellfound.com` row (email,password), then this feed can drive the "
              "logged-in search. Until then Wellfound is not sourceable.", file=sys.stderr)
        return 2

    # An account exists — the logged-in GraphQL search + apply driver is not built yet.
    # Report that precisely (a driver gap, distinct from the account wall) rather than
    # pretending to source. Left as the single next build once an account is provisioned.
    print("[]")
    print("ERROR: Wellfound account present but the logged-in GraphQL search driver is not "
          "built yet (camofox path). This is a DRIVER gap, not an account wall — implement "
          "the logged-in search here next.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
