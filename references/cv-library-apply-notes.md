# CVLibrary — apply mechanics & blockers (CORRECTED 2026-07-16)

CVLibrary (`cv-library.co.uk`) is a major UK job board that surfaced as the downstream
of Adzuna's "Apply for this job" redirect during the LinkedIn-off pivot. It holds a
large on-profile junior-mid UX/Service Designer pool the 6 canonical boards miss.

## Inventory (verified 2026-07-15)
- `cv-library.co.uk/jobs/ux-designer/london` → **"Displaying 1–20 of 2,407 jobs"**.
- Each card has an "Easy Apply" tag + green **"Apply Now"** button.
- Agency-heavy (Randstad, Pontoon, Hays) but also direct employers; salaries often
  contract day-rates (£50–£60/hr, £500–£600/day) — junior-mid band, on-profile.

## Reachability
- **No Cloudflare at job level** — individual job pages and search results render fine
  (unlike Indeed's Turnstile). Search-URL nav is picky: use the FORM, not a guessed URL.
  - Form search that works: `input[name=keyword]`="UX Designer" + `input[name=location]`="London"
    (note: `keyword` singular, NOT `keywords`), then `form.requestSubmit()` →
    `/ux-designer-jobs-in-london?search_id=…`.
- Adzuna detail page "Apply for this job" → `cv-library.co.uk/job/<id>/ux-designer?…`
  (confirmed redirect; TotalJobs is the other common downstream).

## BLOCKERS — CORRECTED 2026-07-16 (the "wedge" was a FALSE POSITIVE)

**The 2026-07-15 "CONFIRMED REAL click-wedge" finding was WRONG.** It was a
**camofox BACKEND-DEGRADATION artifact** (same dead-backend era that produced the
false "external-route" Reed calls and the silent `open-tab` auto-nav failure — see
`camofox-open-tab-nav-pitfall.md`). After the backend self-healed, EVERY step the old
note claimed was wedged WORKED:
- `cfx.sh open-tab "about:blank"` → explicit `nav` to the register URL → the
  registration form renders fine.
- Typing email + password + clicking "Register" → advances to **Step 2: Upload CV**
  with NO HTTP 500, NO wedge.

So CVLibrary is **NOT** wedged. The real blockers are:

1. **No account (still true).** `ats-credentials.csv` has NO `cv-library.co.uk` row.
   Register with you@example.com + a strong password at the `/register?id=…` URL
   (the search results gate behind registration — only a `register?id=` link shows
   when logged out). Registration is a 3-step flow: (1) email+password, (2) **Upload
   CV (Required)**, (3) profile details.

2. **CV upload = native file-chooser — camofox REST CANNOT drive it (the real stop).**
   - The `<input type=file name=cv>` only MOUNTS in the DOM after clicking
     "Select file from device" — which opens a **native OS file dialog** camofox's
     REST layer can't satisfy. `document.querySelector('input[type=file]')` returns
     `none` on a fresh page load; it appears only post-click.
   - camofox exposes a file-staging REST endpoint: `POST /tabs/{tabId}/upload`
     (auth: `Authorization: Bearer $CFX_KEY`), body
     `{"userId":"$CFX_USER","tabId":"$CFX_TAB","selector":"input[name=cv]","path":"<name>"}`
     where `path` is **relative to camofox's server-side `/uploads/` dir**, which is
     bind-mounted **read-only** from this skill's `uploads/` dir
     (`<skill-dir>/uploads`).
     So `path` = e.g. `jane-doe-resume-cleo.pdf` (already present there).
     The endpoint returns `{"ok":true,"uploaded":"/uploads/<name>"}` — it STAGES the
     file but does **NOT bind it to CVLibrary's React file input** (the input is
     unmounted until the native chooser fires). So the CV never attaches.
   - No `setFileInputFiles`/CDP path is exposed by cfx.sh/cfx.py; the only file-input
     helper is the `/upload` staging endpoint above, which is insufficient for
     CVLibrary's chooser-gated input.

**Net: CVLibrary registration is achievable, but the mandatory CV upload is blocked by
a native file-chooser camofox can't drive.** 2,407 UX Designer London jobs stay locked
behind it. Unblock = either a camofox file-chooser bridge (e.g. CDP `DOM.setFileInputFiles`
wired into the REST layer) or an account whose CV is already on file.

## Status (2026-07-16)
Hard stop on **CV upload** (native file-chooser limit), NOT on a wedge and NOT on
data-scarcity. Do NOT credit CVLibrary as "exhausted" or "wedged" — it is *blocked on
upload*, distinct from *empty*. The old note's "wedge CONFIRMED REAL" paragraph is
RETIRED; it described a backend-degradation symptom, not a board property.

## If unblocked later
Apply flow is Easy-Apply-style (CV upload + submit, like Reed). Reuse
`reed_apply.py`'s DOM-click + screening-loop pattern as the starting template, swapping
the field set per CVLibrary's form. Capture `applications/<slug>/confirmation.png` and
log via `log-application.py --proof` (mandatory for `Applied`).
