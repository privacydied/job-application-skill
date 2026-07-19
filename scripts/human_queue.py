#!/usr/bin/env python3
"""
human_queue.py — the ONE coalesced human-intervention worklist ("set-and-forget" lever).

WHY THIS EXISTS. Every human touchpoint in this skill is currently scattered and
per-incident: a captcha halts the run and pings the user (blockers.jsonl), a login wall
waits on the user (holds.csv), and each account wall accretes separately (accounts-needed.csv).
So the human is interrupted N times, unpredictably, each for one item. That is the opposite
of "set and forget."

This script COALESCES all of them into a single ranked session: "spend 10 human-minutes
here, in this order, and unlock the most queued applications." It reads the three existing
ledgers (nothing new to maintain), estimates how many pending/blocked applications each
action would unlock (from queue.jsonl + the tracker), ranks by that leverage, and prints
ONE worklist with the VNC link and the exact resolve command per item.

It is READ-ONLY (like triage_blocked.py): it never mutates a ledger. The human does the
batch session, then clears each item its normal way (`blockers.py resolve <id>`, drop creds
into ats-credentials.csv + `accounts.py resolve <ats>` + `triage_blocked.py`), and the next
firing/daemon resumes automatically.

Sources it unifies:
  * accounts.ranked()   — account walls (parliament/tfl/bbc/… need self-registration)
  * blockers.pending()  — open captcha/login/account/sms blockers (blockers.jsonl)
  * holds.csv (via search_plan.read_holds) — captcha (halts all) / login (per-site) holds

Leverage estimate per item = est_inventory (accounts) or queued+blocked rows for the site.

CLI:
  human_queue.py            # the ranked human-batch worklist (human-readable)
  human_queue.py --json     # machine worklist (ordered list of items)
  human_queue.py --top N    # only the N highest-leverage items
"""
import json
import os
import sys
from urllib.parse import urlparse

_here = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_here)
sys.path.insert(0, os.path.join(_ROOT, "sites", "_common", "scripts"))

import accounts        # noqa: E402  — account-wall ledger (ranked by blocked_count/inventory)
import blockers        # noqa: E402  — structured blocker inbox (captcha/login/account/sms)
import search_plan     # noqa: E402  — read_holds() parses holds.csv (captcha/login)

QUEUE = os.path.join(_ROOT, "queue.jsonl")
TRACKER = os.path.join(_ROOT, "application-tracker.csv")
VNC = blockers.VNC


def _norm_site(s):
    """A comparable site token: bare host (drop scheme/www) or a lowercased slug."""
    s = (s or "").strip().lower()
    if not s:
        return ""
    if "//" in s or "." in s:
        host = urlparse(s if "//" in s else "//" + s).netloc or s
        host = host.split("@")[-1].split(":")[0]
        if host.startswith("www."):
            host = host[4:]
        return host
    return s


def _site_matches(token, hay):
    """Loose containment either way — 'guardian' matches 'jobs.theguardian.com' and vice
    versa — so a blocker keyed by short site name still finds its queued/tracked rows."""
    token, hay = _norm_site(token), _norm_site(hay)
    if not token or not hay:
        return False
    # compare on the significant label (theguardian vs jobs.theguardian.com)
    a = token.split(".")[0] if "." in token else token
    b = hay
    return a in b or token in b or b in token


