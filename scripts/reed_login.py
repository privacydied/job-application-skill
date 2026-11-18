#!/usr/bin/env python3
"""reed_login.py — re-authenticate a dead Reed session via the emailed 4-digit code.

Reed has no password login: SignIn emails a 4-digit code. This is the ONE scripted re-login
(recipe + failure history: references/reed-session-wall-recovery.md). Rules it enforces, each
one a real failure on a live run:

  1. CLEAR COOKIES FIRST. A stuck OTP step from an earlier attempt hides #signin_email; the
     run starts by clearing Reed cookies + storage (and signing out) so the email step shows.
  2. NEVER click "Send code again" before the first fetch. Resending invalidates the code the
     reader is about to return. The passwordless click IS the explicit request.
  3. Select the email by REQUEST TIME, not "newest 4-digit token". Before each request the
     script records the mailbox's highest IMAP UID and the clock; it accepts only a Reed email
     with a higher UID whose Date is after the request (minus --skew-s). Stale unspent codes
     in the inbox are otherwise indistinguishable from the live one.
     A resend happens only when no code arrived within --wait, and it is again an explicit
     request with its own UID/time baseline.
  4. Commit each digit through React's native value setter + input/change events. Only if
     Verify stays disabled, fall back to real keystrokes (click, type, Tab).
  5. After Verify, WAIT for the URL to leave the login/sign-in page before checking session
     state; then confirm "Sign out" on the applications page.

Usage:
  python3 scripts/reed_login.py                 # camofox tab (source .jobenv.run first)
  python3 scripts/reed_login.py --if-needed     # no-op when already signed in
  python3 scripts/reed_login.py --cdp http://localhost:9222   # local Edge/Chrome fallback
  Options: --email ADDR  --wait 90  --resends 1  --skew-s 60

Email address: --email, else the `reed...` row in ats-credentials.csv, else the IMAP row
address (Reed must send to the mailbox the IMAP row reads). No address is hardcoded.

Prints LOGIN_OK and exits 0 on success. Exit codes: 1 no address / IMAP creds,
2 email step never appeared, 3 no fresh code, 4 Verify stayed disabled,
5 redirect never left the login page, 6 session check failed after redirect.
"""
import argparse
import csv
import email as emaillib
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "sites", "_common", "scripts"))
import email_ingest as ei  # noqa: E402
import fetch_verification_code as vcode  # noqa: E402

SIGNIN_URL = "https://www.reed.co.uk/account/SignIn?returnUrl=%2F"
SIGNOUT_URL = "https://www.reed.co.uk/account/signout?returnUrl=%2F"
HOME_URL = "https://www.reed.co.uk/"
APPS_URL = "https://www.reed.co.uk/account/jobs/applications"
EMAIL_SEL = "#signin_email"
SEND_SEL = "#signin_button_passwordless_signin_jobseeker_web_view"
VERIFY_SEL = "#passwordless_verify_code"
DIGIT_IDS = ("first-otp-digit", "second-otp-digit", "third-otp-digit", "fourth-otp-digit")


# ── pure helpers (unit-tested in tests/test_core.py) ─────────────────────────────────

def on_login_page(url):
    """True while the tab is still on Reed's sign-in / auth-callback flow."""
    low = (url or "").lower()
    return "login" in low or "signin" in low


def _msg_date(date_hdr):
    try:
        dt = parsedate_to_datetime(date_hdr) if date_hdr else None
    except (TypeError, ValueError):
        return None
    if dt is not None and dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def select_code(messages, base_uid, requested_at, skew_s=60):
    """The 4-digit code from the newest Reed email that arrived AFTER the request, or ''.

    messages     : iterable of (uid:int, from_hdr, date_hdr, body_text)
    base_uid     : highest mailbox UID seen just BEFORE the request — anything at or below
                   it existed already and is stale by construction (clock-independent).
    requested_at : aware datetime of the request; the Date header must be >= it - skew_s.
                   A missing/unparseable Date fails CLOSED here (unlike get_code): a code we
                   cannot place in time is exactly the stale-code failure this guards."""
    floor = requested_at - timedelta(seconds=skew_s)
    for uid, frm, date_hdr, body in sorted(messages, key=lambda m: m[0], reverse=True):
        if uid <= base_uid or "reed" not in (frm or "").lower():
            continue
        dt = _msg_date(date_hdr)
        if dt is None or dt < floor:
            continue
        code = vcode._extract(body or "", digits=4)
        if code:
            return code
    return ""


