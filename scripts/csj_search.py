#!/usr/bin/env python3
"""csj_search.py — drive the CSJ search form, return a fresh results SID URL.

CSJ search-context SIDs are one-shot + expiry-signed. This regenerates one by
filling the form (what=keyword, where=London) and submitting, then captures the
resulting index.cgi?SID= URL that feed.py needs.

Usage: csj_search.py "<keyword>" [pages]
  prints the SID nav URL to stdout (the value to put in searches.csv csj row / pass to feed.py --nav)
"""
import sys, time, json, re, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "sites", "_common", "scripts"))
import cfx

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

def ev(expr, tries=6):
    for _ in range(tries):
        try:
            r = cfx.evaluate(expr)
            if r is not None:
                return r
        except Exception:
            pass
        time.sleep(2)
    return None

def main():
    keyword = sys.argv[1] if len(sys.argv) > 1 else "design"
    # ensure on CSJ home
    cfx.navigate("https://www.civilservicejobs.service.gov.uk/csr/index.cgi")
    time.sleep(4)
    SET = """(name,val)=>{const e=document.querySelector('input[name="'+name+'"]');if(!e)return 'NO:'+name;const s=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;s.call(e,val);e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));return 'OK:'+name;}"""
    def call(fn, *args):
        aj = "[" + ",".join(json.dumps(a) for a in args) + "]"
        return ev("(" + fn + ").apply(null," + aj + ")")
    print("what:", call(SET, "what", keyword))
    print("where:", call(SET, "where", "London"))
    # submit the search form
    r = ev("""(()=>{const b=document.querySelector('input[name=search_button]');if(!b)return 'NOBTN';b.click();return 'CLICKED';})()""")
    print("submit:", r)
    time.sleep(6)
    # capture the SID URL from the address bar
    url = ev("location.href")
    print("results url:", url)
    if url and "SID=" in url:
        print("SID_URL=" + url)
        return 0
    print("NO_SID_URL")
    return 1

if __name__ == "__main__":
    sys.exit(main())
