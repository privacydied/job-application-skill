# applygateway.com — site notes

A third-party apply-forwarding ATS reached via Adzuna redirects (and likely other
aggregators). URL shape: `applygateway.com/apply?JobId=<id>&supplierId=<id>`.

## Apply — guest-drivable, but requires setting a password (self-registration)

Fields: `fname`, `lname`, `email`, `phone`, `new-password` (mandatory — this is a real
account registration, not a plain guest form), `postal-code`, `chkDiversity` (optional,
demographic — leave unticked per PII/truthfulness convention), `chkFreelancer`,
`fileSelector` (CV upload), `chkJobMatches` (consent checkbox), cookie-bar checkboxes.

## Gotchas (verified 2026-09-04, Firmdale Hotels Social Media Manager)
- `atsform.py`'s `_load_defaults` / `fill` engine does **not** bind the password field via
  label text — target it directly by CSS id: `atsform.py fill "#new-password" "<pw>"`.
- `atsform.py checkbox "#chkJobMatches" on` returns `NOT_FOUND` (label-text lookup fails
  for this specific checkbox) — use `cfx.click_selector('#chkJobMatches')` directly instead.
- CV upload works fine via the standard `atsform.py upload "#fileSelector" <file>`.
- Submit button text is plain `"Submit"`.
- **Save the self-registered password to `ats-credentials.csv`** (row added:
  `applygateway.com,<email>,<password>,<date> · self-registered via apply flow`) — a future
  application on this board may need to sign back in rather than re-register.
