import json, subprocess, sys, os
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
cfg = sys.argv[1]
meta = json.load(open('runcfg/queue.json'))
entry = next(e for e in meta if e['json_path']==cfg)
ats = entry['ats']
if ats=='greenhouse':
    cmd = ["python3","sites/greenhouse/scripts/gh_apply.py", cfg]
else:
    cmd = ["python3","sites/ashbyhq/scripts/ashby.py","apply", cfg, "--submit"]
print("RUN", entry['company'], entry['role'], "::", " ".join(cmd), flush=True)
r = subprocess.run(cmd, capture_output=True, text=True)
print(r.stdout[-2500:])
print("RC", r.returncode)
# read proof
appdir = os.path.join("applications", entry['slug'])
print("APPDIR", appdir, os.path.exists(appdir))
