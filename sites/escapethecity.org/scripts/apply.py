#!/usr/bin/env python3
"""apply.py — resolve + route an Escape the City (escapethecity.org) opportunity to its real
apply destination.

Escape the City has NO in-platform apply form and NO single apply mechanism: each opportunity's
JD page (a Vue SPA) carries a per-listing "Apply" / "Register your interest" CTA that points OUT
to wherever the employer collects applications — verified live 2026-07-21: the Runna "Director of
Product Design" listing routes via a bit.ly shortlink to a **Typeform**; others land on an
employer ATS (Ashby/Greenhouse/Lever/…) or an email. So there is nothing to "fill" here — the
driver's job is to CLASSIFY and ROUTE:

  1. open the opportunity page (browser — the CTA is not in the static HTML),
  2. extract the apply destination (the external CTA href; follow shortlinks like bit.ly → final),
  3. classify it with ats_router:
       * Ashby / Greenhouse  -> GUEST-DRIVABLE: print the exact driver command (build a config,
         then run it against the opened ATS tab),
       * Typeform / Lever / Workday / SmartRecruiters / email / unknown -> route to manual/VNC
         (no shipped driver / anti-bot) — never a false auto-submit.

This converts the escapecity channel from "NO_DRIVER → everything is VNC labour" to "every listing
resolved + routed; the Ashby/Greenhouse-backed ones auto-drive." It never fabricates a submission.

Usage:
    CFX_KEY=.. python3 sites/escapethecity.org/scripts/apply.py <opportunity-url-or-slug> [--json]
Exit: 0 drivable (Ashby/Greenhouse) · 3 recognised-but-manual (typeform/lever/email/…) · 2 error.
"""
import json
import os
import re
import sys
import time
import urllib.request

_here = os.path.dirname(os.path.abspath(__file__))
_COMMON = os.path.join(_here, "..", "..", "_common", "scripts")
sys.path.insert(0, _COMMON)
import cfx          # noqa: E402
import ats_router   # noqa: E402

_BASE = "https://www.escapethecity.org/opportunity/"


def _url(arg):
    if str(arg).startswith("http"):
        return arg
    return _BASE + str(arg).strip("/")


def _ev(js, tab, tries=8):
    for _ in range(tries):
        try:
            v = cfx.evaluate(js, tab=tab)
            if v is not None:
                return v
        except Exception:  # noqa: BLE001
            pass
        time.sleep(1.5)
    return None


def _follow(url, hops=5):
    """Follow redirects (bit.ly and other shortlinks the CTA uses) to the final destination.
    HEAD first, fall back to GET. Returns the final URL (or the input if it can't resolve)."""
    cur = url
    for _ in range(hops):
        try:
            req = urllib.request.Request(cur, method="HEAD",
                                         headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                final = r.geturl()
                if final and final != cur:
                    cur = final
                    continue
                return final or cur
        except Exception:  # noqa: BLE001
            try:
                req = urllib.request.Request(cur, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=15) as r:
                    return r.geturl() or cur
            except Exception:  # noqa: BLE001
                return cur
    return cur


def _apply_destination(tab):
    """Extract the apply destination from the opened JD. Prefer an explicit external CTA href
    ("Register your interest" / "Apply" anchor); fall back to a mailto; return ('', '') if the
    only control is a JS button with no discoverable href."""
    raw = _ev(r"""(function(){
      var out={href:'',mailto:''};
      var els=[...document.querySelectorAll('a,button')];
      // 1) an anchor whose text or context is apply/register-interest, with an external href
      var a=els.find(function(x){var t=(x.innerText||x.textContent||'').trim();
        var h=(x.getAttribute&&x.getAttribute('href'))||'';
        return /apply|register (your )?interest|express interest/i.test(t)&&/^https?:/i.test(h)
          &&!/escapethecity\.org/i.test(h);});
      if(a)out.href=a.getAttribute('href');
      // 2) any external anchor that isn't a social/company-marketing link, as a fallback
      if(!out.href){var soc=/linkedin|tiktok|facebook|twitter|instagram|youtube/i;
        var b=els.find(function(x){var h=(x.getAttribute&&x.getAttribute('href'))||'';
          return /^https?:/i.test(h)&&!/escapethecity\.org/i.test(h)&&!soc.test(h)
            &&!/^https?:\/\/(www\.)?[^\/]*\.(com|org|io)\/?$/i.test(h);});  // skip bare company homepage
        if(b)out.href=b.getAttribute('href');}
      var m=els.find(function(x){var h=(x.getAttribute&&x.getAttribute('href'))||'';return /^mailto:/i.test(h);});
      if(m)out.mailto=m.getAttribute('href');
      return JSON.stringify(out);})()""", tab)
    try:
        d = json.loads(raw) if raw else {}
    except (ValueError, TypeError):
        d = {}
    return (d.get("href") or "").strip(), (d.get("mailto") or "").strip()


def route(arg, as_json=False):
    url = _url(arg)
    if not os.environ.get("CFX_KEY"):
        print("ERROR: no CFX_KEY (escapecity JD is a Vue SPA — needs the browser).", file=sys.stderr)
        return 2
    tab = cfx.open_tab("escapply")
    try:
        cfx.navigate(url, tab=tab)
        time.sleep(6)
        title = _ev("document.title", tab) or ""
        href, mailto = _apply_destination(tab)
    finally:
        try:
            cfx.close_tab(tab)
        except Exception:  # noqa: BLE001
            pass

    result = {"opportunity": url, "title": title, "cta_href": href, "mailto": mailto,
              "final_url": "", "ats": "", "drivable": False, "route": ""}

    if re.search(r"not found|404|no longer", title, re.I):
        result.update(ats="expired", route="listing not found / expired — skip (do not log)")
        _emit(result, as_json)
        return 3
    if not href and mailto:
        result.update(ats="email", route=f"email application to {mailto} — manual/VNC")
        _emit(result, as_json)
        return 3
    if not href:
        result.update(ats="unknown", route="no discoverable apply link (JS-only 'Apply' button) "
                                             "— open in VNC and follow the CTA")
        _emit(result, as_json)
        return 3

    final = _follow(href)
    r = ats_router.classify(final)
    result.update(final_url=final, ats=r["ats"], drivable=r["drivable"])
    if r["drivable"]:
        result["route"] = f"guest-drivable — open {final} in a tab, build the config, run: {r['invoke']}"
        _emit(result, as_json)
        return 0
    result["route"] = f"{r['note']}"
    _emit(result, as_json)
    return 3


def _emit(result, as_json):
    if as_json:
        print(json.dumps(result, indent=2))
        return
    print(f"escapecity: {result['title'] or result['opportunity']}")
    if result["cta_href"]:
        print(f"  CTA: {result['cta_href']}" + (f"  →  {result['final_url']}"
              if result['final_url'] and result['final_url'] != result['cta_href'] else ""))
    tag = "▶ DRIVABLE" if result["drivable"] else "⚠ MANUAL"
    print(f"  {tag} [{result['ats']}]: {result['route']}")


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 2
    return route(args[0], as_json="--json" in argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
