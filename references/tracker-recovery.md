# Tracker Recovery — `application-tracker.csv`

The tracker is the ONLY local record of submitted applications. Losing it does not
un-apply the jobs (they still show on LinkedIn/CSJ), but it destroys the count and
the dedup key. This file is the restore procedure, written after a 2026-07-15 incident
where an inline `open('w')` + raise-after-truncate zeroed a 288-row file; only 74
committed rows survived and ~41 uncommitted LinkedIn rows were unrecoverable.

## THE ONE DANGEROUS PATTERN (never do this)

    with open(p, 'w', newline='') as f:
        csv.writer(f).rows = rows if False else None   # raises AttributeError
        csv.writer(f).writerows(rows)                   # never runs; file already 0 bytes

`open(p, 'w')` truncates immediately. Any exception thrown before `writerows`
(even an unrelated attribute error on a throwaway line) leaves an EMPTY file. The
corruption is silent — the next `wc -l` shows 0.

## SAFE PATTERNS

1. Single row -> always `log-application.py` (loop step 8). Dedup-safe, append-only,
   cannot truncate. Use it even for bulk re-adds (one call per row).
2. Bulk append -> heredoc `cat >>` (append mode, never truncates):
       cat >> application-tracker.csv <<'EOF'
       2026-07-15,Company,Role,Source,url,Applied,Follow-up,notes
       EOF
   A syntax error in the heredoc body aborts BEFORE touching the file — safe.
3. Bulk rewrite -> single `with open(p,'w',newline='')` block. Mutate the list in
   memory FIRST, then `writerows` as the LAST statement with NOTHING between `open()`
   and `writerows` that can raise. Never open in 'w' then run other statements that
   might throw.

## RECOVERY PROCEDURE (after a truncate / partial write)

1. Stop. Do not keep editing the corrupted file.
2. Restore from git HEAD (recovers the last committed baseline):
       git checkout -- application-tracker.csv
       python3 -c "import csv;rows=list(csv.DictReader(open('application-tracker.csv')));print('Applied:',sum(1 for r in rows if r.get('Status','').strip()=='Applied'))"
3. Fallback copies (if HEAD is too old): `application-tracker.csv.bak-audit-*` in the
   skill dir. Pick the newest; git HEAD is usually newer than a `.bak-audit` from a
   prior day.
