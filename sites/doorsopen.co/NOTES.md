# doorsopen.co ("Doors Open") — site notes

Music/nightlife/events industry job board (like a niche Indeed for live-music-venue and
promoter companies). Reached this session via an Adzuna → doorsopen.co redirect (The
Columbo Group, Graphic Designer, job 19267). Worth checking again for the music-tech/audio
angle — genuinely on-topic postings (venues, promoters, festivals) live here.

## Apply flow
- Job detail page has its own "Apply Now" button that opens a **Sign up / Sign in modal**
  — an account is required before applying (no guest-apply path observed).
- Signup fields (all plain, no shadow DOM): `input[name=FullName]` (text),
  `input[name=username][type=email]` (email), `input[type=password]` (password),
  a `<select>` for Location (country name text options, e.g. "United Kingdom"), and an
  `input[name=terms]` checkbox ("I agree to the Terms of Use and Privacy Policy").
  Straightforward native-setter `.value=` + `input`/`change` events works for all of them.
- The **Register submit button (`input[type=submit][value=Register]`) renders BELOW the
  visible modal viewport** — a JS `.click()` on it silently no-ops (no error, no
  navigation, modal stays open unchanged). Must `scrollIntoView({block:'center'})` it
  first, then a real coordinate click (`cfx.sh click-xy`) — this is what actually
  triggered form validation and revealed the next step.

## ⛔ Invisible reCAPTCHA v2 gates account creation
After a real button click, the form surfaces "Please confirm you are not a robot." and an
`invisible`-size reCAPTCHA v2 (`recaptcha/api2/anchor?...size=invisible...`) becomes
active. `recaptcha.py click` produced the same **fingerprint-distrust NO-CHANGE stall**
seen elsewhere this session (The Flex/Base360 Ashby form, 2026-09-27) — `aria-checked`
stays false, no image-grid challenge ever opens, no token issues. This is NOT the normal
sanctioned image-grid solve path; per CAPTCHA doctrine, log `Blocked` and do not
tight-retry. Account may or may not exist server-side after this — treat as unconfirmed;
a future attempt should try Sign In with the saved credentials first before re-registering.

## Credentials
Saved to `ats-credentials.csv` (gitignored) under `doorsopen.co` — signup was filled but
not confirmed to have completed past the reCAPTCHA gate.
