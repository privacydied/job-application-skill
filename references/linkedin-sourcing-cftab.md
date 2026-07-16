# LinkedIn sourcing — CFX_TAB clobber by `feed.py --nav` (verified 2026-07-13)

`feed.py --nav "<url>"` navigates the **shared `CFX_TAB`** tab to each search URL to
enumerate cards. When you run several title-variant searches before applying, the LAST
`--nav` leaves `CFX_TAB` parked on a results page — NOT on the posting you intend to
apply to.

## Symptom seen this run
Sourced Rightmove User Researcher via 3 `feed.py --nav` variant calls
(`UX Designer`, `Product Designer`, `Interaction Designer`). After the third call,
`CFX_TAB` was on the `Interaction Designer` results page. A `click-follow` on the
Rightmove apply-ref (e24) then navigated the tab AWAY (the ref `e24` belonged to
whatever the last search page had rendered), not to the ATS. Cost: had to re-open the
JD URL before click-follow worked.

## Rule (encode into sourcing sequence)
1. **Do ALL LinkedIn variant sourcing first** (3 title variants per NOTES), collect the
   candidate list, apply the cheap pre-filter.
2. **THEN** re-navigate `CFX_TAB` to the specific posting's
   `https://www.linkedin.com/jobs/view/<id>` URL *immediately before* `click-follow`.
   Don't assume the tab is still on the posting from an earlier step.
3. If you must interleave (source one -> apply one), re-navigate to the JD right before
   each apply. Re-point `CFX_TAB` to any new popup/ATS tab returned by `click-follow`
   (it sets `new_tab` in the result) so subsequent `atsform.py` calls hit the ATS, not
   LinkedIn.

Same gotcha applies to the auto-cooldown-marking bundled query: feed.py's `--nav`
cools the query key after an exhausted run, so re-running the exact bundled query
returns `[]` on cooldown — use distinct single-title variants (different cooldown keys)
to keep sourcing.
