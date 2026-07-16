# Camofox `open-tab "<url>"` auto-nav silent failure

**Severity:** HIGH — silently poisons downstream conclusions (false "NO APPLY
BUTTON" → false "external-route" → false "backend dead" / "exhausted").

**Discovered:** 2026-07-16. Cost ~10 wasted passes in one session; the bug was
only caught when a manual `eval` on a tab created via `open-tab "url"` returned
`innerText.length=0` / `title=""` while the SAME url loaded fine via a separate
explicit `nav`.

## Symptom

`cfx.sh open-tab "https://www.reed.co.uk/jobs/..."` returns a tab id, but the
tab never actually navigates. Evidence:

- `cfx.sh eval "(document.body?document.body.innerText.length:0)+'|'+document.title"`
  returns `0|` (empty DOM, no title).
- `cfx.sh list-tabs` shows the tab with `"url":"about:blank"` even though the
  `listItemId` field holds the URL you passed to `open-tab`.
- Any `apply` run reports `NO APPLY BUTTON` / `STUCK` because the page is blank
  (no Apply button exists on `about:blank`).

The backend process itself is fine — `curl http://localhost:9377/health`
reports `browserConnected:true`. The failure is specifically `open-tab`'s
auto-navigate step not firing.

## Fix

Do NOT rely on `open-tab` to navigate. Split it:

```bash
NT=$(bash sites/_common/scripts/cfx.sh open-tab "about:blank" \
      | grep -oE '[a-f0-9-]{36}' | head -1)
export CFX_TAB="$NT"
echo "CFX_TAB=$CFX_TAB" > .jobenv.persist   # BUT see env-clobber trap below
bash sites/_common/scripts/cfx.sh nav "https://www.reed.co.uk/jobs/..." >/dev/null 2>&1
sleep 9
# VERIFY before doing anything else:
bash sites/_common/scripts/cfx.sh eval "(document.body?document.body.innerText.length:0)+'|'+document.title"
# -> expect e.g. "8706|Business Analyst Jobs in London | Reed.co.uk"
```

A `0|` return = nav did not take; re-`nav` on a FRESH tab.

## Env-clobber trap (compounds the above)

Background subshells that `source .jobenv.persist` fail if that file was written
with `echo "CFX_TAB=..." > .jobenv.persist` (overwrites the WHOLE file, destroying
`CFX_KEY`). Then every `cfx.sh` call dies with
`Set CFX_KEY to the CAMOFOX_ACCESS_KEY bearer token`. Always persist BOTH vars:

```bash
source .jobenv.run   # holds CFX_KEY
cat > .jobenv.persist <<EOF
export CFX_KEY="$CFX_KEY"
export CFX_TAB="$NT"
EOF
source .jobenv.persist
```

## The false-negative chain (so you recognise it next time)

1. `open-tab "url"` → blank tab (silent).
2. Apply driver runs on blank page → `NO APPLY BUTTON`.
3. Agent concludes "this role is external-route / not in-Reed-applyable".
4. After ~20 such roles: "Reed external-route only → Reed exhausted".
5. Later, on a healthy tab via explicit `nav`, the SAME role shows a real
   `Apply now` button → `SUBMITTED`. The "external-route" conclusion was FALSE.

**Rule:** never declare a posting "external-route / no apply button" from a
session where `open-tab` auto-nav may have failed. Verify the load
(`innerText.length > 0`) FIRST.

## `restart_engine()` caveat

`cfx.restart_engine()` wraps a `sudo -n docker compose restart`. If the NOPASSWD
sudoers rule is absent on the host, it returns `"a password is required"` and the
restart silently does NOT happen. The backend can also SELF-HEAL after a long
idle (the wedge clears on its own). So: a `curl /health` showing
`browserConnected:true` while tabs render blank means the process is up but YOUR
tab session is stale — don't loop on restart. Wait ~90s idle, then
`open-tab "about:blank"` + explicit `nav` on a FRESH tab.

## Verification recipe (paste-to-run)

```bash
cd <skill-dir>
source .jobenv.run
NT=$(bash sites/_common/scripts/cfx.sh open-tab "about:blank" | grep -oE '[a-f0-9-]{36}' | head -1)
cat > .jobenv.persist <<EOF
export CFX_KEY="$CFX_KEY"
export CFX_TAB="$NT"
EOF
bash sites/_common/scripts/cfx.sh nav "https://www.reed.co.uk/jobs/business-analyst/london" >/dev/null 2>&1
sleep 10
bash sites/_common/scripts/cfx.sh eval "(document.body?document.body.innerText.length:0)+'|'+document.title"
# expect NON-ZERO innerText + a real title
```
