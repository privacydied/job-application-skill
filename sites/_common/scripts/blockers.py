#!/usr/bin/env python3
"""
blockers.py — structured blocker inbox + parked-application resume (feature-roadmap N.3).

WHY THIS EXISTS. Every wall (login / non-sanctioned CAPTCHA / downstream account / SMS
verification) serializes the human INTO the loop: today the loop stops, prints a prose
"held" message, and the application is parked in whatever half-filled state it reached — with
no structured record and no resume path except the model happening to remember. So human
latency is SERIAL (the loop waits) and a parked application is easily lost.

This makes blockers DATA:
  * record(...) writes a structured blocker to blockers.jsonl (kind, site, url, what-to-do,
    VNC link, the parked application's slug) and fires a best-effort push notification, so the
    human learns immediately and the loop can continue OTHER work meanwhile (human latency
    becomes PARALLEL).
  * The human clears it whenever and marks it resolved (`blockers.py resolve <id>`).
  * resumable() lists resolved blockers whose parked application is NOT yet confirmed (per the
    H.8 journal) — the next firing / daemon pass resumes each from its journal state instead
    of relying on the model remembering.

⚠️ CAPTCHA semantics are UNCHANGED. A non-sanctioned CAPTCHA is still a FULL immediate halt
(SKILL.md / captcha-policy.md). This inbox is the RESUME mechanism after the human clears it —
NOT a license to continue past it. record() for a captcha still means "the loop halted here."

blockers.jsonl (skill root, gitignored) rows:
  {id, kind, site, url, company, role, slug, what, vnc, created, resolved, resolved_at?}
  kind ∈ login | captcha | account | sms | other

Push notification: best-effort. If env NOTIFY_CMD is set it's run with the message as its
last arg (e.g. NOTIFY_CMD="ntfy publish mytopic"); else a notify.sh at the skill root is
called if present; else it's just logged. Never raises.

CLI:
  blockers.py record <kind> <site> --url u --company c --role r --slug s --what "…"
  blockers.py list [--all]        # open (or --all) blockers
  blockers.py resolve <id> [note]
  blockers.py resumable           # resolved blockers whose parked app isn't confirmed yet
"""
import json
import os
import subprocess
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fsutil import locked_append, file_lock, atomic_write  # noqa: E402
import journal  # noqa: E402  (H.8 — the resume substrate)

_here = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_here, "..", "..", ".."))
BLOCKERS = os.path.join(_ROOT, "blockers.jsonl")
VNC = "http://nasirjones:6080/vnc.html"
KINDS = ("login", "captcha", "account", "sms", "other")


