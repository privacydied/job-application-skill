# Camofox session stability — tab cap, key hazard, recovery (2026-07-14)

Operational lessons from a run that wedged the engine and wasted ~30 tool calls.
Read BEFORE writing any script that opens camofox tabs or drives `cfx` from raw Python.

## 1. The ~8-tab wedge (root cause of "Internal server error" / "tab not created")
The engine caps at roughly **8 live tabs**. Above that, `POST /tabs` starts returning
`{"error":"Internal server error"}` and existing navigations 500/410 even though
`GET /tabs` may still report 1 tab. Symptom: feed scripts print `ERROR nav: … HTTP 500`
or `open_tab: tab not created (last response {})`, and `cfx` reads return `410 Tab no
longer exists (browser was restarted)`.

**Cause observed live:** launching 5 *parallel* background sourcing scripts, each
opening its OWN tab, blew past the cap and wedged everything.

**Fix:** on the Hermes autonomous path, **source SERIALLY on ONE reused tab** (the
intended Hermes pattern reuses one tab across postings — do NOT open a tab per
process). One background process at a time. Close stray tabs first (see §3).

## 2. The `.jobenv` stale-key hazard
The committed `.jobenv` may carry a **stale/wrong key**. Symptom that betrays it:
`GET /tabs` (read) works, but `POST /tabs` (navigate/open) returns `HTTP 401
Unauthorized`. The live 64-char bearer token lives in **`.jobenv.run`** in the same
dir. Rule: if `POST /tabs` 401s, copy `CFX_KEY` from `.jobenv.run` into `.jobenv`
(and keep `CFX_USER=nasirjones`, `CFX_URL=http://localhost:9377`). A GET working but
POST 401ing is the tell — do not assume the engine is down.

## 2b. SNAPSHOT REF FORMAT: `[eN]`, NOT `@eN` (learned 2026-07-15)
`cfx.sh snap` tags interactive elements as **`[eN]`** (square brackets, `e` prefix,
**no `@` sign**) — e.g. `- button "Apply now" [e18]`, `- link "Apply Now" [e30]`.
Do NOT grep for `@e[0-9]+` — that pattern matches NOTHING and silently yields an
empty ref, which then forces the fragile `cfx.sh eval "...click()"` fallback that
500s (the camofox click-wedge). **Extract with `grep -oE '\[e[0-9]+\]'` and strip the
brackets, then `cfx.sh click eN` directly** — that is the reliable path. A
correct-ref `click eN` returning `{"ok":true,"url":...}` but NOT advancing the page =
a real board wedge (not your bug) — see `cv-library-apply-notes.md` / the Adzuna and
CSJ notes. (Confirmed 2026-07-15: spending 13+ passes grepping `@e` produced empty
refs and wedging eval-clicks; switching to `[eN]` extraction + `click eN` worked on
Reed immediately and, on CVLibrary/Adzuna, correctly proved the wedge is real rather
than a ref-extraction artifact.)

## 3. Tab recovery + health
- Live-tab list: `python3 sites/_common/scripts/cfx.py list-tabs` (returns a bare
  list). Or raw `GET /tabs?userId=nasirjones` → `{"running":true,"tabs":[…]}` (a DICT,
  not a list — handle both shapes). **CAVEAT: this `GET /tabs` endpoint is itself the
  one that HANGS during the TAB-API WEDGE (see `camofox-backend-recovery.md`) — when it
  times out, don't trust `list-tabs()`; create a tab via the raw `POST /tabs` workaround
  there instead.**
- Reopen a live tab if camofox restarted: `python3 sites/_common/scripts/cfx.py ensure-tab`
  (reuses `CFX_TAB` or opens a fresh one and prints it).
- Close all stray tabs (when wedged): loop `cfx.close_tab(tab_id)` for every
  `list-tabs` entry, then `ensure-tab` one fresh tab. `close_tab` needs `userId` —
  use `cfx.py close-tab <id>` (it passes userId), NOT a raw `curl -X DELETE` (that
  omits userId and silently no-ops). **Verified live: a wedge at the ~10-tab cap is
  cleared by force-closing ALL tabs (loop the curl `DELETE /tabs/<id>?userId=nasirjones`
  for every id `GET /tabs` lists) THEN opening ONE fresh tab — this drops `activeTabs`
  back to 1 and un-wedges the API.**
