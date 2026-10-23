# careers.elcompanies.com (Estée Lauder Companies — Eightfold apply form)

Single-page form at `/careers/apply?pid=<id>`. Text inputs have stable ids
(`Contact_Information_firstname`, `Position_Specific_Questions_q_*`) — `atsform.fill('#id', v)`
works (a JS value-set does NOT register). Dropdowns are `input[role=combobox]` with
`aria-labelledby` → question; click input, then click `[role=option]` in `aria-controls` list.

⛔ BLOCKER (2026-10-15): the **required resume upload never binds** in camofox — plain `/upload`,
page-world `DataTransfer`+`change`, synthetic drop, and `/uploadViaChooser` (HTTP 500) all
leave "Upload your resume cannot be left blank". Log `Blocked`; needs a human upload.
