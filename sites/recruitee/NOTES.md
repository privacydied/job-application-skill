# recruitee.com — verified site notes

Site-specific quirks for company career sites hosted on Recruitee
(`<company>.recruitee.com`). Two confirmed end-to-end applications so far:
CloserStill Media (`careers.closerstillmedia.com`, custom domain) and Avant Arte
(`avantarte.recruitee.com`, default subdomain).

## Cover letter: prefer "Write it here instead" over uploading a file
The Application form offers a file-upload box for "Cover letter" by default, but
there is a link/button **"Write it here instead"** that swaps it for a plain
`<textarea>`. Clicking it is more reliable than generating+uploading a second PDF
for a text field — use `set_textarea`-style native-setter + input/change dispatch
(same pattern as `sites/welcometothejungle/scripts/set_textarea.py`) to fill it
cleanly.

## Checkbox groups (e.g. "preferred work location") need a JS `.click()`, not cfx.sh's ref-based click
Confirmed on Avant Arte's "What is your preferred work location?" checkbox group:
`cfx.sh click <ref>` on the checkbox returned `{"ok":true}` (no error) but
`document.querySelector('input[value=...]').checked` came back `false` when
verified afterward — a **silent false-positive**, not a visible failure. The
inputs are real `<input type="checkbox">` elements (not a custom widget), so this
looks like a click-target/overlay issue specific to Recruitee's checkbox styling
rather than a shadow-DOM or react-select case. **Fix:** after a checkbox-group
click, verify with `evaluate` (`[...document.querySelectorAll('input[type=checkbox]')].map(c=>c.value+':'+c.checked)`)
before trusting it, and if still `false`, fall back to a direct JS click:
```js
document.querySelector('input[value="<value>"]').click()
```
This flipped `.checked` to `true` reliably.

## Phone field defaults to a guessed country code
The phone input pre-fills a country-code prefix (e.g. `+31` for Netherlands) based
on some heuristic (likely job location), not the applicant's actual country. Don't
just append digits — set the full international number via the native
`HTMLInputElement.prototype.value` setter + `input`/`change` dispatch (same pattern
used for the cover-letter textarea) to overwrite the prefix cleanly; this also
flips the "Select country calling code" button label to the correct country
automatically as a side effect (confirmed: typing `+447700900000` changed the
displayed country from Netherlands to United Kingdom).

## Standard flow
1. Company details autofill from the job listing (name/email/phone are usually
   the only bare fields).
2. Upload CV via the shared `/upload` endpoint (see `CAPABILITY-GAPS.md`) — same
   recipe as every other ATS.
3. Answer any custom screener textareas.
4. Submit button is literally labelled "Send". Success state: the "Application"
   tab label changes to "Application Applied" and the panel shows heading
   **"All done!"** / "Your application has been successfully submitted!" — this
   is the confirmation signal to screenshot/log, analogous to WTTJ's "We're
   rooting for you!".
