# Easy Apply batch pitfalls (learned 2026-07-14, 100-application run)

Four concrete failure modes cost real turns on the first Easy Apply batch. The
batch driver `scripts/easyapply_batch.py` already encodes the fixes; this note is
the WHY + how-to-detect so a future session doesn't re-derive them.

## 1. Sponsorship / authorised-to-work / relocate screeners are RADIOS, not text
`easyapply.py fill` matches `labelOf(el).includes(want)`. For "Will you now or in
the future require sponsorship for employment visa status? Required" the backing
`<input>` is a **radio group**, and its `labelOf` resolves to a short label that
often OMITS the trailing "Required" — so passing the full state-label string as
`want` returns `NO_FIELD`, and the loop spins `fill` → `next` → `BLOCKED_UNANSWERED_REQUIRED`
until the 150s timeout. Fix: answer `require sponsorship`/`sponsorship`/`authorized
to work`/`right to work`/`willing to relocate`/`notice period`/`available to start`
with `easyapply.py radio <key-substring> <Yes|No|Immediately>`, falling back to
`fill` only if the radio isn't found. Substring match works because `radio` searches
`fieldset legend/label innerText .includes(want)`.

## 2. Post-submit "Application sent" races the spinner
After `easyapply.py submit` clicks, the modal shows a **spinner for several seconds**
before the header flips to "Application sent". Reading `state()` immediately returns
the REVIEW step (not "sent"), so a naive driver thinks it failed and exits
`CHECK_CONFIRM_MANUALLY` WITHOUT logging — even though LinkedIn did submit. Fix:
poll `state()` for up to ~16s for "sent" in step/header; only if that stays false,
fall back to scanning `document.body.innerText` for "your application was sent"/
"applied". Log `Applied --proof` only on a positive confirmation. Otherwise the
tracker under-reports real submissions.

