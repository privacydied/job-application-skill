# CSJ — login, posting-ID extraction, and the evaluate wedge

Verified 2026-07-15 while unblocking CSJ as the big-volume board after LinkedIn EA
exhausted. These are the missing mechanical steps between "feed.py works" and
"tal_eform.py / tal_sec2.py can run" — the gaps the main SKILL.md + `csj-tal-eform-notes.md`
don't close.

## 1. Login (credentials live in `ats-credentials.csv`, NOT `.env`)

Row `civilservicejobs.service.gov.uk` holds `you@example.com` + password. To apply you
MUST be logged in — the live CSJ tab often shows "Sign in to your account" (not logged in)
even though the session profile carries other boards.

Verified recipe (drive the live browser via `cfx.evaluate`, reusing ONE tab):

1. Navigate to any CSJ page; click the **"Sign in to your account"** anchor
   (`[...document.querySelectorAll('a')].find(x=>/sign in to your account/i.test(x.innerText))`).
   This lands on the sign-in page (title `Sign in - Civil Service Jobs`).
2. Fill email + password. The sign-in form's inputs are dynamically named — select by
   type/label, not id:
   - email: `inp.find(i=>/email|username|login/i.test(i.name+i.id+i.placeholder+i.type))`
   - password: `inp.find(i=>/password|pass/i.test(i.name+i.id+i.placeholder))`
   - set via `el.value=...; el.dispatchEvent(new Event('input',{bubbles:true}))`
   - read password from `ats-credentials.csv` (never hardcode in a script or screenshot).
3. Click submit (`input[type=submit],button[type=submit]` or the first `button`) →
   `b.click()`.
4. **Success check:** after submit, `document.title` → `Civil Service job search` and the
   header shows **"Account details"** + **"Sign out"** (not "Sign in to your account").

> NOTE: the SKILL.md bootstrap bullet mentions `csr/login.cgi` + `password_login_window` +
> `login_button`. That path did NOT match the live form this session — the "Sign in to your
> account" link → standard email/password page is what actually works. Prefer it.

## 2. Extracting posting IDs from search results

CSJ result cards do **NOT** link to `jobs.cgi?jcode=<id>` directly. They link to
`index.cgi?SID=<base64>` where the base64 decodes to a query string containing
`joblist_view_vac=<digits>` (the vac ID == jcode). So:

```python
import base64
def vac_from_card_href(href):
    s = href.split('SID=')[1].split('&')[0]
    dec = base64.b64decode(s + '=' * (-len(s) % 4)).decode('utf-8', 'ignore')
    return ''.join(c for c in dec.split('joblist_view_vac=')[-1][:12] if c.isdigit())
# stable URL to open / hand to tal_eform:
stable = f"https://www.civilservicejobs.service.gov.uk/csr/jobs.cgi?jcode={vac}"
```

Keyword-OR in the What box returns 0 results ("analyst OR support" → 0; single keyword
"analyst" → 31). Use single keywords, not OR bundles, when driving the search form.

## 3. The CSJ `evaluate` wedge (distinct from the concurrent-tab wedge)

`cfx.evaluate` with any non-trivial JS (e.g. `Array.from(document.querySelectorAll(...)).map(...)`
over result cards) **intermittently HTTP 500s on CSJ pages** — even though `document.title`
still evaluates fine and reducing the tab count to 1 did NOT clear it. This is a CSJ-page
interaction flake, not the ~10-tab concurrent wedge (camofox-concurrent-tab-wedge.md).

Reliable fallbacks, in order:
1. **Retry the evaluate 2–3×** with a short sleep — often transient; a single `None`/500 on
   a large payload is a flake (re-read with a small query before concluding session death).
2. **Screenshot + vision avoids evaluate entirely.** `python3 sites/_common/scripts/cfx.py
   shot /tmp/csj.png` works even when evaluate is wedged; `vision_analyze` reads titles /
   visible links / "logged in as Jane Doe" state off the image. Use this to confirm
   login state and to eyeball result counts when DOM extraction is blocked.
3. Navigate the tab to a fresh URL (e.g. back to the search form) and retry — a nav sometimes
   clears the wedge for the next evaluate.

Do NOT conclude CSJ is "down" from a wedged evaluate — confirm with a screenshot first.

## 4. The apply handshake — reaching the TAL eform (the part that was actually blocked)

`feed.py` gives you vac IDs; `tal_eform.py` needs the eform. The bridge — getting from a
posting advert to the live `cshr.tal.net/.../eform/<ID>/page/1` URL — is NOT documented and
was the real wall this session. Here is the verified path (all on the ONE reused, logged-in
tab):