- Health: `curl -fsS -H "Authorization: Bearer $CFX_KEY" $CFX_URL/health` →
  `browserConnected:true`. Watch `activeTabs` — if it climbs toward 8, stop opening more.

## 3b. PATCH `.jobenv.run` AFTER EVERY TAB CHANGE (Hermes path gotcha)
On the Hermes path the live `CFX_TAB` lives in `.jobenv.run`, and many driving
scripts `source .jobenv.run` at launch. **When a tab dies and you reopen one, you
MUST persist the new id into `.jobenv.run` or the next `source` uses the stale (dead)
id and every nav 404s.** Two ways to persist, ONE of them is broken:

- ❌ **In-script `open('.jobenv.run').write(...)` FAILS** — a permission/quirk means a
  Python `write()` to `.jobenv.run` inside `cfx.heal_tab` / a driver does NOT actually
  change the file (the write is swallowed; the on-disk id stays stale). Verified live:
  `heal_tab()` reopened a tab and printed it, but `.jobenv.run` still held the old id
  and the next `cfx.navigate` 404'd.
- ✅ **Use the `patch` tool (or `sed -i`) to rewrite `export CFX_TAB='…'` in
  `.jobenv.run`** — that actually persists. Pattern used all session: capture the new
  id from `cfx.ensure_tab()`/`POST /tabs`, then
  `python3 -c "…re.sub(r'CFX_TAB=.([^']+)',new)…"` writing the file, OR edit via the
  `patch` tool. Verify with `grep CFX_TAB .jobenv.run` before the next driving call.
- **`cfx._tab()` reads `os.environ['CFX_TAB']` live**, so `heal_tab()` updating the
  in-process env IS enough *within one driver process* — but a SEPARATE background
  batch that `source`s `.jobenv.run` at start needs the on-disk file updated too.

## 4. `cfx.py` subcommands (NOT `nav` / `eval` / `close-tab`)
The Python `cfx.py` CLI uses: `list-tabs`, `ensure-tab`, `open-tab [url]`,
`find-popup`, `dismiss-cookies`, `click-follow <ref>|--selector <css> [--no-heal]`,
`eval-frame <frameSelector> '<js>'`, `check-engine`, `restart-engine`. There is no
`nav`/`eval`/`close-tab` subcommand — drive navigation via the REST
`POST /tabs/<id>/navigate` endpoint or `click-follow`.

## 5b. Late-session degradation — "NO APPLY BUTTON" can be a dying engine, not external-route
After a long run (many `open-tab`/`restart-engine` calls, the camofox backend
starts degrading: `cfx.sh snap` **times out at 90s**, `eval` returns empty,
and `shot` renders **near-black blank** frames. Symptom chain seen live
(2026-07-16, a 15+-pass Reed session): `tcsetattr: Inappropriate ioctl`
errors on fresh tabs, then `snap` 90s timeouts, then blank `shot` frames.

**The trap:** a real on-profile role then reads "NO APPLY BUTTON" / renders blank —
which LOOKS like an external-route/premium posting, but is actually the engine
being unable to paint the page. Before concluding "external-route, skip it",
**re-probe on a genuinely-fresh engine**: `restart-engine()` → open ONE new
tab → `cfx.sh nav <job url>` → `shot` → vision-check for the Apply button.
If the fresh-engine shot ALSO shows no Apply button (and the card text/title IS present),
it is genuinely external-route. If the fresh-engine shot renders the button, the
earlier reading was backend death — retry the apply on the healthy tab.

**Rule of thumb:** 2+ consecutive `snap` timeouts or blank `shot` frames in one
session = engine is degrading, not that every remaining posting is unapplyable.
Restart + one clean tab before declaring any "exhausted / external-route only" ceiling.
(Separate concern from §1's ~8-tab wedge: that 500s on OPEN; this is
post-open render death after a long session — both clear via restart + one fresh tab.)
Reuse one tab; on any 500/410 in the loop, call `ensure-tab` and retry; parse
feed.py output as whole-stdout-or-first-`[…]`-block (see
`references/feed-scripting-pitfalls.md` — feed.py prints a text line *before* the JSON
array, so `json.loads(p.stdout)` fails). Cap concurrency at ONE tab.
