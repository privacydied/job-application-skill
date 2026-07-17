# Hard Boards Runbook (CSJ / Guardian / NHS / MI5-MI6 / GCHQ / Parliament / TfL / BBC)

Consolidated technique for the "apply 100 more on the HARD, account-gated, multi-page
boards" class of run. Read this BEFORE a hard-board pass — most ceiling/duplicate
problems in the 2026-07-17 run came from skipping the account-login + live-dedup steps.

## 1. LOG IN BEFORE SOURCING — non-negotiable for CSJ
A **not-logged-in CSJ tab silently suppresses inventory**. Symptoms observed 2026-07-17:
`feed.py --what` returns *"could not mint a CSJ SID"* / *"session bounced"*, and a
full family sweep yields 0–7 cards instead of the real ~150–390. The fix is NOT a
new orchestrator — it is **logging in first**.

- Creds live in `ats-credentials.csv` (row `civilservicejobs.service.gov.uk`).
- Open a FRESH tab, navigate `https://www.civilservicejobs.service.gov.uk/csr/login.cgi`,
  fill `input[name=username]` + `input[name=password_login_window]` (native value-setter +
  input/change dispatch), click `input[name=login_button]`.
- Verify the tab shows **"Jane Doe / Applications / Sign out"** (NOT "Sign in to
  your account"). Only then run `feed.py --what` / `pipeline.run()` for CSJ.
- MI5/MI6/GCHQ share one `applicationtrack.com` login (row `applicationtrack.com (MI5)`);
  it was already live this run. Guardian/NHS apply as guests (see walls below).

## 2. Cross-reference the LIVE "Applications" view (avoids duplicate re-apply)
The feed's tracker-dedup regex **misses some already-`Applied` jcodes** — this run it
reported jcodes 2005590 (UKEF Service Designer) and 2005440 (DfE Service Designer) as
"FRESH" even though they were already `Applied` in the tracker AND showing "Application
received" in the live CSJ Applications list. Re-applying a received app just opens the
existing received application (no double-submit path) — wasted turn + tracker churn.

- After login, click **Applications** → capture the app-ID + title + status table.
  That list is the authoritative "do-not-reapply" set.
- Dedup candidate jcodes against BOTH the tracker AND that live list before opening any advert.
- (`log-application.py` matches on Company+Role, not URL — a same-role/different-company
  posting silently merges; pass `--append-new` when the company differs. See SKILL.md §8.)

## 3. Realistic inventory ceiling (measured 2026-07-17, logged-in)
Full CSJ sweep (~582 candidates) → on-profile + not-tracked ≈ **11**. Guardian (~360) →
≈8. NHS → ≈0 on-profile in the sourced families. MI5/MI6 ≈9 cards BUT see §4 (no
confirmable submission). **Total genuinely applyable fresh pool ≈ 28** — far below a
"+100" target. The data-scarcity ceiling is REAL on hard boards; state it once with the
specific unblock (boards 5–8 accounts) and stop padding. Use the canonical
`precheck.py` screen (pipe feed JSON → stdin) — hand-screening 300+ titles silently
bins on-profile Tier A/B roles.

## 4. MI5 / MI6 / GCHQ (applicationtrack.com) — autofill stops BEFORE submit (BY DESIGN)
`sites/applicationtrack.com/scripts/autofill.py` walks the section tracker, fills the
resolvable Yes/No/agree eligibility gates, SKIPS hidden fields, and **deliberately never
submits** — the user-only final page (memorable word + declaration + Submit) is left to
the human. So an applicationtrack pass ends at `needs_human`, NOT a confirmation. **Do not
count these as `Applied`** (no captured proof). Report them as a wall: "autofill complete,
final page needs applicant."

## 5. CSJ TAL Section-2 submit wall — root cause + fix
See `references/csj-tal-eform-notes.md` §"S2 submit wall" for the full recipe. TL;DR:
the "There is a problem — Desirable experience and skills" banner is **page 1 failing
validation**, not a generic S2 wall:
- `datafield_50626_1_1` radio "Do you have the relevant experience?" must be **Yes** — but
  `tal_sec2.py` has NO radio kind, so it is never set. Set it manually (click value `1`).
- `datafield_50629_1_1` 250-word statement must be non-empty (a re-navigation drops it).
- `datafield_53854_1_1` (qualification select, page 2) set to **Degree**.
- Page 6 Submit only renders after declaration `205967` ticked + `76575`='Yes'.
- Confirmation = "Application status: Application received."

## 6. Account walls (boards 5–8) — report once, don't grind
GCHQ / Parliament / TfL / BBC need a candidate account that does not exist. Creation
needs a CAPTCHA, email verification, or an answer the agent can't hold → account wall,
not exhaustion. Creating those 4 accounts (with creds stored in `ats-credentials.csv`,
NEVER a tracked file) is the single highest-leverage unblock for a 477 target. Guardian
one-time-code wall and NHS cookie-overlay wall similarly block login-cross-ref but NOT
guest apply.