def _queued_by_site(site):
    """How many pending queue.jsonl rows belong to `site` (by board or url host)."""
    n = 0
    try:
        with open(QUEUE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if _site_matches(site, row.get("board", "")) or \
                        _site_matches(site, row.get("url", "")):
                    n += 1
    except (FileNotFoundError, OSError):
        pass
    return n


def _blocked_by_site(site):
    """How many tracker rows for `site` are in a Blocked state — applications that would
    become re-appliable once this wall is cleared (triage_blocked re-queues them)."""
    import csv
    n = 0
    try:
        with open(TRACKER, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if (row.get("Status") or "").strip() != "Blocked":
                    continue
                if _site_matches(site, row.get("Source", "")) or \
                        _site_matches(site, row.get("URL", "")):
                    n += 1
    except (FileNotFoundError, OSError):
        pass
    return n


def build_worklist():
    """The coalesced, leverage-ranked list of human actions. Each item:
        {kind, target, unlocks, action, url, note, resolve}
    `unlocks` is the estimated number of applications this one action frees up.
    De-duplicated so an account wall that appears in BOTH accounts-needed.csv and a
    blockers.jsonl 'account' row is listed once (leverage taken as the max)."""
    items = {}   # key -> item (dedup by (kind-class, target))

    def _upsert(key, item):
        cur = items.get(key)
        if cur is None or item["unlocks"] > cur["unlocks"]:
            # keep the richer of the two notes/urls
            if cur:
                item.setdefault("note", cur.get("note", ""))
                item["url"] = item.get("url") or cur.get("url", "")
            items[key] = item
        elif cur and not cur.get("url") and item.get("url"):
            cur["url"] = item["url"]

    # 1) account walls — the highest-leverage class (one signup unlocks a whole board)
    for a in accounts.ranked():
        target = a.get("ats") or a.get("key") or ""
        est = int(a.get("est_inventory") or 0)
        blk = int(a.get("blocked_count") or 0)
        unlocks = max(est, blk, _queued_by_site(a.get("board") or target),
                      _blocked_by_site(target))
        _upsert(("account", accounts._norm(target)), {
            "kind": "account-signup", "target": target, "unlocks": unlocks,
            "action": f"Create an account on {target} (self-registration; may be "
                      f"reCAPTCHA/SMS-gated), then drop creds into ats-credentials.csv.",
            "url": a.get("signup_url") or "",
            "note": a.get("note") or "",
            "resolve": f"accounts.py resolve {target}  &&  triage_blocked.py --ats {target}",
        })

    # 2) open blockers (captcha/login/account/sms) from blockers.jsonl
    for b in blockers.pending():
        kind = (b.get("kind") or "other").lower()
        site = b.get("site") or ""
        target = site or b.get("company") or kind
        unlocks = max(_queued_by_site(site), _blocked_by_site(site), 1)
        if kind == "account":
            key = ("account", accounts._norm(target))
        else:
            key = (kind, _norm_site(target))
        label = {"captcha": "Solve the CAPTCHA (noVNC) and finish/Send the staged form",
                 "login": "Log in to the site in the browser (noVNC) so the session is live",
                 "sms": "Complete SMS/email verification (noVNC)",
                 "account": "Create the account (noVNC)"}.get(kind, "Clear the blocker (noVNC)")
        _upsert(key, {
            "kind": f"{kind}-clear", "target": target, "unlocks": unlocks,
            "action": f"{label}"
                      + (f" — {b.get('company','')} {b.get('role','')}".rstrip()
                         if (b.get("company") or b.get("role")) else "")
                      + (f": {b.get('what')}" if b.get("what") else ""),
            "url": b.get("url") or VNC,
            "note": b.get("what") or "",
            "resolve": f"blockers.py resolve {b.get('id')}",
        })

    # 3) holds.csv (captcha halts everything; login blocks that site) — may overlap (2)
    for h in search_plan.read_holds():
        kind = (h.get("type") or "").lower()
        site = h.get("site") or ""
        if not site and kind != "captcha":
            continue
        unlocks = max(_queued_by_site(site), _blocked_by_site(site), 1)
        key = (kind, _norm_site(site) or "captcha-hold")
        if key in items:
            continue  # already surfaced via a blocker row
        _upsert(key, {
            "kind": f"{kind}-hold", "target": site or "(all sites)", "unlocks": unlocks,
            "action": ("A held CAPTCHA is halting the whole loop — solve it (noVNC) and "
                       "clear the hold" if kind == "captcha"
                       else f"Log in to {site} (noVNC) to lift the per-site hold"),
            "url": h.get("url") or VNC,
            "note": h.get("note") or "",
            "resolve": "remove the row from holds.csv once cleared",
        })

    worklist = sorted(items.values(), key=lambda x: -int(x.get("unlocks") or 0))
    return worklist


def _print_human(worklist, top=None):
    shown = worklist[:top] if top else worklist
    if not shown:
        print("✓ No human actions pending — the loop is fully unattended right now.")
        return
    total = sum(int(i.get("unlocks") or 0) for i in shown)
    print("══════════════════════════════════════════════════════════════════════")
    print(f" HUMAN BATCH SESSION — {len(shown)} action(s), ~{total} applications unlocked")
    print(f" Do these in ONE noVNC sitting ({VNC}), highest-leverage first:")
    print("══════════════════════════════════════════════════════════════════════")
    for i, item in enumerate(shown, 1):
        print(f"\n {i}. [{item['kind']}] {item['target']}   (~{item['unlocks']} unlocked)")
        print(f"      → {item['action']}")
        if item.get("url"):
            print(f"      url:     {item['url']}")
        if item.get("note") and item["note"] not in item["action"]:
            print(f"      note:    {item['note'][:160]}")
        print(f"      resolve: {item['resolve']}")
    print("\n──────────────────────────────────────────────────────────────────────")
    print(" After the session, the next loop firing / autodrain resumes automatically.")


def main():
    argv = sys.argv[1:]
    top = None
    if "--top" in argv:
        i = argv.index("--top")
        if i + 1 < len(argv) and argv[i + 1].isdigit():
            top = int(argv[i + 1])
    worklist = build_worklist()
    if "--json" in argv:
        out = worklist[:top] if top else worklist
        print(json.dumps({"actions": out,
                          "total_unlocked": sum(int(i.get("unlocks") or 0) for i in out),
                          "vnc": VNC}, ensure_ascii=False, indent=1))
        return 0
    _print_human(worklist, top=top)
    return 0


if __name__ == "__main__":
    sys.exit(main())