# ── mailbox ──────────────────────────────────────────────────────────────────────────

def mailbox_max_uid():
    """Highest UID in INBOX right now (0 if empty). Taken just before each code request."""
    M = ei._connect()
    try:
        M.select("INBOX", readonly=True)
        typ, data = M.uid("search", None, "ALL")
        uids = [int(u) for u in (data[0].split() if typ == "OK" and data and data[0] else [])]
        return max(uids) if uids else 0
    finally:
        try:
            M.logout()
        except Exception:  # noqa: BLE001
            pass


def _new_messages(base_uid):
    """(uid, from, date, body) for every INBOX message with UID > base_uid. PEEK: never marks
    a message \\Seen (see fetch_verification_code.get_code)."""
    M = ei._connect()
    out = []
    try:
        M.select("INBOX", readonly=True)
        typ, data = M.uid("search", None, f"UID {base_uid + 1}:*")
        for raw in (data[0].split() if typ == "OK" and data and data[0] else []):
            uid = int(raw)
            if uid <= base_uid:          # "N:*" returns the last message even when N > max
                continue
            t2, md = M.uid("fetch", raw, "(BODY.PEEK[])")
            if t2 != "OK" or not md or not md[0] or not isinstance(md[0], tuple):
                continue
            msg = emaillib.message_from_bytes(md[0][1])
            out.append((uid, msg.get("From") or "", msg.get("Date"), vcode._body_text(msg)))
    finally:
        try:
            M.logout()
        except Exception:  # noqa: BLE001
            pass
    return out


def wait_for_code(base_uid, requested_at, wait_s, skew_s, poll_s=5):
    deadline = time.time() + wait_s
    while True:
        try:
            code = select_code(_new_messages(base_uid), base_uid, requested_at, skew_s)
        except Exception as e:  # noqa: BLE001 — one IMAP hiccup must not end the wait
            print(f"  IMAP_WARN {e}", file=sys.stderr)
            code = ""
        if code:
            # Record it for sibling drives. The UID baseline already proves this email is
            # new, so a ledger collision (4-digit codes repeat) is only a warning.
            if not vcode._ledger_consume(code):
                print("  VCODE_LEDGER_COLLISION (new email, reused digits) — using it", file=sys.stderr)
            return code
        if time.time() >= deadline:
            return ""
        time.sleep(poll_s)


# ── browser backends ─────────────────────────────────────────────────────────────────

class CfxPage:
    """camofox tab via the shared cfx driver (the default; the only sanctioned browser)."""

    def __init__(self):
        import cfx  # noqa: PLC0415
        self.cfx = cfx
        cfx.ensure_tab(persist=True)

    def goto(self, url):
        self.cfx.goto(url)

    def js(self, expr):
        return self.cfx.evaluate(expr)

    def url(self):
        return self.cfx.current_url()

    def click(self, sel):
        self.cfx.click_selector(sel)

    def key_type(self, sel, text):
        self.cfx.click_selector(sel, pace=False)
        self.cfx.post(f"/tabs/{self.cfx._tab()}/type",
                      {"userId": self.cfx._uid(), "selector": sel, "text": text})
        self.cfx.press("Tab")

    def fill(self, sel, text):
        self.cfx.post(f"/tabs/{self.cfx._tab()}/type",
                      {"userId": self.cfx._uid(), "selector": sel, "text": text, "mode": "fill"})

    def dismiss_cookies(self):
        try:
            self.cfx.dismiss_cookie_banner()
        except Exception:  # noqa: BLE001
            pass

    def clear_cookies(self):
        # camofox has no clear-cookies endpoint (POST /sessions/:uid/cookies only imports) and
        # DELETE /sessions/:uid would log every other board out. So: server-side sign-out
        # (drops the httpOnly auth cookies), then expire every JS-visible Reed cookie and
        # wipe Reed storage, which is where the stuck OTP step lives.
        self.goto(SIGNOUT_URL)
        self.goto(HOME_URL)
        self.js(_CLEAR_JS)


