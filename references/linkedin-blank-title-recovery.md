# LinkedIn blank-title card recovery (sourcing technique)

**Symptom (observed live 2026-07-13):** `sites/linkedin/scripts/feed.py` returns a
non-trivial fraction of result cards with `"title": ""` and `"company": ""` even
after `--scrolls 10`. The list-card DOM node exists (`data-job-id` present) but its
inner text never rendered — a LinkedIn virtualized-list paint quirk, NOT a dead
posting. Blank cards appeared across every title variant (Product/UX/UI/Interaction/
Digital/Design-Systems) and the `f_WT=2` remote filter.

**Why it matters for the cheap pre-filter:** the skill's rule says drop off-profile
titles on sight — but a blank title is not "off-profile", it's "unknown". Do NOT
skip these on the list; recover the title first, then screen.

**Recovery recipe (per card):** open the JD page and read the detail container's
text. The top-card selector `.jobs-unified-top-card__job-title` ALSO misses these
same cards (returns null), so don't rely on it. Use:

```js
(() => {
  const m = document.querySelector('main, .jobs-details, article');
  const lines = (m ? m.innerText : '').split('\n').map(s => s.trim()).filter(Boolean);
  return { company: lines[0] || '(unknown)', title: lines[1] || '(unknown)' };
})()
```

JD body layout is **line 0 = company, line 1 = title**, then location·time·applicants.
The recovered title reliably exposes what the list hid: e.g. a blank card became
"UK-Based UX/UI Product Designers" @ Nancy Assists ($150/yr, "Responses managed off
LinkedIn" → agency spam) or "Senior Product Designer" @ British Airways.

**Re-runnable probe:** `scripts/reveal_blank.py <id> [<id> ...]` (run from skill root)
prints `id | company | title` for each, so you don't hand-type nav+eval per card.

**Screening outcome from the live pass:** after recovering ~20 blank cards in a
"UX Designer" London batch, 100% were senior/principal/lead, agency spam, or adjacent
disciplines (PM, Software Engineer, Architect, Animator) — zero junior→mid on-profile
roles remained. When recovery confirms a query is exhausted of viable on-profile roles,
mark it on cooldown (`board_cooldown.mark('linkedin', <query>, 12)`) and move to another
board; do not re-walk the same query.