## 3. camofox tabs die mid-batch (HTTP 404 / 500)
The single shared tab routinely dies between calls (engine restart, ~10-tab wedge
recovery, transient 500). A batch that doesn't self-heal aborts every remaining
posting with `Tab not found`. Fix: wrap every `cfx.navigate` in a self-heal —
on 404/500 call `cfx.ensure_tab(persist=False)`, update `os.environ['CFX_TAB']`,
retry. RETRY the same posting; don't skip it. But first `already_done(company,role)`
against application-tracker.csv so an already-Applied row isn't double-submitted
(the driver's own submit can leave a row unlogged if pitfall #2 bit it — verify,
don't assume).

## 4. Resume PERSISTS across Easy Apply sessions
Opening a 2nd Easy Apply shows the PREVIOUS posting's PDF still attached. Re-upload
`uploads/base-resume.pdf` on the Resume step and confirm via the Review step that
`resume = base-resume.pdf` before submit. (Same warning as the main SKILL.md
easyapply-resume-persistence note — restated because it bit again here.)

## 5. Source LinkedIn WITH f_AL=true for volume
"Easy Apply" (profile-driven, login-free) is the automatable path. Plain
`--nav` LinkedIn searches mix in "Apply" postings that redirect to a heavier external
ATS. Filter the search URL with `&f_AL=true` to get ONLY Easy Apply roles. The
six-family query set in searches.csv was re-run with `f_AL=true` and yielded ~79
candidates → 22 review-survivors, vs the external-mixed pass which needed per-posting
ATS drivers. For a 100-target, ALWAYS source Easy Apply–filtered first; only fall back
to external-ATS redirects for the roles that have no Easy Apply equivalent.

## 6. `.jobenv.run` is not python-writable on this host
`open('.jobenv.run').write(...)` raises `io.UnsupportedOperation: not writable`
even though the file is `-rw------- <your-user> users`. The `patch` tool works; raw python
`open().write()` does not (likely an ACL/immutable bit). To persist a new CFX_TAB,
use the `patch` tool (or `cat >` via shell) — never rely on an in-Python file write.
The batch driver avoids the issue entirely by keeping the tab id in
`os.environ['CFX_TAB']` in-process after a self-heal.

## 7. BAIL on BLOCKED_UNANSWERED_REQUIRED (don't loop forever)
`easyapply.py next` returns `BLOCKED_UNANSWERED_REQUIRED: <question>` when a
required question is still empty after you answered the ones you knew. The ORIGINAL
`easyapply_batch.py` (and a naive driver) loops: it re-answers the known screener,
calls `next` again, gets `BLOCKED_...` again, and spins until the 150s timeout —
never logging, never advancing. **Detect the signal and exit NEEDS_HUMAN for that
posting.** A 2nd genuinely-unanswerable screener (e.g. Persistent Systems:
sponsorship answered, but "Do you have Native-level French/Italian proficiency?"
has no truthful answer for Jane) is a real skip, not a flake. Inspect `state()['errors']`
or the still-visible labels to capture the blocking question text. The hardened
driver is `scripts/easyapply_driver.py` (extends the original with this bail + the
persist-tab fix below).

## 8. Persist the healed tab id back to `.jobenv.run`
`easyapply_batch.py` self-heals a dead tab by calling `cfx.ensure_tab()` and updating
`os.environ['CFX_TAB']` **in-process only**. That's fine within one run, but the NEXT
shell call (or a later re-run) re-`source`s `.jobenv.run` and reads the STALE tab id
that died — so the next call dies with `404 Tab not found` before the driver even
starts. **After every heal, rewrite the `export CFX_TAB='...'` line in `.jobenv.run`**
(`scripts/easyapply_driver.py` does this via `persist_tab()`). If a fresh terminal
call opens with a `404`/`500` on the tab, heal once, persist, then proceed. (The
file is not python-writable by raw `open()`, so `persist_tab` uses `re.sub` on the
read string then writes — if that also fails, fall back to the `patch` tool.)

## 9. Unanswerable screeners that legitimately skip a posting
These are NOT bugs — they are honest off-profile skips; log them `Skipped` (not
`Blocked`, which implies retryable). Observed examples that correctly bail:
native-level French/Italian (or other language) proficiency; years-of-experience
with a specific tool (Mac, Paid Social, IT Consulting) when Jane has none;
onsite/commute/office-location questions for non-London offices (Harold Hill,
Bromley); open-salary "what are your salary expectations"; portfolio/essay
questions requiring human-written content (Queensmith's "what is exceptional
marketing" piece). The driver bails to NEEDS_HUMAN on these; convert to `Skipped`
with the reason so the tracker stays accurate and they aren't re-attempted.

## 10. `apply_ea.py` confirmation race — RESOLVED (patched 2026-07-15)
`scripts/easyapply_batch.py` was hardened for pitfall #2, but the canonical
`sites/linkedin/scripts/apply_ea.py` (the preferred end-to-end driver per SKILL.md
loop step 5) had its OWN blind spot observed live 2026-07-14: when LinkedIn
auto-advances a step straight to a step label containing `Your application was sent
to <Co>` / `Application submitted` **without** going through the Review→submit path,
the driver's inline confirm reads the spinner/modal and misses it — it times out
(`RC=3`/`RC=124`) and logs nothing, **even though the application SUCCEEDED**. Verified:
One Identity + Blu Digital both showed "Application submitted" on the job page but
were absent from the tracker until reconciled manually (nav to the job page, `cfx.evaluate`
for `application submitted` / an `Applied` button, then `log-application.py Applied --proof`).
**Fix in `apply_ea.py`:** treat a step label matching `application (was )?sent` /
`submitted` the same as `submit`'s own `SUCCESS: application sent` — set SUBMITTED_OK
and log. Until fixed, the harness workaround is: after a batch, find roles that printed
`Your application was sent` but aren't in the tracker, and reconcile them.

## 11. `answer_screeners` FAILED select/fill → loops — RESOLVED (patched 2026-07-15)
In `apply_ea.py`, when a KNOWN screener's widget can't accept the value (e.g. Nozomi's
"Location (city)" react-select combobox), `ea("select", key, val)` returns non-`OK`
and the driver falls back to `ea("fill", key, val)` which also fails — but
`answer_screeners` still returns `all_known=True`, so the driver thinks the step is
answered, advances `next`, gets `BLOCKED_UNANSWERED_REQUIRED: Location`, and **loops
until its attempt cap** instead of bailing to NEEDS_HUMAN. Fix: if `select`+`fill` both
fail for a known key, return False (caller flips to NEEDS_HUMAN). Until fixed, such a
role spins its max attempts and must be logged `Blocked` manually with the reason
"select/fill of '<key>' did not resolve (react-select combobox needs human typing)".

**RESOLUTION (2026-07-15):** both defects fixed in `sites/linkedin/scripts/apply_ea.py`:
the walk loop now detects a `sent`/`application submitted` step label and logs
inline (no Review path needed); and a `BLOCKED_UNANSWERED_REQUIRED` on a plain step
returns NEEDS_HUMAN (exit 7) immediately instead of looping to the attempt cap.
After a batch, reconciliation should be unnecessary — see `references/rotation-recovery-2026-07-15.md`.
