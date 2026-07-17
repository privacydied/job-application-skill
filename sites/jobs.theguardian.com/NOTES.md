# jobs.theguardian.com (Guardian Jobs / Madgex) — verified site notes

The UK board for creative / editorial / charity / public-sector roles, on the **Madgex**
platform. Distinct inventory vs the aggregators and — unusually — a **direct on-page apply
form, no board account required**. Wired in `pipeline.py FEEDS` as `guardian`.

## Sourcing (VERIFIED live 2026-07-17)
- Free-text search is the **`?Keywords=` query param**: `/jobs/?Keywords=<terms>` — the
  `/jobs/<what>/` PATH is a **category browse** (`/jobs/design/`), NOT keyword-filtered (both
  return 20/page; only the query param actually filters). Cooldown key: the `Keywords` param
  (parsed case-insensitively — `board_cooldown.query_from_url` only matches lowercase keys),
  else the browse-path segment.
- Result cards are `.lister__item` with `a[href^="/job/<ID>/<slug>/"]`; recruiter/salary/location
  via `[class*=recruiter|salary|location]`. Canonical URL: `/job/<digits>/<slug>/`.
- **Listing pages are bot-walled to plain curl** (0 bytes) — source via camofox.

## ⚠️ Apply section STALE — read references/guardian-board-reality.md instead
The direct on-page `#application-form` flow described below was the Guardian apply path at
the time this NOTES.md was written, but as of 2026-07-17 the **guest** path no longer shows
that form: "Apply on website" redirects to the employer's own ATS (account-gated). The
logged-in Madgex "quick apply" path is *untested and untestable from the agent* (login is
email-OTP gated on `you@example.com`, which the agent can't read). Treat the section below as
historical; the current, authoritative apply-path reality is in
`references/guardian-board-reality.md`.

## ✅ Apply — direct on-page form (`ats_hint: guardian-direct`)
>This section is STALE (see banner above). Left for historical reference only.
"Apply now" is an in-page anchor to `#application-form`. Fields: `firstName`, `lastName`,
`email`, `cv` (file upload — use `atsform.upload("Your CV", "<file>.pdf")`), optional
`coverLetter` (textarea), plus **optional** opt-ins (`cvDatabaseOptIn`, `sendCvForReview`,
`jobAlerts` — leave OFF). Submit button: **"Send application"**. No account/login needed.
- Text fields: set via the native value setter — **use `HTMLTextAreaElement.prototype` for
  the textarea**, `HTMLInputElement.prototype` for inputs (mixing them 500s the evaluate).

## ⚠️ Sourcepoint cookie consent — accept it BEFORE interacting
A Sourcepoint CMP loads as `iframe#sp_message_iframe_<id>` (src `cdn.privacy-mgmt.com`) and
**overlaps the lower reCAPTCHA tiles**. Accept it properly via `cfx.eval_frame` — the button
text is **"Yes, I accept"** (not "Accept all"). **Do NOT hide the consent iframe via CSS** —
hiding its parent chain also collapses the reCAPTCHA widget so the challenge won't render.
Accept → cookie set → it won't reappear that session.

## ⛔ reCAPTCHA v2 gates "Send application" — fingerprint-distrust CAPABILITY GAP
Submitting triggers a reCAPTCHA **v2 image grid** (sanctioned auto-solve per
`references/captcha-policy.md` → `recaptcha.py solve-grid`). BUT on this camofox fingerprint
the widget **distrusts the client**: the checkbox won't self-solve, and while a grid does open
on the first `Send` of a fresh page-load, **correct selections keep advancing rounds without
ever issuing a token** (looped ≥3 identical "cars" rounds, tokenLen stayed 0). This is the
same anti-automation wall as Turnstile/hCaptcha (see `CAPABILITY-GAPS.md`). **Hand the final
reCAPTCHA + Send to the user via noVNC** — a human's real pointer behaviour can pass the
behavioural score that programmatic clicks can't. Everything up to the CAPTCHA is automatable.
- Clean-run recipe (so the grid renders unobscured): fresh navigate → **accept Sourcepoint
  consent first** → fill fields + `atsform.upload` CV → click "Send application" **once** →
  grid opens on the first try → solve OR hand off. Re-clicking Send on a used widget will NOT
  re-open the grid; reload for a fresh widget.
