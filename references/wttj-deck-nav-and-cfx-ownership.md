# WTTJ deck navigation + cfx.sh ownership (field notes, 2026-07-12)

Two operational lessons from a live run — both apply to every future WTTJ run.

## 1. WTTJ swipe-decks are not lists — don't try to page them

The Home dashboard cards ("All your matches", "Jobs added this week", "Fully
remote", per-theme `?theme=newly-added` decks) open as **single-job swipe
views**. Each shows ONE job with a small row of thumbnail/dot indicators near
the top (just under the deck heading) to switch jobs. There is NO multi-result
list and NO reliable next-arrow.

**Why it's a trap for automation:**
- The deck-switch thumbnails render with zero-size / wrong `getBoundingClientRect`
  when probed via `evaluate` — returns x=0,y=0, or worse, resolves to the
  *company-photo* carousel rather than the job-nav control.
- Coordinate probes (`document.elementFromPoint(x, y)`) at the vision-reported
  thumbnail centers land on the job `<h1>` or the company `<a>` link, never the
  deck control.
- One eval probe returned **HTTP 500** from the camofox server.
- Paging a deck one job at a time cost ~10+ REST calls per posting and stalled.

**UPDATE 2026-07-12 (re-verified same day):** `/jobs?query=Product%20Designer`
also renders as the same swipe deck — DOM probe confirms an 11-item `<circle>`
dot indicator, `data-testid="job-card-v2"` matching only ONE card,
`a[href*="/jobs/"]` finding only 2 in-pane anchors, and no list/grid toggle
anywhere on the page. WTTJ has unified the search and recommendation-deck UIs, so
**WTTJ search results can't be paged either** — the dots are the same
zero-reliable-hitbox elements (SVG circles ~6-11px, no stable click target).

**What to do instead (higher yield, lower effort):**
- Treat WTTJ sourcing as "open individual known JD URLs" only — from a prior
  deck view, a shared link, or a company page.
- Use **Indeed guest search** (no login) and **company careers pages** as the
  actual primary sourcing channel — they paginate predictably, no swipe-deck trap.
- The deck's "Apply with your profile" flow is fine once you're ON a JD page —
  only *browsing the deck to find postings* is the problem.

## 2. cfx.sh can come back root-owned 700

If `sites/_common/scripts/cfx.sh` was written/edited by root, it returns as
`root:root` mode `700`. Running `bash cfx.sh …` as `<your-user>` then fails:
`Permission denied`. Observed 2026-07-12.

**Repair (preferred):**
```bash
chmod +x sites/_common/scripts/cfx.sh
chown <your-user>:<group> sites/_common/scripts/cfx.sh
```
Run from the skill root. Re-test with `cfx.sh list-tabs`.

**REST fallback (when you can't chown mid-run):** the camofox server exposes
the same actions over HTTP at `http://localhost:9377` with
`Authorization: Bearer $CFX_KEY` (the `CAMOFOX_ACCESS_KEY`/`session_key` value
from `~/.hermes/config.yaml` under `browser.camofox`). Useful endpoints:
- `POST /tabs/{tabId}/evaluate`  body `{"userId": "...", "expression": "..."}`
- `POST /tabs/{tabId}/click`     body `{"userId": "...", "ref"|"selector": "..."}`
- `GET  /tabs?userId=...`        list tabs (find the apply tab)

A minimal Python wrapper calling `/evaluate` works when cfx.sh is unusable.
Reuse the native-setter pattern from `sites/welcometothejungle/scripts/set_textarea.py`
for textareas (HTMLTextAreaElement value setter + dispatch input/change).
This bypasses the broken shell script entirely — no need to wait on a chown.

**Root cause:** the skill's "Fix ownership after writing" rule exists precisely
for this; enforce it on every skill-file write, including the shell helper.
