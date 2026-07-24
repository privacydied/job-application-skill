#!/usr/bin/env python3
"""probe_required_fields.py — batch-diagnose which REQUIRED react-select fields on a set of
Greenhouse/Ashby apply forms are EMPTY (uncommitted) in the headless camofox session.

WHY (2026-07-24): the Greenhouse headless react-select wall means required combo fields
(Country / Location / "UK Right to Work" / "US Person") often render ZERO options headless,
so `combobox_pick` can't bind them and submit bounces with CODE_MISSING. This probe tells you,
BEFORE driving, which forms have a genuinely-uncommittable required field (headless wall) vs a
fixable config gap. A form whose EMPTY_REQUIRED list contains a consent/RTW field that won't
load is a driver wall, not a fill error — log Blocked, don't loop.

USAGE
  source .jobenv.run && unset CFX_URL CFX_USER
  python3 scripts/probe_required_fields.py <url1> [url2 ...]
  python3 scripts/probe_required_fields.py @/tmp/urls.txt        # one url per line
  python3 scripts/probe_required_fields.py /tmp/feed.json       # harvest JSON -> .url fields

Prints, per URL: EMPTY_REQUIRED=[labels...]. Empty list = all required combos committed
(form is drivable subject to other checks).
"""
import os, sys, time, json
_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(_HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "sites", "_common", "scripts"))
import cfx


def _env():
    for v in ("CFX_URL", "CFX_USER"):
        os.environ.pop(v, None)
    p = os.path.join(ROOT, ".jobenv.run")
    if os.path.exists(p):
        for line in open(p):
            if line.startswith("export CFX_KEY="):
                os.environ["CFX_KEY"] = line.split('"')[1]
            if line.startswith("export CFX_TAB="):
                os.environ["CFX_TAB"] = line.split('"')[1]


def _empty_required():
    return cfx.evaluate(r"""(function(){
      var labs=[].slice.call(document.querySelectorAll('label'));
      var req=[];
      for(var i=0;i<labs.length;i++){
        var l=labs[i];
        if(l.offsetParent===null) continue;
        if(!/\*/.test(l.innerText)) continue;
        var c=l.closest('[class*=control]')||l.parentElement;
        var inp=c?c.querySelector('input[role=combobox]'):null;
        if(!inp) continue;
        var sv=c?c.querySelector('[class*=singleValue]'):null;
        if(!sv || !sv.textContent.trim()) req.push(l.innerText.trim().replace(/\*/g,'').slice(0,40));
      }
      return JSON.stringify(req);
    })()""")


def probe(url):
    r = cfx.goto(url)
    if not r.get("ok"):
        return url, "NAV_FAIL"
    time.sleep(1.2)
    try:
        res = _empty_required()
        req = json.loads(res) if isinstance(res, str) else []
    except Exception as e:  # noqa: BLE001
        req = ["ERR:" + str(e)[:40]]
    return url, req


def main():
    _env()
    urls = []
    for a in sys.argv[1:]:
        if a.startswith("@"):
            urls += [u.strip() for u in open(a[1:]) if u.strip()]
        elif a.endswith(".json"):
            d = json.load(open(a))
            for j in (d if isinstance(d, list) else []):
                u = j.get("url")
                if u:
                    urls.append(u)
        else:
            urls.append(a)
    if not urls:
        print("usage: probe_required_fields.py <url> [url...] | @file | feed.json")
        return 2
    for u in urls:
        url, req = probe(u)
        print(f"{url}\n  EMPTY_REQUIRED={req}")


if __name__ == "__main__":
    sys.exit(main())
