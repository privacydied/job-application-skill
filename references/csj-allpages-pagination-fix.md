# CSJ `--all-pages` stops at page 1 — root cause + fix

**Symptom (verified 2026-07-15):** `feed.py --nav <csj> --all-pages` emits only ~6 of 31
results and stderr logs `no 'next' control after page 1 — end of results`. The search
header shows `1 2` (pagination exists) but the crawler never follows to page 2.

**Root cause:** `feed.py._next_page()` only matches anchors whose visible text starts with
`next`. The current (verified) selector chain is:

```python
"let a=links.find(x=>/^next\\s*(?:»|›|&raquo;|&rsaquo;|>)?$/i.test(txt(x)));"
"if(!a) a=links.find(x=>/^next\\b/i.test(txt(x)) && txt(x).length<=12);"
"if(!a) a=document.querySelector('a[rel=next][href]');"
"if(!a) a=links.find(x=>/^next$/i.test((x.getAttribute('title')||x.getAttribute('aria-label')||'').trim()));"
```

CSJ renders pagination as **numbered links** (`1`, `2`, …), not a `next` anchor. The "2"
link's text is just `2`, so every matcher above misses it → crawler thinks it's the last
page. The page-2 SID link DOES exist in the DOM (`href` contains `page=2`); the detector
just can't see it.

**Fix (apply + verify before shipping):** after the existing `if(!a)` chain in `_next_page()`,
add a numeric-page matcher that prefers a page number HIGHER than the current one (CSJ encodes
`page=N` in the SID):

```python
"if(!a){" \
"  const cur = (location.href.match(/[?&]page=(\\d+)/)||[])[1] || '1';" \
"  const nums = links.filter(x=>/^\\d+$/.test((x.innerText||x.textContent||'').replace(/\\s+/g,''))" \
"                         && /[?&]page=\\d+/.test(x.getAttribute('href')||''));" \
"  a = nums.map(x=>({x, n:+(x.getAttribute('href').match(/page=(\\d+)/)[1])}))" \
"          .filter(o=>o.n > +cur).sort((p,q)=>p.n-q.n)[0]?.x || null;" \
"}"
```

Caveat: the SID is per-search-context and **expires** (timestamped `reqsig`). Regenerate a
fresh SID by driving the search form (`what` / `whereselector` / `submitSearch` via
`cfx.evaluate`, then write the URL into `searches.csv` via Python — base64 is too long to
paste) — full recipe in `csj-sourcing-pitfalls.md`. Only navigate the stable
`jobs.cgi?jcode=<id>` URLs.

**Impact:** unlocks all ~31 (and beyond) CSJ results per search → real CSJ volume, which is
the skill's prescribed big-target lever when LinkedIn EA is exhausted. Without this fix, CSJ
feeds are capped at ~6 cards and are not worth driving.

**Manual workaround (no code change):** after page 1, grab the page-2 SID link directly and
`open-tab` it, or drive `cfx.evaluate("location.href='<page2 SID url>'")` — then run
`feed.py` again pointed at that page (repeat per page). Slow but works today.
