#!/usr/bin/env python3
"""Serial driver: apply each candidate in runcfg/queue.json until today's
strict Applied count reaches APPLY_TARGET (default 20). Ashby runs first
(no email-code gate); greenhouse is best-effort. A dead tab is auto-recovered.
Logs every terminal outcome; never fabricates Applied (driver logs it on real
confirmation only)."""
import json, subprocess, sys, os, csv, datetime, time
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(_ROOT)
sys.path.insert(0, os.path.join(_ROOT, 'sites', '_common', 'scripts'))

APPLY_TARGET = int(os.environ.get('APPLY_TARGET', '20'))

def applied_today():
    today = datetime.date.today().strftime('%Y-%m-%d')
    n = 0
    with open('application-tracker.csv', newline='') as f:
        for r in csv.DictReader(f):
            if r['Status'] == 'Applied' and r['Date'] == today:
                n += 1
    return n

def drive(entry):
    ats = entry['ats']
    cfg = entry['json_path']
    if ats == 'greenhouse':
        cmd = ["python3", "sites/greenhouse/scripts/gh_apply.py", cfg]
    else:
        cmd = ["python3", "sites/ashbyhq/scripts/ashby.py", "apply", cfg, "--submit"]
    print(f"\n>>> [{ats}] {entry['company']} | {entry['role']}", flush=True)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=540)
    except subprocess.TimeoutExpired:
        print(f"  TIMEOUT on {entry['role']}")
        return 'timeout'
    out = (r.stdout + r.stderr)[-1800:]
    print(out, flush=True)
    if 'APPLIED_OK' in out:
        return 'applied'
    if 'SKIP_ALREADY_APPLIED' in out:
        return 'skip'
    return 'blocked'

def main():
    meta = json.load(open('runcfg/queue.json'))
    results = {}
    for i, entry in enumerate(meta):
        have = applied_today()
        if have >= APPLY_TARGET:
            print(f"\n*** TARGET MET: {have} Applied today >= {APPLY_TARGET}. Stopping. ***")
            break
        print(f"\n=== progress {i+1}/{len(meta)} | applied_today={have}/{APPLY_TARGET} ===", flush=True)
        # recover tab if camofox reports dead (best-effort)
        try:
            import cfx
            cfx.ensure_tab(persist=False)
        except Exception:
            pass
        res = drive(entry)
        results[entry['slug']] = res
        if res == 'applied':
            print(f"  ++ applied ({applied_today()}/{APPLY_TARGET})")
        else:
            print(f"  -- {res}")
    print("\n=== run summary ===")
    from collections import Counter
    c = Counter(results.values())
    print(dict(c), "applied_today now:", applied_today())

if __name__ == '__main__':
    main()
