# Scratch probes, secrets, and the "don't re-write it" capability index

Field note from a Hermes CSJ/Workday run (2026-07-14). During debugging, ~15
one-shot `.py` probes were written to `/tmp` (`nav.py`, `csj_applylink.py`,
`wd_*.py`, `broad.py`, …). The lessons below are why they were **not** folded
into the skill — and how to avoid re-deriving them next time.

## Widget capability index (dropdown / combobox strategies)
`atsform.combobox_pick` is the ONE engine that drives every dropdown/combobox (native
`<select>` + all react-select variants) via an interaction LADDER — open with a synthetic
pointer sequence (`pointerdown/mousedown/mouseup`) on the control, else focus+ArrowDown, else
a trusted click, else type-to-filter; read the menu from `aria-controls` OR `.select__menu`
OR global `.select__option`. **Known-working strategies (auto-appended by `probe_widget.py`):**

- **react-select (Greenhouse remix, `select__control` + `aria-controls: null`)** → opens on
  **pointer-mousedown** on the control; options in the global `.select__option` list. Verified
  Vercel `job-boards.greenhouse.io` 2026-07-19 (single-select + `mark all that apply` multi).
- Lever / Ashby / WTTJ / SmartRecruiters use the same react-select library → same
  pointer-mousedown open; a few variants also honour focus+ArrowDown (ladder rung 2).
- Large async country/location typeaheads → rungs 1–3 render nothing; **type-to-filter**
  (rung 4) narrows the list, then the option click commits.

When you meet a widget the ladder can't open, run
`python3 scripts/probe_widget.py "<label>"` — it reports the winning rung (or none) and
appends a row here. A widget is a capability gap to record, **never** a "structural limit"
or a `Blocked` (see `references/camofox-form-filling-pitfalls.md` §doctrine).

### Auto-recorded widget probes (probe_widget.py appends below)

## Rule 1 — a probe must NEVER hardcode credentials
Five of that run's `/tmp/wd_*.py` probes hardcoded Jane's ATS password in
plaintext (`pw = "…"`). **A probe that hardcodes a secret can never be committed**
(it would leak into git history) and must be **scrubbed**, not archived. Read
creds at runtime instead:

```python
import csv, os
def cred(site_substr):
    p = os.path.join(os.path.dirname(__file__), "..", "..", "..", "ats-credentials.csv")
    for r in csv.DictReader(open(p)):
        if site_substr.lower() in r["site"].lower():
            return r["email"], r["password"]
    raise SystemExit(f"no cred row matching {site_substr!r}")
```

`ats-credentials.csv` is already gitignored, so a probe that sources creds from it
stays commit-safe. Same rule for the tab/session key — take `CFX_KEY`/`CFX_TAB`
from the env (via `cfx`), never inline them.

## Rule 2 — before writing a throwaway probe, check this index
Most `/tmp` probes re-implemented something the skill already ships. Re-writing a
throwaway burns the slowest tokens (model round-trips) to re-derive a solved thing.
**Reach for the shipped tool first:**

| You need to… | Use this (don't re-write) |
|---|---|
| nav to a URL + dump title/body/DOM | `sites/_common/scripts/cfx.py` / `cfx.sh nav` + `eval` |
| extract apply buttons/links + the JD from a posting | `sites/_common/scripts/jd.py` |
| check logged-in / session state for a board | `sites/_common/scripts/check_login.py` |
| screen a feed to on-profile roles (title/location/seniority) | `sites/_common/scripts/precheck.py` + `check_title.py` |
| enumerate a board's search results (stable ids + tracker dedup) | that board's `sites/<board>/scripts/feed.py` |
| write/append a tracker row (dedup-safe, update-in-place) | `sites/_common/scripts/log-application.py` |
| **trusted click** on a control that ignores synthetic `el.click()` (React submits) | `cfx.click_and_follow(selector=…)` — NOT `evaluate("el.click()")` |
| set a React-controlled input/textarea/select | native prototype `value` setter + dispatch `input`+`change` (pattern is used across the site scripts) |
| upload a file to an `<input type=file>` | `sites/_common/scripts/upload-file.sh` or `POST /tabs/<tab>/upload` with a `selector` |
| fill a whole ATS form in one pass | `sites/_common/scripts/atsform.py apply <config.json>` |

If a genuinely new capability is missing, add it to the right `sites/<board>/scripts/`
or `_common/scripts/` as a hardened, cred-parametrized helper — **not** a `/tmp`
one-shot — and note it here so the next run finds it.

## Findings worth keeping from that run (fold into the board NOTES)
- **Workday create-account (`myworkdayjobs`)** — synthetic `.click()` **no-ops** on
  Workday's React "Create Account" submit; you must use the **trusted** click
  endpoint: `cfx.click_and_follow(selector="button[type=submit]")`. Stable input
  ids on the create-account form: `input-4` (email), `input-5`/`input-6`
  (password ×2); there is a honeypot `website` field — **leave it empty**. (This is
  the same class of fix as `nav_to_link.py`'s click-drift workaround — both are
  "the DOM needs a real trusted event, not a scripted one.")
- **CSJ "Apply at advertiser's site"** can point at a *generic, non-ATS* careers
  redirect (e.g. a bare `mi5.gov.uk/careers`) rather than a real applyable ATS —
  treat that as **skip**, not a form to drive. A real advertiser link resolves to an
  actual ATS (Workday, Applied, etc.). (See `sites/civilservicejobs/NOTES.md` for the
  advertiser-site external-ATS handling this extends.)
- **combobox** `Will you require Visa Sponsorship` @ `job-boards.greenhouse.io` (role=combobox, aria-controls=None, ctrl=select__control remix-css-13cymwt-control) → opened via **pointer-mousedown**; tried pointer-mousedown=ok, arrowdown=ok, trusted-click=ok [2026-07-19]