class CdpPage:
    """Local Edge/Chrome over CDP (the documented local-browser fallback)."""

    def __init__(self, endpoint):
        from playwright.sync_api import sync_playwright  # noqa: PLC0415
        self._pw = sync_playwright().start()
        self.ctx = self._pw.chromium.connect_over_cdp(endpoint).contexts[0]
        pages = [p for p in self.ctx.pages if "reed.co.uk" in p.url]
        self.pg = pages[0] if pages else self.ctx.new_page()

    def goto(self, url):
        self.pg.goto(url, wait_until="domcontentloaded", timeout=90000)
        self.pg.wait_for_timeout(2500)

    def js(self, expr):
        return self.pg.evaluate(expr)

    def url(self):
        return self.pg.url

    def click(self, sel):
        self.pg.locator(sel).first.click(timeout=10000)

    def key_type(self, sel, text):
        self.pg.locator(sel).click()
        self.pg.keyboard.press("Control+A")
        self.pg.keyboard.press("Backspace")
        self.pg.keyboard.type(text)
        self.pg.keyboard.press("Tab")
        self.pg.wait_for_timeout(150)

    def fill(self, sel, text):
        self.pg.locator(sel).fill(text, timeout=5000)

    def dismiss_cookies(self):
        for label in ("Reject All", "Accept all cookies"):
            try:
                self.pg.get_by_role("button", name=label).click(timeout=2000)
                return
            except Exception:  # noqa: BLE001
                pass

    def clear_cookies(self):
        import re  # noqa: PLC0415
        try:
            self.ctx.clear_cookies(domain=re.compile(r"(^|\.)reed\.co\.uk$"))
        except TypeError:  # Playwright < 1.43 has no filter: clearing all is the only option
            print("  WARN old Playwright — clearing ALL cookies in this profile", file=sys.stderr)
            self.ctx.clear_cookies()
        self.goto(HOME_URL)
        self.js(_CLEAR_JS)


_CLEAR_JS = r"""(function(){
  var n=0, hosts=[location.hostname, '.'+location.hostname, '.reed.co.uk', 'reed.co.uk'];
  document.cookie.split(';').forEach(function(c){
    var k=c.split('=')[0].trim(); if(!k) return;
    hosts.forEach(function(h){
      document.cookie=k+'=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/; domain='+h;
    });
    document.cookie=k+'=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/'; n++;
  });
  try{localStorage.clear();}catch(e){} try{sessionStorage.clear();}catch(e){}
  return n;
})()"""


def _visible_js(sel):
    return ("(function(){var e=document.querySelector(%r);"
            "return !!(e && e.offsetParent!==null);})()" % sel)


def _mark_text_js(text, tag):
    """Tag the smallest element whose text is exactly `text` so a TRUSTED click can hit it."""
    return ("(function(){var e=[...document.querySelectorAll('a,button,span,div')]"
            ".find(x=>x.childElementCount<3&&(x.innerText||'').trim()===%r);"
            "if(!e)return false;e.setAttribute('data-reed-login',%r);return true;})()"
            % (text, tag))


def _set_digits_js(code):
    # Auth0/Passwordless drift (2026-11-17): plain Event('input'/'change') leaves the
    # Verify button disabled — React's OTP widget commits on InputEvent with
    # inputType='insertText' plus a keyup. Verified live: all four digits bind and
    # the button enables.
    return ("(function(ids,code){var s=Object.getOwnPropertyDescriptor("
            "HTMLInputElement.prototype,'value').set;var n=0;"
            "ids.forEach(function(id,i){var el=document.getElementById(id);if(!el)return;"
            "s.call(el,code[i]);"
            "el.dispatchEvent(new InputEvent('input',{bubbles:true,"
            "inputType:'insertText',data:code[i]}));"
            "el.dispatchEvent(new KeyboardEvent('keyup',{key:code[i],bubbles:true}));"
            "n++;});return n;})"
            "(%r,%r)" % (list(DIGIT_IDS), code))


_VERIFY_ENABLED_JS = ("(function(){var b=document.querySelector(%r);"
                      "return !!(b && !b.disabled && b.getAttribute('aria-disabled')!=='true');})()"
                      % VERIFY_SEL)


def _signed_in(page):
    page.goto(APPS_URL)
    if on_login_page(page.url()):
        return False
    txt = page.js("document.body ? document.body.innerText : ''") or ""
    return "Sign out" in txt


def _click_text(page, text, tag):
    if page.js(_mark_text_js(text, tag)):
        page.click(f'[data-reed-login="{tag}"]')
        return True
    return False


def _address(cli_email):
    if cli_email:
        return cli_email
    path = os.path.join(ROOT, "ats-credentials.csv")
    try:
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if (row.get("site") or "").strip().lower().startswith("reed") \
                        and "@" in (row.get("email") or ""):
                    return row["email"].strip()
    except OSError:
        pass
    try:
        return ei._creds()[0]
    except Exception:  # noqa: BLE001
        return ""