def notify(message):
    """Best-effort push notification. NOTIFY_CMD env (run with message appended) → notify.sh
    at root → log only. Never raises."""
    cmd = os.environ.get("NOTIFY_CMD")
    try:
        if cmd:
            subprocess.run(cmd.split() + [message], timeout=15,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        sh = os.path.join(_ROOT, "notify.sh")
        if os.path.isfile(sh) and os.access(sh, os.X_OK):
            subprocess.run([sh, message], timeout=15,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


def _read():
    out = []
    try:
        with open(BLOCKERS, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        continue
    except (FileNotFoundError, OSError):
        pass
    return out


def record(kind, site, url="", company="", role="", slug="", what="", now=None):
    """Append a structured blocker + fire a push notification. Returns the blocker id."""
    now = now or datetime.now()
    if not slug and (company or role):
        slug = journal.slugify(company, role)
    bid = f"{now.strftime('%Y%m%dT%H%M%S')}-{(site or kind)[:20]}"
    rec = {"id": bid, "kind": (kind or "other").lower(), "site": site, "url": url,
           "company": company, "role": role, "slug": slug, "what": what, "vnc": VNC,
           "created": now.strftime("%Y-%m-%dT%H:%M:%S"), "resolved": False}
    try:
        locked_append(BLOCKERS, lambda f: f.write(json.dumps(rec, ensure_ascii=False) + "\n"))
    except OSError:
        pass
    msg = (f"[job-apply BLOCKED] {rec['kind']} @ {site}"
           + (f" — {company} {role}".rstrip() if (company or role) else "")
           + (f" — {what}" if what else "") + f" | clear via VNC {VNC} then "
           f"`blockers.py resolve {bid}`")
    notify(msg)
    return bid


def pending():
    return [b for b in _read() if not b.get("resolved")]


def resolve(bid, note="", now=None):
    now = now or datetime.now()
    with file_lock(BLOCKERS):
        rows = _read()
        hit = False
        for b in rows:
            if b.get("id") == bid and not b.get("resolved"):
                b["resolved"] = True
                b["resolved_at"] = now.strftime("%Y-%m-%dT%H:%M:%S")
                if note:
                    b["note"] = note
                hit = True
        if not hit:
            return False

        def _w(f):
            for b in rows:
                f.write(json.dumps(b, ensure_ascii=False) + "\n")
        atomic_write(BLOCKERS, _w)
    return True


def resumable():
    """Resolved blockers whose parked application (by slug) is NOT confirmed per the journal
    — the resume worklist for the next firing/daemon pass. A resolved blocker with a confirmed
    (or absent-slug) application is done and excluded."""
    out = []
    for b in _read():
        if not b.get("resolved"):
            continue
        slug = b.get("slug")
        if not slug:
            continue
        if journal.is_confirmed(slug):
            continue
        b = dict(b)
        b["journal_state"] = journal.last_state(slug)
        b["submitted_unconfirmed"] = journal.is_submitted_unconfirmed(slug)
        out.append(b)
    return out


def _cli(argv):
    cmd = argv[1] if len(argv) > 1 else ""

    def opt(flag, default=""):
        return argv[argv.index(flag) + 1] if flag in argv and argv.index(flag) + 1 < len(argv) else default

    if cmd == "record" and len(argv) >= 4:
        bid = record(argv[2], argv[3], url=opt("--url"), company=opt("--company"),
                     role=opt("--role"), slug=opt("--slug"), what=opt("--what"))
        print(f"recorded {bid} (push-notified). CAPTCHA/login stay HARD-HALT — this only "
              f"tracks + enables resume after you clear it.")
        return 0
    if cmd == "list":
        rows = _read() if "--all" in argv else pending()
        if not rows:
            print("no open blockers." if "--all" not in argv else "no blockers recorded.")
            return 0
        for b in rows:
            state = "RESOLVED" if b.get("resolved") else "OPEN"
            print(f"[{state}] {b['id']} {b['kind']} @ {b['site']} "
                  f"{b.get('company','')} {b.get('role','')} — {b.get('what','')}  {b.get('url','')}")
        return 0
    if cmd == "resolve" and len(argv) >= 3:
        note = argv[3] if len(argv) > 3 else ""
        print("resolved" if resolve(argv[2], note) else "not-found")
        return 0
    if cmd == "resumable":
        rows = resumable()
        if not rows:
            print("nothing to resume.")
            return 0
        print(f"{len(rows)} parked application(s) to resume (blocker cleared, not yet confirmed):")
        for b in rows:
            print(f"  slug={b['slug']} state={b.get('journal_state')} "
                  f"submitted_unconfirmed={b.get('submitted_unconfirmed')} "
                  f"({b.get('company','')} {b.get('role','')}) {b.get('url','')}")
        return 0
    if cmd == "notify-test":
        ok = notify("[job-apply] blockers.py notify-test")
        print("sent" if ok else "no NOTIFY_CMD/notify.sh configured (logged only)")
        return 0
    print("Usage: blockers.py record <kind> <site> [--url --company --role --slug --what] | "
          "list [--all] | resolve <id> [note] | resumable | notify-test", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(_cli(sys.argv))
