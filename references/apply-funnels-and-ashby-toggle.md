# Apply funnels & Ashby toggle pitfall

## Platform-gated funnels (skip, don't stop)

Some LinkedIn "Apply on company website" links do NOT lead to a real ATS. They
land on an AI-recruiter / app-platform funnel with **no web application form**:
no CV upload, no name/email fields, no Submit. Examples seen 2026-07-13:
- `jackandjill.ai` — "Talk to Jack" / "Sign up" / "Log in" only. The page says
  "If your profile's a match and <Company> wants to meet, Jill will make the
  intro." Requires human sign-up to a third-party platform + AI screening.
- `jobs.siira.world` — "Sign up to be on our watchlist" / "Download the App" /
  in-app matching + identity verify + contract sign. No web form.

These are **unsubmittable autonomously**. Treat as a per-posting `Skipped`
(reason: "platform funnel — no web application form"), continue to the next
candidate. Not a hard stop, not a CAPTCHA halt. The user may sign up manually.

Also: a LinkedIn "Apply on company website" can redirect to a *different*
LinkedIn listing of the SAME role already `Applied` (cross-post). Dedup + the
tracker catch this as a duplicate `Skipped`.

Recognize the funnel fast: snapshot shows only "Sign up"/"Talk to"/"Log in"/
"Download the App" links and NO `input`/`button[type=submit]` controls.

## Ashby `set-toggle` can set the WRONG field (bug, 2026-07-13)

When a posting renders multiple Yes/No toggle fields inside one shared ancestor
wrapper, `ashby.py set-toggle "<question>" "Yes"` may match a SIBLING field's
`Yes` button (nearest ancestor holding both Yes and No) and report `OK -> Yes`
while the TARGET field is unchanged. Observed: `set-toggle "London office" "Yes"`
returned OK but the field stayed `No`.

Mitigation until the script picks the most-specific box: after every `set-toggle`,
verify with a direct JS read of the field's selected button colour, and if wrong,
click the correct button by label via `cfx.sh eval`:
```js
(() => { const L='London office';
  const f=[...document.querySelectorAll('div')].filter(d=>(d.innerText||'').split('\n')[0].includes(L)&&d.querySelector('button'));
  for(const x of f){const b=[...x.querySelectorAll('button')];const t=b.find(y=>y.innerText.trim()==='Yes');if(t)t.click();} })()
```
Then re-run `check` to confirm. The `submit` path is unaffected — only toggle
*selection* can misfire, so always re-verify toggles (Visa/office/etc.) via
screenshot + `check` before submit.