def request_code(page):
    """Snapshot the mailbox, then fire the explicit request. Returns (base_uid, requested_at)."""
    base_uid = mailbox_max_uid()
    requested_at = datetime.now(timezone.utc)
    page.click(SEND_SEL)
    return base_uid, requested_at


def resend_code(page):
    base_uid = mailbox_max_uid()
    requested_at = datetime.now(timezone.utc)
    if not _click_text(page, "Send code again", "resend"):
        return None
    return base_uid, requested_at


def commit_code(page, code):
    page.js(_set_digits_js(code))
    time.sleep(0.6)
    if page.js(_VERIFY_ENABLED_JS):
        return "setter"
    for sel_id, ch in zip(DIGIT_IDS, code):
        page.key_type("#" + sel_id, ch)
    time.sleep(0.6)
    return "keyboard" if page.js(_VERIFY_ENABLED_JS) else ""


def main():
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--email", default="")
    ap.add_argument("--cdp", default="", help="CDP endpoint of a local browser instead of camofox")
    ap.add_argument("--wait", type=int, default=90, help="seconds to wait for each code email")
    ap.add_argument("--resends", type=int, default=1, help="explicit resends if no code arrives")
    ap.add_argument("--skew-s", type=int, default=60, help="allowed clock skew vs email Date")
    ap.add_argument("--if-needed", action="store_true", help="exit 0 if already signed in")
    args = ap.parse_args()

    address = _address(args.email)
    if not address:
        print("NO_ADDRESS (pass --email or add a reed/imap row to ats-credentials.csv)")
        return 1
    try:
        mailbox_max_uid()
    except Exception as e:  # noqa: BLE001
        print(f"NO_IMAP {e}")
        return 1

    page = CdpPage(args.cdp) if args.cdp else CfxPage()
    if args.if_needed and _signed_in(page):
        print("LOGIN_OK already signed in")
        return 0

    page.clear_cookies()                                   # rule 1
    print("COOKIES_CLEARED", flush=True)
    page.goto(SIGNIN_URL)
    page.dismiss_cookies()
    if not page.js(_visible_js(EMAIL_SEL)):
        # Auth0 drift (2026-11-17): Reed now lands on an Auth0 page defaulted to the
        # REGISTER tab, so #signin_email is hidden until "Already here? Sign in" is
        # clicked. The old "Back to email" label no longer exists. Try both.
        for _n, _txt in enumerate(("Back to email", "Sign in", "Continue with email")):
            if _click_text(page, _txt, f"back{_n}"):
                time.sleep(1.2)
                if page.js(_visible_js(EMAIL_SEL)):
                    break
    if not page.js(_visible_js(EMAIL_SEL)):
        print("STUCK_NO_EMAIL_FIELD url=" + page.url())
        return 2

    page.fill(EMAIL_SEL, address)
    base_uid, requested_at = request_code(page)            # rules 2+3: the explicit request
    print("CODE_REQUESTED", flush=True)
    code = wait_for_code(base_uid, requested_at, args.wait, args.skew_s)
    resends = 0
    while not code and resends < args.resends:
        resends += 1
        req = resend_code(page)
        if req is None:
            print("NO_RESEND_LINK", flush=True)
            break
        print(f"CODE_RESENT {resends}", flush=True)
        code = wait_for_code(req[0], req[1], args.wait, args.skew_s)
    if not code:
        print("NO_FRESH_CODE")
        return 3
    print("CODE_FOUND", flush=True)

    how = commit_code(page, code)                          # rule 4
    if not how:
        try:
            print("OTP_DOM " + str(page.js(
                "JSON.stringify({inputs:[...document.querySelectorAll('input')].map(i=>({id:i.id,type:i.type,len:i.value.length,max:i.maxLength,vis:i.offsetParent!==null})),"
                "btn:[...document.querySelectorAll('button')].map(b=>({id:b.id,t:b.innerText.slice(0,18),dis:b.disabled}))})")), flush=True)
        except Exception as e:  # noqa: BLE001
            print("OTP_DOM_ERR " + str(e)[:80])
        print("VERIFY_DISABLED")
        return 4
    print("DIGITS_COMMITTED via " + how, flush=True)
    page.click(VERIFY_SEL)

    deadline = time.time() + 30                            # rule 5
    while on_login_page(page.url()) and time.time() < deadline:
        time.sleep(2)
    if on_login_page(page.url()):
        print("REDIRECT_TIMEOUT url=" + page.url())
        return 5
    if not _signed_in(page):
        print("SESSION_NOT_ESTABLISHED")
        return 6
    print("LOGIN_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
