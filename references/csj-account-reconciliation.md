# CSJ account reconciliation — verifying the count + the data-scarcity ceiling

Verified 2026-07-15 while the user repeatedly fired "continue / do another pass"
on a met 100-target. The CSJ wall was already broken (Section 1 + Section 2 both
drive end-to-end); the open question was whether more on-profile applications were
being missed. Reconciling the **live CSJ Applications list** against
`application-tracker.csv` is the definitive way to answer that — and to prove the
ceiling is real rather than a missed application.

## The reconciliation protocol (run this before declaring CSJ exhausted)

1. Open the live Applications list on the ONE logged-in tab:
   `cfx.navigate('https://cshr.tal.net/vx/lang-en-GB/mobile-0/appcentre-11/brand-2/user-1067187/candidate/application')`
   (the `brand-2/user-<id>` path is stable; read it off the address bar if it
   differs). `sleep 6`.
2. Read the table body:
   `document.body.innerText.replace(/\s+/g,' ').trim()` — the rows are
   `Reference Application ID Title Status Department Closing date Last update
   Action`. Each completed (or in-progress) CSJ app shows here.
3. Cross-check every **`Application received` / `Invited to … Test`** row against
   `application-tracker.csv` (grep the Title + Department). If they ALL already
   have an `Applied` tracker row → the count is accurate and CSJ is fully drained
   for Jane's profile. If any is MISSING → log it (don't assume it was a
   different session's work — reconcile, then add the row so dedup sees it).

## Diagnostic: "applying to a posting redirects to an existing received app"

When you click **"Apply now"** on a CSJ advert whose application is ALREADY
submitted, the SPA does NOT open a fresh eform — it lands you on
`…/candidate/application/<EXISTING_APP_ID>?instant=apply` with the status
**"Application received"** (or "Invited to … Test"). There is NO new eform and
NO double-submit path. This is how you confirm a posting is already done without
guessing from the tracker:

- UK Export Finance User Researcher (jcode 2005241) → redirects to app 18255634
  "Application received".
- Cabinet Office User Researcher (jcode 2004993) → redirects to app 18255406
  "Application received".

So a fresh `feed.py` pass that lists these as "fresh" is WRONG about freshness —
the account already holds them. Trust the account list over `feed.py`'s dedup
when they disagree (feed.py matches on jcode; an already-submitted jcode is
still "fresh" in its view because it only checks the tracker, and a pre-existing
app isn't always in the tracker under that exact jcode string).

## The genuine CSJ ceiling for Jane (verified against the account)

The live account showed 7 completed CSJ apps, ALL already `Applied` in the
tracker: Business Analyst (Cabinet Office), Senior Business Analyst (CPS),
User Researcher (UK Export Finance), Performance Analyst (HM Land Registry),
User Researcher (Cabinet Office), Senior Service Desk Analyst (OFGEM),
Associate Product Manager (Cabinet Office). The **only non-senior exact-fit
Jane roles** (Business Analyst / User Researcher) were all already received;
the remainder are senior (£56k+) or off-profile intelligence/data analysts.
Re-sourcing the London `london-search` SID yields 0 on-profile fresh.

**Conclusion when reconciliation shows all received apps are tracked:** the
CSJ channel is at genuine data-scarcity for Jane's profile. State the count
once, stop re-emitting the ceiling, and do NOT force off-profile analyst roles
(no-fabrication rule). The two big channels (LinkedIn EA + CSJ) are then both
exhausted for this profile until new postings appear (time-based; the
`f_TPR=r86400` LinkedIn re-source already runs, and CSJ inventory turns over
~daily at 11:55pm closes).
