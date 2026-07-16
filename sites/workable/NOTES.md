# apply.workable.com (Workable) — site notes (recipe)

External ATS. Form-fill via the shared engine `../_common/scripts/atsform.py`
(standard labelled inputs + resume upload + custom questions, same class as
Greenhouse/Lever — atsform verified on that pattern). **Not live-tested here** —
recipe below; adjust labels from a live field dump if they differ.

## ⛔ The blocker: Cloudflare Turnstile on submit
Workable gates final submit behind **Cloudflare Turnstile** ("Verify you are
human"), which **rejects camoufox's fingerprint** — it fails even for a genuine
human click via VNC (see `../_common/CAPABILITY-GAPS.md`, FE Fundinfo case). So you
can FILL a Workable application fine, but SUBMIT is usually blocked. Expect
`Blocked`, cite that gap. This is NOT the same as reCAPTCHA (which the new
`frameSelector` click can reach) — Turnstile is a fingerprint problem, not a click
problem; `recaptcha.py` does not help here. Before spending time, run `cfx.sh
check-cooldown apply.workable.com`.

## Reaching + filling the form
`apply.workable.com/<company>/j/<id>/` → **Apply** → the form (or `…/j/<id>/apply`).
```
atsform.py fill "First Name" "Jane"          # + Last Name / Email / Phone
atsform.py upload "Resume" <resume>.pdf        # "Upload a file" / "Resume"
atsform.py fill "Cover letter" "@cover.txt"    # or a summary/textarea
atsform.py select "..." "..."                  # custom dropdowns (native or react-select)
atsform.py review "<Company>"
# SUBMIT: expect a Turnstile widget. Per SKILL.md's CAPTCHA directive: STOP, hold the
# filled form, hand to the user. If Turnstile "verification failed" twice, log Blocked.
```
Turnstile can also open as a **popup tab** — `cfx.sh find-popup` before assuming
it's inline (documented in `cfx.sh` header).
