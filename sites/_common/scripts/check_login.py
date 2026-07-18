#!/usr/bin/env python3
"""
check_login.py — verify logged-in / wall state on the login-gated boards before sourcing.

The SKILL requires a login-check before sourcing LinkedIn and WTTJ (both are
session-gated; LinkedIn bot-walls guests hard). This was ad-hoc inline JS every run —
promoted from a Hermes throwaway (/tmp/chk_login.py, 2026-07-14) into a proper,
reusable script, and FIXED: the throwaway probed `www.welcometothejungle.com` (the
marketing domain — always looks logged-out); the real app is `app.welcometothejungle.com`
(see sites/welcometothejungle/NOTES.md).

Per board it navigates a known URL, reads a bundle of logged-in vs wall signals, and
classifies:
  logged_in  — a logged-in signal is present → OK to source
  wall       — a login-required board shows a sign-in wall and no logged-in signal →
               HARD STOP (message the user + VNC http://nasirjones:6080/vnc.html, wait)
  guest_ok   — a guest-browsable board (Indeed) loaded fine → OK to source
  blocked    — a guest board is bot-walled (Cloudflare/CAPTCHA) → treat per SKILL
  unknown    — ambiguous; screenshot and decide by eye (don't assume walled)

Usage:
    CFX_KEY=... CFX_TAB=... python3 check_login.py [board ...]
      pre-source boards (in the default sweep): linkedin | wttj | indeed | seek
      apply-session boards (on-demand — NOT in the default sweep): reed | csj | guardian |
              totaljobs | cvlibrary | amazon | nhs   — check these before an APPLY batch on
              that board (a dead session reads as `wall`). `all` runs every board.
      Default (no args) = the four pre-source boards only, so an apply-board's logged-out
              state never blocks a sourcing run. Pass specific boards for a subset,
              e.g. `check_login.py reed` before a reed_apply.py batch, or
              `check_login.py linkedin wttj` for the session-gated pre-source check.
      ⚠️ For GUARDIAN, `sites/jobs.theguardian.com/scripts/login.py --check` is authoritative
              (it handles the OAuth "signed in — Continue" half-state this probe can misread).
      ⚠️ reed/csj/guardian probe the ACCOUNT page (their homepage headers cache a stale
              "Sign out" and lie); totaljobs/cvlibrary/amazon/nhs signals are PENDING first-live
              validation (conservative — a miss degrades to `unknown`, never a false logged_in).
      ⚠️ NAVIGATES the tab once per board (like feed.py --nav) — run it BEFORE sourcing /
              point CFX_TAB at a scratch step, not mid-application.

    Login-REQUIRED boards (linkedin, wttj): a wall is a hard stop (exit 11).
    Guest-browsable boards (indeed, seek): login not needed to source, so a logged-out
    state is `guest_ok` (not a stop) — the `logged_in` boolean still reports actual status.

Output: one JSON object per board + a summary line, and an exit code:
  0  every checked board is OK to source (logged_in or guest_ok)
  11 at least one login-required board is WALLED (needs the user) — HOLD-like
  1  something ambiguous/blocked (unknown or blocked), nothing walled

Login is only ever handled by the user via VNC (SKILL login-wall rule) — this script
never attempts to log in, it only reports state.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cfx  # noqa: E402

# Per-board probe. `signals` runs in-page and returns booleans; `required` = login
# needed to source (a wall is a hard stop) vs guest-browsable.
BOARDS = {
    "linkedin": {
        "url": "https://www.linkedin.com/feed/",
        "required": True,
        "signals": r"""{
          logged_in: !!(document.querySelector('.global-nav__me-photo, img.global-nav__me-photo, .global-nav__me, [data-control-name="nav.settings"]')
                     || document.querySelector('a[href*="/in/"]')
                     || /feed|my network|notifications/i.test((document.querySelector('.global-nav')||{}).innerText||'')),
          wall: !!(document.querySelector('.authwall, form.login__form, input#session_key, [data-tracking-control-name*="guest_homepage"]')
                 || /sign in to linkedin|join linkedin|new to linkedin/i.test(document.body.innerText.slice(0,1500)))
        }""",
    },
    "wttj": {
        # the APP subdomain — NOT www.welcometothejungle.com (marketing, always logged-out)
        "url": "https://app.welcometothejungle.com/",
        "required": True,
        "signals": r"""{
          logged_in: !!(document.querySelector('[data-testid*="avatar" i], a[href*="/me/"], a[href*="/profile" i], button[aria-label*="account" i], [data-testid*="user-menu" i]')
                     || /^https:\/\/app\.welcometothejungle\.com\/(jobs|me|dashboard)/.test(location.href)),
          wall: !!(document.querySelector('a[href*="/login"], a[href*="/signup"], [data-testid*="signin" i]')
                 || /log in|sign up|create.*account/i.test(document.body.innerText.slice(0,800)))
                 && !document.querySelector('a[href*="/me/"], [data-testid*="avatar" i]')
        }""",
    },
    "indeed": {
        "url": "https://uk.indeed.com/",
        "required": False,  # guest-browsable — login not needed to source
        "signals": r"""{
          logged_in: !!document.querySelector('[data-gnav-element-name="AccountMenu"], [data-gnav-element-name="SignOut"], a[href*="/account"], a[href*="/logout"]'),
          wall: !!(document.querySelector('iframe[src*="challenge" i], #challenge-running, .cf-challenge, iframe[title*="captcha" i]')
                 || /verify you are human|checking your browser|unusual traffic|additional verification/i.test(document.body.innerText.slice(0,600)))
        }""",
    },
    "seek": {
        # AU/NZ board (SKILL "Boards to hit" #5). Guest-browsable for search; applying
        # needs login. Signed-in = account/profile menu; signed-out = Sign in / Register.
        "url": "https://www.seek.com.au/",
        "required": False,  # guest-browsable — login not needed to source
        "signals": r"""{
          logged_in: !!(document.querySelector('[data-automation="account name"], [data-automation="signOutLink"], [data-automation*="profile" i], a[href*="/oauth/logout"], a[href*="/profile"]')
                     || /sign out/i.test((document.querySelector('header,[data-automation*="header" i]')||{}).innerText||'')),
          wall: !!(document.querySelector('[data-automation="sign in"], [data-automation="signInLink"], [data-automation="register"], a[href*="/oauth/login"]')
                 || /\bsign in\b/i.test((document.querySelector('header,[data-automation*="header" i]')||{}).innerText||''))
                 && !document.querySelector('[data-automation="account name"], [data-automation="signOutLink"]')
        }""",
    },
    "reed": {
        # Reed APPLY needs a live session (sourcing via feed.py is guest-ok). ⚠️ CHECK THE
        # ACCOUNT PAGE, NOT the homepage: reed.co.uk's header caches a "Sign out" link that stays
        # visible AFTER the apply session dies, so the homepage FALSELY looks logged-in (this is
        # why a firing wrote _reed_probe.py — the homepage lied). /account/jobs/applications shows
        # the TRUE state — a live session renders your applications + a logout link; a dead one
        # shows "Session expired" + logged-out CTAs ("Register your CV"). required=True so a dead
        # session reads as `wall` (re-login before a reed_apply.py batch). NOT in DEFAULT_BOARDS —
        # run on demand: `check_login.py reed`.
        "url": "https://www.reed.co.uk/account/jobs/applications",
        "required": True,
        "signals": r"""{
          logged_in: !/session expired|register your cv|create your reed account/i.test(document.body.innerText.slice(0,2500))
                     && !!([...document.querySelectorAll('a')].some(a=>/sign out|log ?out/i.test(a.innerText||''))
                        || document.querySelector('a[href*="/logout" i], a[href*="/signout" i]')),
          wall: /session expired/i.test(document.body.innerText.slice(0,3000))
                || /\/(signin|login)/i.test(location.href)
                || (/register your cv/i.test(document.body.innerText.slice(0,1500))
                    && ![...document.querySelectorAll('a')].some(a=>/sign out/i.test(a.innerText||'')))
                || ([...document.querySelectorAll('a,button')].some(e=>/^\s*sign in\s*$/i.test((e.innerText||'').trim()))
                    && ![...document.querySelectorAll('a')].some(a=>/sign out/i.test(a.innerText||'')))
        }""",
    },
    "csj": {
        # CSJ apply/candidate state lives in the TAL layer (cshr.tal.net), NOT the
        # civilservicejobs.service.gov.uk front (whose header shows "Sign in to your account" even
        # when TAL is live — same header-lies trap as Reed). A live session renders the candidate
        # applications list; a dead one bounces to .../csr/oidc/... "You must sign in to your Civil
        # Service Jobs account". (VALIDATED: logged-out state observed 2026-07-18.)
        "url": "https://cshr.tal.net/vx/lang-en-GB/candidate/application",
        "required": True,
        "signals": r"""{
          logged_in: /cshr\.tal\.net\/.*\/candidate/i.test(location.href)
                     && !/you must sign in/i.test(document.body.innerText.slice(0,800))
                     && (/application/i.test((document.querySelector('h1,h2')||{}).innerText||'')
                         || [...document.querySelectorAll('a')].some(a=>/sign out/i.test(a.innerText||''))),
          wall: /\/oidc\/|\/signin|\/login/i.test(location.href)
                || /you must sign in to your civil service jobs/i.test(document.body.innerText.slice(0,600))
                || /^\s*sign in\s*$/i.test((document.querySelector('h1,h2')||{}).innerText||'')
        }""",
    },
    "guardian": {
        # Guardian Jobs (Madgex). Login is OAuth via profile.theguardian.com; the dedicated
        # sites/jobs.theguardian.com/scripts/login.py --check is AUTHORITATIVE (it handles the
        # "You are signed in with <email> — Continue" half-state that a plain probe misreads). This
        # native probe is a lightweight cross-board sweep only: signed-in shows the Madgex account
        # menu; a redirect to profile.theguardian.com/signin is the wall. Prefer login.py --check
        # before acting.
        "url": "https://jobs.theguardian.com/account/",
        "required": True,
        "signals": r"""{
          logged_in: !/profile\.theguardian\.com\/signin/i.test(location.href)
                     && [...document.querySelectorAll('a')].some(a=>/sign out|your applications|saved jobs/i.test(a.innerText||'')),
          wall: /profile\.theguardian\.com\/signin/i.test(location.href)
                || [...document.querySelectorAll('a,button')].some(e=>/^\s*sign in\s*$/i.test((e.innerText||'').trim()))
        }""",
    },
    # ── PENDING first-live validation: cred rows exist but the logged-in markers below are
    #    conservative best-guesses (a strong positive signal required, so a miss degrades to
    #    `unknown`/screenshot, never a false `logged_in`). Refine each on its next real session. ──
    "totaljobs": {
        "url": "https://www.totaljobs.com/profile",
        "required": True,
        "signals": r"""{
          logged_in: [...document.querySelectorAll('a')].some(a=>/sign out|log out|my profile|your applications/i.test(a.innerText||'')),
          wall: [...document.querySelectorAll('a,button')].some(e=>/^\s*(sign in|log in|register)\s*$/i.test((e.innerText||'').trim()))
                && ![...document.querySelectorAll('a')].some(a=>/sign out|log out/i.test(a.innerText||''))
        }""",
    },
    "cvlibrary": {
        "url": "https://www.cv-library.co.uk/my-cv-library",
        "required": True,
        "signals": r"""{
          logged_in: !/\/login|\/register/i.test(location.href)
                     && [...document.querySelectorAll('a')].some(a=>/sign out|log out|my cv-library|applications/i.test(a.innerText||'')),
          wall: /\/login|\/register/i.test(location.href)
                || [...document.querySelectorAll('a,button')].some(e=>/^\s*(sign in|log in)\s*$/i.test((e.innerText||'').trim()))
                   && ![...document.querySelectorAll('a')].some(a=>/sign out|log out/i.test(a.innerText||''))
        }""",
    },
    "amazon": {
        "url": "https://www.amazon.jobs/en/applicant/dashboard",
        "required": True,
        "signals": r"""{
          logged_in: !/\/signin|\/login|ap\/signin/i.test(location.href)
                     && [...document.querySelectorAll('a')].some(a=>/sign out|log out|my applications|dashboard/i.test(a.innerText||'')),
          wall: /\/signin|\/login|ap\/signin/i.test(location.href)
                || [...document.querySelectorAll('a,button')].some(e=>/^\s*sign in\s*$/i.test((e.innerText||'').trim()))
                   && ![...document.querySelectorAll('a')].some(a=>/sign out|log out/i.test(a.innerText||''))
        }""",
    },
    "nhs": {
        "url": "https://www.jobs.nhs.uk/candidate/applications",
        "required": True,
        "signals": r"""{
          logged_in: !/\/login|\/signin/i.test(location.href)
                     && [...document.querySelectorAll('a')].some(a=>/sign out|log out|my applications|your applications/i.test(a.innerText||'')),
          wall: /\/login|\/signin/i.test(location.href)
                || [...document.querySelectorAll('a,button')].some(e=>/^\s*(sign in|log in)\s*$/i.test((e.innerText||'').trim()))
                   && ![...document.querySelectorAll('a')].some(a=>/sign out|log out/i.test(a.innerText||''))
        }""",
    },
}

# Default set when no board args given: check ALL of them (login status for every board).
# The exit-11 hard stop only fires for login-REQUIRED boards (linkedin/wttj) being walled;
# indeed/seek are guest-browsable, so a logged-out state there is guest_ok, not a stop —
# their `logged_in` boolean still tells you the actual login status.
DEFAULT_BOARDS = ["linkedin", "wttj", "indeed", "seek"]


def probe(board):
    spec = BOARDS[board]
    cfx.navigate(spec["url"])
    cfx.poll("document.readyState", predicate=lambda r: r == "complete", timeout=25)
    time.sleep(2.5)  # let SPA nav / auth redirects settle
    try:
        raw = cfx.evaluate("JSON.stringify(Object.assign({url:location.href}, " + spec["signals"] + "))")
        sig = json.loads(raw) if isinstance(raw, str) else {}
    except (cfx.CfxError, ValueError) as e:
        return {"board": board, "verdict": "unknown", "error": str(e)[:120]}

    logged_in, wall = bool(sig.get("logged_in")), bool(sig.get("wall"))
    if logged_in:
        verdict = "logged_in"
    elif spec["required"]:
        verdict = "wall" if wall else "unknown"
    else:  # guest-browsable
        verdict = "blocked" if wall else "guest_ok"
    return {"board": board, "required": spec["required"], "url": sig.get("url", spec["url"]),
            "logged_in": logged_in, "wall": wall, "verdict": verdict}


def main():
    args = [a.lower() for a in sys.argv[1:]]
    if "all" in args or not args:
        boards = list(BOARDS) if "all" in args else DEFAULT_BOARDS
    else:
        boards = [b for b in args if b in BOARDS]
        if not boards:
            print(f"FAIL: no known board in {args} (known: {', '.join(BOARDS)}, or 'all')")
            return 2

    results = []
    for b in boards:
        try:
            results.append(probe(b))
        except cfx.CfxError as e:
            results.append({"board": b, "verdict": "unknown", "error": str(e)[:120]})

    for r in results:
        print(json.dumps(r))

    walled = [r["board"] for r in results if r["verdict"] == "wall"]
    ok = [r["board"] for r in results if r["verdict"] in ("logged_in", "guest_ok")]
    other = [r["board"] for r in results if r["verdict"] in ("unknown", "blocked")]

    print("\nsummary: "
          + f"OK to source: {', '.join(ok) or '—'}"
          + (f" | WALLED (need user via VNC): {', '.join(walled)}" if walled else "")
          + (f" | ambiguous/blocked: {', '.join(other)}" if other else ""),
          file=sys.stderr)
    if walled:
        print(f"HOLD: {', '.join(walled)} need login — message the user "
              f"(http://nasirjones:6080/vnc.html), continue login-free boards meanwhile.",
              file=sys.stderr)
        return 11
    return 0 if not other else 1


if __name__ == "__main__":
    sys.exit(main())
