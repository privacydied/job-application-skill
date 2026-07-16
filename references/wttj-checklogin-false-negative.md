# WTTJ — `check_login.py` returns "unknown" for a logged-in session

Captured 2026-07-14.

## Symptom
`python3 sites/_common/scripts/check_login.py wttj` prints
`"verdict": "unknown"` for Welcome to the Jungle even when the camofox tab is
already logged in. The summary line then reads `ambiguous/blocked: wttj`, which —
taken at face value — would trigger a false login-wall stop on a board that is
actually fine to source.

## Reality check that disproves it
Navigate the tab to `https://app.welcometothejungle.com/` and read the page: a
logged-in session shows the dashboard nav (Home / Jobs / Companies / Inbox / You)
and "Inbox" / "You" user-menu controls, plus "Welcome back, Jane". The
`has_user_menu` probe (`!!document.querySelector('[data-testid=notifications], a[href*="/me"], button[aria-label*=account i], .user-menu')`) returns true.

## Rule
Do NOT treat a WTTJ `unknown` verdict from `check_login.py` as a wall. Probe the
app domain directly (dashboard nav + user menu) to confirm; if present, source
normally. Only treat WTTJ as a real login wall if the dashboard shows a Sign-in
control and no user menu.
