#!/usr/bin/env python3
"""Drive one Ashby application via the proven primitives, bypassing the buggy
pre-submit `check()` (which mis-reads Ashby's native-set radios as unanswered).
Sequence mirrors ashby.apply() minus check(): navigate, reveal, upload CV,
fill facts, set required radios, submit, capture+log proof.

Usage: python3 runcfg/drive_ashby.py <cfg.json>
Logs Applied only on confirmed submit (formGone + proof screenshot).
"""
import sys, os, json, time
sys.path.insert(0, 'sites/_common/scripts')
sys.path.insert(0, 'sites/ashbyhq/scripts')
import cfx, atsform, ashby

def main():
    cfg = json.load(open(sys.argv[1], encoding='utf-8'))
    url = cfg['url']; company = cfg['company']; role = cfg['role']
    print(f"\n=== {company} | {role} ===")
    r = cfx.goto(url)
    if not r.get('ok'):
        print(f"NAV_FAIL {url}"); return 2
    time.sleep(1.0)
    if ashby.reveal() != 0:
        print("ABORT: form did not reveal"); return 2
    if 'cv' in cfg:
        if ashby.upload_cv(cfg['cv']) != 0:
            print("CV upload failed"); return 4
    # fill text facts
    for lab, val in (cfg.get('fill') or {}).items():
        rc = atsform.fill(lab, val)
        print(f"  fill {lab!r} -> {rc}")
    # set radios (required) - first config radios, then apply-defaults radios via ashby.apply internals
    RTW = "I am a British or Irish Citizen"
    radios = dict(cfg.get('radios') or {})
    # always ensure right-to-work set
    if 'right to work' not in radios:
        radios['right to work'] = RTW
    for q, opt in radios.items():
        rc = ashby.set_radio(q, opt)
        print(f"  radio {q!r} <- {opt!r} -> {rc}")
    # truthful checkboxes (best-effort)
    try:
        rep = atsform.checkboxes_from_profile()
        if rep.get('ticked'):
            print(f"  ticked {len(rep['ticked'])} checkbox(es)")
    except Exception as e:
        print(f"  checkbox note: {e}")
    # submit + confirm
    rc = ashby.submit()
    if rc == 0:
        ashby._capture_and_log(cfg)
        print(f"SUBMITTED+LOGGED {company} | {role}")
    else:
        print(f"SUBMIT_RESULT rc={rc} (not logged)")
    return rc

if __name__ == '__main__':
    sys.exit(main())
