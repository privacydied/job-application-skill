# <domain> ("<ATS/board name if known>") — site notes

<One-line description of what this domain is and where it's usually reached
from — e.g. "external ATS reached via a WTTJ 'Or apply on X's website' redirect"
or "job board's own native apply flow". If site scripts exist for it, mention
`scripts/` here and what each one does.>

## Canonical login flow (verified)
<Only if the site requires login. Exact URL to navigate to, exact click/type
sequence, what "success" looks like (URL + visible heading/text). Note any
subdomain gotchas (e.g. "app." vs bare domain).>

## Login/form pitfalls that produced false failures
<Anything that LOOKED like a real failure but wasn't — stale leftover form
state, flaky "no session" errors that just need a re-navigate, auth errors
that must NOT be treated as network/captcha blocks, etc. Distinguish clearly
between "this is a real hard-stop, report it" vs "this is noise, retry".>

## Form mechanics that matter
<DOM quirks specific to this site's form framework: shadow DOM, react-select-
style comboboxes with no real `<select>`, sections that need explicit Save
before the next unlocks, anything that isn't a plain HTML form. Include the
verified fix/workaround, not just the symptom — and a code snippet if the fix
involves a specific selector/endpoint call pattern.>

## Known failure modes + verified fixes
<Anything that looked broken and had a root cause worth documenting so it's
never re-investigated from scratch — e.g. "clicking Apply doesn't navigate,
use the href directly" style findings. State the root cause AND the fix.>

## What success looks like
<The canonical confirmation state after a real submit — exact heading text,
URL pattern, whatever is the reliable signal to screenshot/log as proof this
worked. This is what separates "probably submitted" from "confirmed submitted".>

## Verified end-to-end test applications
<Log of real runs that exercised this flow start-to-finish, what each one
specifically proved (e.g. "no-PDF-upload flow works", "long free-text cover
letter field doesn't duplicate text"). Not every application needs an entry
here — just ones that verified something not covered above for the first time.>

<!--
Delete/replace section headers above that don't apply to this site — the
goal is accuracy, not filling out every heading for its own sake. Keep entries
concrete and falsifiable (cite what was actually tried, what actually
happened, what the actual fix was) — vague notes ("sometimes this is flaky")
are close to useless to a future run. See SKILL.md's "Continuous learning"
section for when/how to update this file.
-->
