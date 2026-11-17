# Verifying canonical Reed submits

Use when driving Reed with `scripts/reed_apply.py` and turning its reports into proof-backed `Applied` rows.

## Steps

1. Run batches with `CFX_UPLOAD_MODE=inline` when the Camofox server is remote. The script logs `Applied?` on a reported SUBMIT; that status is unconfirmed and is not a strict `Applied`.
2. Verify every reported submit on `https://www.reed.co.uk/account/jobs/applications` with `cfx.py goto` plus an `innerText` check for the company name. Absence from the dashboard means the submit did not land.
3. For confirmed rows, copy the dashboard screenshot into `applications/<slug>/confirmation.png` and upgrade with `log-application.py <Company> <Role> Reed <url> Applied --proof applications/<slug>/confirmation.png`.
4. Dedupe handled postings by canonical job id parsed from the URL (`/jobs/ux-designer/<id>`, `?jobId=<id>`), not by exact URL: the driver logs a canonical URL while the queue holds search URLs, so exact-URL matching makes submitted rows look unhandled.
5. Two genuine attempts ending in `STUCK` or `NO APPLY BUTTON` are a structural wall: log `Blocked` with the concrete reason and prior-art checked, then move on.

## Pitfalls

- `log-application.py` reaps idle tabs after each resolved application, so a `$CFX_TAB` captured before a batch is dead afterward. Run `cfx.py init` in a **fresh shell** and re-source `.jobenv.run` before verification; `init` in the same shell rewrites the pointer file but leaves the shell's stale variable.
- `log-application.py` refuses to downgrade `Applied?` to `Unverified`, and `reed_apply.py` refuses a duplicate submit while the row is `Applied?`. An unconfirmed row therefore stays `Applied?` with a note — do not retry it through the driver.
- A dashboard badge count is not proof for an individual posting; check the company name in the visible applications list.