1. **Open the stable advert URL** (from §2): `cfx.navigate("https://www.civilservicejobs.service.gov.uk/csr/jobs.cgi?jcode=<vac>")`, `sleep 5`. The advert page shows a green **"Apply now"** button (right side, below the dept logo) and an "Apply and further information" link in the Contents list.
2. **Click "Apply now" with a MINIMAL `.click()` evaluate — NOT `click_and_follow` selectors, NOT `cfx.click_selector`.** The wedge only hits *complex array-map* expressions; a single `document.querySelector(...).click()` works reliably:
   ```python
   cfx.evaluate("document.querySelector(\"input[type=submit][value*='Apply']\").click()")
   ```
   `click_and_follow(selector="input[type=submit][value*=Apply]")` reports `no_change` (it
   doesn't capture the SPA transition) — ignore it; the click still fired. After `sleep 4`
   the URL is now `cshr.tal.net/.../eform/<ID>/page/1` (the TAL Application Guidance page).
3. **Advance the SPA via Continue — URL does NOT change.** TAL is a Knockout SPA: each page
   saves on Continue and the URL stays `.../page/1` (per `csj-tal-eform-notes.md`). A minimal
   evaluate finds + clicks the exact Continue button (don't use a `for` loop that `return`s
   on the first non-matching button — that was a bug this session that made it look like the
   click did nothing):
   ```python
   cfx.evaluate("""(function(){
     var bs=document.querySelectorAll('button,input[type=submit]');
     for(var i=0;i<bs.length;i++){
       var t=(bs[i].innerText||bs[i].value||'').trim().toLowerCase();
       if(t==='continue'){bs[i].click();return 'clicked#'+i;}
     }
     return 'no-continue';
   })()""")
   ```
   After the Guidance page Continue, `document.title` becomes `"Eligibility - Civil Service
   Jobs"` — that's your confirmation the chain advanced. Repeat per page (Eligibility ->
   Personal information -> Diversity monitoring -> Declaration).

   **⚠️ NAVIGATION (Continue clicks) is safe to hand-drive this way. FIELD WRITES ARE NOT.**
   Ad-hoc `el.value = x` / bare radio `.click()` update the **DOM** but NOT Knockout's
   **viewmodel**, so the SPA saves them blank and the final submit rejects with
   *"There is a problem — The following form pages have problems…"*. **Always fill fields via
   `tal_eform.py <spec.json>`** (its prototype-setter updates the model). See the CORRECTION
   block in `csj-eform-camofox-wedge.md`. Do NOT hand-write field values by evaluate.

> WEDGE RULE THAT MADE THIS WORK: `cfx.evaluate` 500s on **complex** expressions (anything
> with `Array.from(...).map(...)` / `.filter().map()` over many nodes). It does NOT 500 on a
> single `document.querySelector(...).click()` or `document.title`. So: do ALL CSJ navigation
> as minimal single-expression evaluates (clicks + `document.title` checks) and use
> `shot`+vision for anything that would need a complex DOM read. This is how you drive a full
> CSJ application without ever hitting the wedge.
> **A 500 returned from a `.click()` evaluate does NOT mean the click failed** — the DOM click
> fires before camofox serializes the response, so the action lands even when the HTTP call
> errors. Verify *navigation* with a separate minimal read (`document.title`); the title
> changing confirms the click landed. **But do NOT treat a DOM `.value`/`:checked` read as
> proof a FIELD was saved** — those read the DOM, not Knockout's viewmodel (see the CORRECTION
> block in `csj-eform-camofox-wedge.md`). The real proof a field persisted is the **absence of
> the "There is a problem" banner** after Continue. Field writes belong in `tal_eform.py`, not
> hand-evaluate.
> **If the wedge persists on a CSJ TAL page after retries + fresh tab:** call `cfx.restart_engine()`
> (self-serviceable via NOPASSWD sudoers — see camofox-concurrent-tab-wedge.md). VERIFIED
> 2026-07-15: a `datafield_44636_1_1` nationality-radio wedge that survived fresh-tab + 5× retries
> cleared after `restart_engine()`; subsequent minimal evaluates + clicks worked and advanced the
> Eligibility form. Do NOT report "restart needs your permission" — it does not on this host.

4. **Then hand off to the drivers** — once you're on the eform, `tal_eform.py <eform_base_no_slash>
   <spec_s1.json> --submit` (Section 1) and `tal_sec2.py <sec2_base> <spec_s2.json>` (Section 2)
   take over. Build the spec from `references/applicant-profile.md` (ethnicity = [your ethnicity];
   socio-economic = "Prefer not to say"; eligibility "Are you already a civil servant?" = No ->
   forces Home-department select + Other-organisation text). Section 2 needs Jane's tailored
   personal + 4 behaviour statements (generate from his profile/CV; no pre-shipped file).
   Map the eform's pages first (`/page/N` for N=1..8, dump fields) before writing the spec —
   page counts differ per role (UKEF 3, OFGEM 5, CPS 4).