4. Rebuild lost rows from authoritative live state — do NOT guess:
   - CSJ completions are FULLY recoverable from the live Applications list
     (https://cshr.tal.net/vx/lang-en-GB/candidate/application). It shows every active
     application with Reference / Application ID / Title / Status / Department /
     Last-update date. Extract the table rows via cfx.evaluate:
       [...document.querySelectorAll('table tr')].slice(1).map(r =>
           [...r.querySelectorAll('td')].map(td => td.innerText.trim().replace(/\s+/g,' ')))
       # -> [ref, appId, title, status, dept, closing, lastUpdate, action]
     Map each to a tracker row: Date=lastUpdate, Company=dept, Role=title,
     Source="Civil Service Jobs", URL=jobs.cgi?jcode=<id> (derive from memory or the
     posting search), Status=Applied (CSJ "Application received" / "Invited to ... Test"
     both count as submitted), Notes="CSJ app <appId> (ref <ref>) <status> <date>".
     Ignore ancient (pre-2026) row(s) — historical, not this hunt.
   - ⚠️ **PRIMARY RECOVERY SOURCE: `applications/*/confirmation.txt`** — the durable
     per-application proof store. Every successful submission writes one
     (`apply_ea.py` → `capture_proof_and_log` → `applications/<slug>/confirmation.txt`)
     containing `LinkedIn Easy Apply confirmation for <Company> — <Role>`, the job
     URL, and a SUCCESS proof line ("application sent (auto-advanced)" or
     "clicked:Submit application"). **These live in `applications/`, NOT the tracker
     CSV, so they SURVIVE a tracker wipe.** This is the highest-yield recovery — it
     recovered 38 rows in the 2026-07-15 incident (→ 120 verified Applied, exceeding
     100). Procedure:
       import glob, re, csv, datetime, os
       for cf in glob.glob('applications/*/confirmation.txt'):
           txt = open(cf, errors='ignore').read()
           m = re.search(r'confirmation for (.+?) — (.+?)\n(https?://\S+)', txt)
           if not m: continue
           comp, role, url = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
           dt = datetime.datetime.fromtimestamp(os.path.getmtime(cf)).strftime('%Y-%m-%d')
           # dedupe against existing tracker rows by (Company.lower(),Role.lower()) and URL
           # append only missing ones as: [dt, comp, role, 'LinkedIn', url, 'Applied', 'Follow-up', 'LinkedIn EA success: <proof>']
     Then commit. The 47-proof set covered ~38 new rows after dedup against the
     74-row git baseline. **This single source alone can restore the count past 100.**

   - CSJ completions are ALSO recoverable from the live Applications list
     (https://cshr.tal.net/vx/lang-en-GB/candidate/application). It shows every active
     application with Reference / Application ID / Title / Status / Department /
     Last-update date. Extract the table rows via cfx.evaluate:
       [...document.querySelectorAll('table tr')].slice(1).map(r =>
           [...r.querySelectorAll('td')].map(td => td.innerText.trim().replace(/\s+/g,' ')))
       # -> [ref, appId, title, status, dept, closing, lastUpdate, action]
     Map each to a tracker row: Date=lastUpdate, Company=dept, Role=title,
     Source="Civil Service Jobs", URL=jobs.cgi?jcode=<id> (derive from memory or the
     posting search), Status=Applied (CSJ "Application received" / "Invited to ... Test"
     both count as submitted), Notes="CSJ app <appId> (ref <ref>) <status> <date>".
     Ignore ancient (pre-2026) row(s) — historical, not this hunt.
   - ⚠️ **CORRECTION (prior note was wrong): LinkedIn rows ARE recoverable** — not from
     the throttled LinkedIn "Applied" UI (that redirects to the jobs homepage and
     renders no Applied tab) and not from the Voyager API (403/404 on a throttled
     session), but from the `applications/*/confirmation.txt` proof store above. The
     earlier claim "LinkedIn rows are NOT recoverable once the CSV is lost" was
     disproven 2026-07-15: 38 LinkedIn EA rows were rebuilt from `confirmation.txt`
     after a wipe. Do NOT fabricate rows to hit a count, but DO harvest every
     `confirmation.txt` FIRST — that IS provable. (Side-channels that do NOT help:
     `run-timings.csv` only logs sourcing/screening stages, not applications;
     `.jd-cache/` is job-description caches; `applications/*/apply.json` are prepared
     specs, not completion records.)
   - Order of recovery for a wiped tracker: (1) git HEAD baseline → (2) harvest ALL
     `applications/*/confirmation.txt` → (3) top up from live CSJ Applications list →
     (4) commit. This recovered a verifiable 120 Applied from a fully-truncated file.
5. Commit immediately so the recovery can't be lost again:
       git add application-tracker.csv && git commit -q -m "recover: rebuild N CSJ rows from live account"

## PREVENTION DISCIPLINE

- Commit the tracker after every session's applications (git add application-tracker.csv
  && git commit -m "..."). Uncommitted-session losses stay small. The 100+ goal is real
  on the platforms even if the local CSV is lost — but the record must survive.
- Prefer `log-application.py` over any hand-written file mutation. If you must bulk-edit,
  use pattern 2 or 3 above. The `csv.writer(f).rows = ...` attribute-assignment
  anti-pattern is the specific trap that caused the 2026-07-15 wipe — never use it.
- After restoring, re-verify the count and report the verifiable number honestly.
  Stating "82 verified (74 committed + 8 rebuilt from CSJ account)" is correct; claiming
  the old "115" from memory after a wipe is not — only the platforms prove the rest, and
  you cannot re-prove LinkedIn rows without the Applied history.
