# LinkedIn sourcing playbook — recovering from a "0 fresh" bundled query

Symptom: `feed.py --nav <searches.csv LinkedIn URL>` prints `[]` with the stderr
note about a 12h cooldown, OR it runs but returns only already-tracked ids plus
off-profile promoted cards. The skill's default instinct ("rotate boards") is
usually WRONG on the first pass. The bundled OR-query (`searches.csv`) gets
cooldown-marked the moment a pass finds 0 fresh — but that does NOT mean the board is
exhausted for the week.

Live example (2026-07-13): the bundled 24h OR-query was cooldown-marked by a prior
run; forcing it still returned 24 already-tracked + 1 fresh (a Senior role that fails
the title pre-filter). The 24h window WAS genuinely drained for the targeted titles —
but the 7-day + remote searches then surfaced 17 fresh distinct candidates. So:
confirm exhaustion properly before giving up.

## Recovery sequence (each step is a DISTINCT subset — one empty != the next is)
1. **Force the 24h bundled query** with `--force` to distinguish "cooldown" from
   "truly drained." If it still returns ~0 on-profile fresh, the window really is
   drained for those titles.
2. **Widen the window:** swap `f_TPR=r86400` (24h) for `f_TPR=r604800` (7d) and
   re-run with `--force`. Surfaces postings up to a week old the 24h query missed.
3. **Add the remote filter:** append `&f_WT=2` (remote; 1=onsite, 3=hybrid) to the
   7d query. Different result subset — this run: 17 fresh distinct candidates vs 3
   from the unfiltered 7d search.
4. **Per-title LinkedIn searches:** run single-title queries
   (`keywords=UX%20Researcher`, `Service%20Designer`, `Content%20Designer`,
   `Design%20Systems%20Designer`, `Web%20Designer`, `Visual%20Designer`,
   `Interaction%20Designer`, `Digital%20Designer`, `Junior%20Product%20Designer`),
   each as its own `--nav --force`. CRITICAL: each `keywords=` value is its OWN
   cooldown key in `board-cooldown.csv`, so these are NOT blocked by the bundled
   query's cooldown and they catch titles the OR-bundle may have deduped against.
5. **Only after steps 1-4 yield nothing** mark LinkedIn dry and rotate boards.

## Indeed as the fallback (guest-browsable, no login)
- Indeed's OR-bundle degrades to loose matching (see `searches.csv` note), so prefer
  **PER-TITLE single-phrase** searches (`q=UX+Designer`, `l=London`, `fromage=7`).
- Indeed returns heavy OFF-PROFILE noise. Screen hard:
  - `Frontend Developer` / `Full Stack` / `Staff/Lead Engineer` — not design.
  - `Lecturer in Graphic...` / `BIM & Visualisation Artist` / `3D 4D Designer` —
    not product/UX.
  - **`Design Engineer` is a MECHANICAL/STRUCTURAL role** — `check_title.py` false-
    matches its regex "design engineer" to Tier A. Screen these out by hand; they are
    NOT UX/product design.
  - Run every fresh Indeed id through `check_title.py`, then manually confirm the
    title is a real design/UX/research role before opening.
- Location default is London; remote-UK roles still render as "Remote" — keep them.

## Parsing `feed.py` output
`feed.py` prints log lines (`[feed] searching...`, cooldown notes, `N FRESH jobs`)
interleaved with a JSON array. The array is NOT the first `[` — the log line
`[feed] ...` also starts with `[`. Robust parse:
```python
import json, re
t = open(path).read()
m = re.search(r'\[\s*\{', t)        # anchor on the REAL array (starts with [{)
sub = t[m.start():]
rows = json.loads(sub[:sub.rfind(']')+1])
```
Do NOT anchor on `(?m)^\[` — it matches the `[feed]` log line and `json.loads`
then fails with `Expecting value: line 1 column 2`.

## cfx.sh vs cfx.py command surface
- `cfx.sh` has the interactive verbs: `nav`, `snap`, `click`, `type`, `press`,
  `scroll`, `shot`, `eval`, `eval-frame`, `click-selector`, `click-frame`,
  `click-xy`, `open-tab`, `close-tab`, `list-tabs`, `find-popup`,
  `record-captcha-fail`, `check-cooldown`.
- `cfx.py` is primarily a **LIBRARY** (site scripts `import cfx`); its CLI surface is
  limited (`list-tabs`, `click-follow`). It does NOT implement `nav`, `click`,
  `eval`, or `shot` — those live in `cfx.sh`. Driving a posting by hand uses `cfx.sh`;
  `cfx.py` is what `feed.py` / `easyapply.py` import.
- `python3 sites/_common/scripts/cfx.py click-follow <ref>` is the correct way to
  click an external-ATS "Apply" button — it auto-dismisses LinkedIn's "Share your
  profile?" consent dialog. A plain `cfx.sh click` on that button does NOT clear the
  consent modal.
