# Camofox file-upload REST endpoint (discovered 2026-07-16)

camofox's REST helper (`cfx.sh`/`cfx.py`) has NO `setFileInputFiles`/CDP wrapper, but the
backend DOES expose a **file-staging endpoint** that can place a file into the browser's
upload sandbox so a page's `<input type=file>` can pick it up.

## Endpoint
```
POST /tabs/{tabId}/upload
Authorization: Bearer $CFX_KEY
Content-Type: application/json
{
  "userId":   "$CFX_USER",
  "tabId":    "$CFX_TAB",
  "selector": "input[name=cv]",   # any CSS selector the input matches
  "path":     "jane-doe-resume-cleo.pdf"   # RELATIVE to camofox's server-side /uploads/
}
```
- Returns `{"ok":true,"uploaded":"/uploads/<name>"}` on success, `400` with
  `"path required (relative to /uploads)"` if `path` missing, `404` for bad selector paths.
- The server-side `/uploads/` dir is **bind-mounted read-only** from this skill's
  `uploads/` dir (`<skill-dir>/uploads`)
  per the camofox compose volume:
  `- <skill-dir>/uploads:/uploads:ro`
  So any CV already in `uploads/` is referenceable by bare filename as `path`.

## LIMITATION (critical)
The endpoint **stages** the file but does NOT bind it to the page's file input. It works
only when the target `<input type=file>` is **already mounted and visible** in the DOM at
call time. Many sites (e.g. **CVLibrary**) render the file `<input>` ONLY after the user
clicks "Select file from device" — which fires a **native OS file-chooser dialog** that
camofox's REST layer cannot satisfy. In that case `document.querySelector('input[type=file]')`
returns `none` on a fresh load, and even after staging via `/upload`, the React input
stays unbound → CV never attaches. So this endpoint unblocks uploads only for
input-always-present forms (e.g. straightforward `<input type=file>` rendered at page load),
NOT chooser-gated widgets.

## When you actually need it
- Upload forms where the `<input type=file>` is present on load (verify with
  `eval "document.querySelector('input[type=file]')?.name"`). Stage the CV via this
  endpoint, then the page's own "Upload"/"Continue" button should recognize it.
- If the input only appears post-click (chooser-gated), this endpoint is insufficient —
  the real unblock is a CDP `DOM.setFileInputFiles` wired into the REST layer, or an
  account whose CV is already on file.

## Why there is NO CDP workaround for the camofox tab (verified 2026-07-16)

A session spent ~30 passes trying to break the CVLibrary upload. The decisive checks:

- `curl /tabs/{tab}/setFileInputFiles` → **404**. camofox's REST layer does NOT implement
  CDP `DOM.setFileInputFiles` (there is no route that binds a file to the input).
- The `openapi.json` does not list `/upload` at all — it is an undocumented internal endpoint.
- The CDP debug port `9222` in `compose.yaml` is on a **separate `chrome-cdp` container**
  (`image: ... chrome-cdp ...`, `--remote-debugging-address=0.0.0.0 --remote-debugging-port=9222`),
  NOT the camoufox tab you drive via REST `9377`. `curl http://localhost:9222/json/version`
  is empty / it is a different browser image. So there is **no reachable CDP for the
  camofox tab** — the `9222` port cannot bind a file to your camofox `<input>`.
- noVNC (`6080`) is reachable only when `VNC_BIND=0.0.0.0` + `VNC_PASSWORD` are set, and is
  **view-only** (human viewing). There is no API to drive the VNC mouse/keyboard from a
  script, so you cannot script the native file-chooser through it either.

**Conclusion (superseded 2026-07-16):** the cap WAS at the camofox API boundary — now fixed.

## FIX (2026-07-16): `/tabs/{tabId}/uploadViaChooser` — chooser-gated upload
Added a route to `server.js` (bind-mounted, so a **container restart deploys it** — no
rebuild) that handles the chooser-gated case via Playwright's `filechooser` event:
```
POST /tabs/{tabId}/uploadViaChooser
{ "userId": "...", "trigger": "<CSS selector of the 'Select file' button>",
  "path": "jane-doe-resume.pdf" }   # relative to /uploads
```
It arms `page.waitForEvent('filechooser')`, clicks `trigger`, then `fileChooser.setFiles(path)`
— binding the file WITHOUT the native OS dialog. This unblocks CVLibrary and any
click-to-open-chooser upload. Client helper: `atsform.upload_chooser(trigger, filename)`.

Use `/upload` when the `<input type=file>` is present on load; use `/uploadViaChooser`
(pass the button that opens the picker) when it is chooser-gated. **Deploy: restart the
`camofox-browser` container** (`docker compose -f compose.yaml
restart camofox-browser`) when idle — the edited `server.js` is bind-mounted read-only over
the image's baked copy, so only a restart is needed.
