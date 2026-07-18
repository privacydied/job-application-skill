#!/usr/bin/env python3
"""
jd.py — one-call JD screen+extract: navigate to a posting and return EVERYTHING the
screening + extraction steps need as ONE compact JSON payload.

WHY THIS EXISTS (speed levers 1+2 against slow inference): the naive flow spends
several model turns per posting — nav, full-page a11y snapshot (the single biggest
token payload in a turn, most of it nav chrome/footer noise), then a second look for
requirements/hiring manager. This replaces all of that with one process call whose
output is JUST the decision-relevant content, so SKILL.md loop steps 1 (Screen) and
2 (Extract) happen in the SAME model turn the page is opened, with no full snapshot.

    CFX_KEY=… CFX_TAB=… python3 jd.py --nav "<posting url>"     # navigate + extract
    CFX_KEY=… CFX_TAB=… python3 jd.py                            # extract current tab
    CFX_KEY=… CFX_TAB=… python3 jd.py --nav-batch urls.txt       # N postings, ONE call
    CFX_KEY=… CFX_TAB=… feed→precheck | ... | python3 jd.py --nav-batch -   # or stdin
    options: --max-chars N   cap on the JD body text (default 7000)
             --cache-ttl M   payload-cache freshness window, minutes (default 360)
             --refresh       bypass the cache read (still writes); alias --no-cache

  --nav-batch is speed lever #1: it navigates+extracts EVERY surviving posting in
  one process — so SKILL.md step 3 (Screen+Extract) costs ONE model turn total
  instead of one per posting. URLs come from a file or stdin ('-'), one per line
  (blank / #-comment lines ignored, de-duplicated). Output is a JSON ARRAY of the
  same per-posting payloads (single --nav still returns one object), each with an
  added "_cache":"hit"|"miss". Navigations stay sequential with the usual
  human_pause between them, so the anti-detection cadence is unchanged; a posting
  that errors becomes {"url":…,"error":…} and the batch keeps going. Payloads are
  cached (speed lever #3) keyed by CANONICAL id (24h TTL) — `?trk=`/`?theme=` variants
  of one posting share a cache entry, a re-run within the TTL skips the browser, but an
  under-rendered shell is never cached so SPA-retry still works. `--compact` emits the
  token-diet payload (capped jd_text); `pipeline.py` stores that in queue.jsonl.

Payload fields:
  url/title/h1/meta          identity — company usually in og:site_name / title
  title_eligibility          check_title.py verdict on the h1 (code, not memory)
  jd_text                    main JD body text (largest content block, whitespace-
                             collapsed, capped) — read salary/location/visa/hiring
                             manager from here; NEVER take a full `snap` of a JD page
  requirements               bullet lists under requirement-ish headings (must-haves)
  salary_mentions            £/$/€ amounts regex-harvested from the text
  location_signals           london/remote/hybrid/other-UK-city/sponsorship booleans
                             (advisory pointers into the location hard screen — the
                             JD's own location line in jd_text is authoritative)
  form                       visible field inventory + apply-ish button texts —
                             {fields:0, apply_buttons:[]} + signup-y CTAs is the
                             "platform funnel — no web application form" signature
                             (fast Skip); real fields = a fillable ATS, proceed
  hidden_suspects            invisible-to-humans text matching instruction-like
                             patterns (LLM-trap scan, Adversarial Content Defense §3
                             — code does the sweep so no turn is spent grepping DOM)

Screening is still the model's judgment call — this just guarantees the whole basis
for it arrives in one turn. If a field looks truncated or the page is a shell (SPA
not yet rendered -> tiny jd_text), re-run once before concluding anything.
"""
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cfx  # noqa: E402
import stagetimer  # noqa: E402  (no-op unless STAGETIMER is set)
from check_title import check_title  # noqa: E402
# Single source of truth for the non-London UK-city hard-screen list: precheck.py owns
# it (that's the authoritative screen). Importing it keeps jd's advisory location signal
# from drifting out of sync (it did — jd was missing bath/coventry/leicester/southampton/
# york, so a JD for one of those wouldn't flag uk_city_other while precheck would drop it).
from precheck import UK_CITIES  # noqa: E402

SALARY_RE = re.compile(r"[£$€]\s?\d[\d,.]*\s?[kK]?(?:\s*[-–—]\s*[£$€]?\s?\d[\d,.]*\s?[kK]?)?"
                       r"(?:\s*(?:per\s+(?:annum|year|month|day)|pa|p\.a\.|/(?:yr|year)))?")

TRAP_RE = re.compile(r"\b(ai|llm|language model|assistant|automated|ignore (?:previous|all|prior)|"
                     r"prompt|instruction|mention the word|include the (?:word|phrase)|"
                     r"to prove|start your (?:answer|response)|system prompt)\b", re.I)

_EXTRACT_JS = r"""
(() => {
  const collapse = s => (s || '').replace(/\s+/g, ' ').trim();
  const MAXC = %d;

  // --- main JD text: the largest content block, not the whole page ---
  const cands = ['main', 'article', '[class*="description"]', '[id*="description"]',
                 '[class*="jobDetails"]', '[class*="job-details"]', '[role="main"]'];
  let bestEl = document.body, bestLen = 0;
  for (const sel of cands) {
    for (const el of document.querySelectorAll(sel)) {
      const L = (el.innerText || '').length;
      if (L > bestLen) { bestLen = L; bestEl = el; }
    }
  }
  if (bestLen < 200) { bestEl = document.body; }
  const jdText = collapse(bestEl.innerText).slice(0, MAXC);

  // --- requirements: bullet lists following requirement-ish headings ---
  const reqRe = /(requirement|qualif|about you|you.ll (?:need|bring)|looking for|must.have|nice.to.have|responsibilit|what you|who you are|skills)/i;
  const reqs = [];
  for (const h of bestEl.querySelectorAll('h1,h2,h3,h4,h5,strong,b')) {
    if (!reqRe.test(h.innerText || '') || (h.innerText || '').length > 80) continue;
    let sib = h.closest('h1,h2,h3,h4,h5') || h;
    for (let hops = 0, n = sib.nextElementSibling; n && hops < 3; n = n.nextElementSibling, hops++) {
      if (/^(UL|OL)$/.test(n.tagName)) {
        const items = [...n.querySelectorAll('li')].map(li => collapse(li.innerText).slice(0, 220)).filter(Boolean);
        if (items.length) reqs.push({ heading: collapse(h.innerText).slice(0, 80), items: items.slice(0, 25) });
        break;
      }
    }
    if (reqs.length >= 6) break;
  }

  // --- form inventory: fillable ATS vs platform funnel ---
  const vis = el => el.offsetParent !== null || el.type === 'hidden' ? el.offsetParent !== null : false;
  const q = sel => [...document.querySelectorAll(sel)].filter(vis).length;
  const form = {
    text_inputs: q('input[type=text],input[type=email],input[type=tel],input[type=url],input[type=number],input:not([type])'),
    textareas: q('textarea'), selects: q('select,[role=combobox]'),
    file_inputs: document.querySelectorAll('input[type=file]').length,
    radios: q('input[type=radio]'), checkboxes: q('input[type=checkbox]'),
    apply_buttons: [...document.querySelectorAll('button,a,[role=button],input[type=submit]')]
      .map(b => collapse(b.innerText || b.value || '')).filter(t => t && /(^|\b)(apply|easy apply|submit)/i.test(t))
      .filter((t, i, arr) => arr.indexOf(t) === i).slice(0, 5),
    signup_ctas: [...document.querySelectorAll('button,a,[role=button]')]
      .map(b => collapse(b.innerText || '')).filter(t => t && /(sign ?up|create (an )?account|download (the )?app|get the app|join the waitlist)/i.test(t))
      .filter((t, i, arr) => arr.indexOf(t) === i).slice(0, 5),
  };

  // --- hidden-text sweep (LLM traps): human-invisible text nodes ---
  const hidden = [];
  for (const el of document.querySelectorAll('body *')) {
    if (hidden.length >= 12) break;
    if (/^(SCRIPT|STYLE|NOSCRIPT|TEMPLATE|META|LINK|svg|SVG|PATH)$/i.test(el.tagName)) continue;
    if (el.childElementCount > 0) continue;
    const txt = collapse(el.textContent);
    if (txt.length < 15 || txt.length > 600) continue;
    let st;
    try { st = getComputedStyle(el); } catch (e) { continue; }
    const invisible = st.display === 'none' || st.visibility === 'hidden' || +st.opacity === 0
      || parseFloat(st.fontSize) <= 2 || parseInt(st.textIndent) <= -999
      || (el.offsetWidth <= 1 && el.offsetHeight <= 1);
    if (invisible) hidden.push(txt.slice(0, 250));
  }

  const meta = {};
  for (const [k, sel] of [['site_name', 'meta[property="og:site_name"]'],
                          ['og_title', 'meta[property="og:title"]'],
                          ['description', 'meta[name="description"],meta[property="og:description"]']]) {
    const m = document.querySelector(sel);
    if (m && m.content) meta[k] = collapse(m.content).slice(0, 200);
  }

  return JSON.stringify({
    url: location.href,
    title: collapse(document.title).slice(0, 200),
    // prefer the heading INSIDE the main content block — a cookie dialog can own the
    // page's first <h1> (seen live on recruitment.hackney.gov.uk 2026-07-14)
    h1: collapse(((bestEl.querySelector('h1,h2') || document.querySelector('h1')) || {}).innerText).slice(0, 200),
    meta, jd_text: jdText, jd_text_full_len: bestLen, requirements: reqs,
    form, hidden_raw: hidden,
  });
})()
"""


def extract(max_chars=7000):
    raw = cfx.evaluate(_EXTRACT_JS % max_chars, timeout=45)
    data = json.loads(raw) if isinstance(raw, str) else (raw or {})

    text_all = " ".join([data.get("jd_text", ""), data.get("title", ""),
                         json.dumps(data.get("requirements", []))])
    low = text_all.lower()

    # Keep only plausible salary figures (>=3 consecutive digits, or a k suffix) —
    # filters ad noise like LinkedIn's "Premium for £0" (seen live on first test).
    data["salary_mentions"] = sorted({m.strip() for m in SALARY_RE.findall(data.get("jd_text", ""))
                                      if re.search(r"\d{3}|\d\s?[kK]\b", m)})[:6]
    data["location_signals"] = {
        # word-boundary + new-lookbehind (mirrors precheck.screen_location) — a bare
        # `"london" in low` wrongly flagged "Londonderry"/"New London" as london=True,
        # which would skip pipeline's review→drop for a non-commutable location.
        "london": bool(re.search(r"(?<!new )\blondon\b", low)),
        "remote": bool(re.search(r"\bremote\b|work from home|fully.remote", low)),
        "hybrid": "hybrid" in low,
        # "york" guarded against "New York" (matches precheck.screen_location).
        "uk_city_other": sorted({c for c in UK_CITIES if re.search(
            r"(?<!new )\byork\b" if c == "york" else r"\b" + re.escape(c) + r"\b", low)}),
        "sponsorship_mentioned": "sponsor" in low,
    }
    # Title for the screen: the JD body's first <h1> is USUALLY the job title, but some sites
    # (LinkedIn) hijack it with a UI string like "Use AI to assess how you fit" — check_title then
    # screens THAT as ineligible and wrongly drops a good role. og:title and a suffix-cleaned
    # document.title ("<job> | <company> | LinkedIn") are reliable job-title carriers. So try all
    # of them (they all describe the SAME posting) and keep the one check_title finds eligible;
    # fall back to the h1 (original behaviour) when none match — so an off-profile role still reads
    # ineligible.
    _og = (data.get("meta") or {}).get("og_title") or ""
    _doc = re.split(r"\s+[|–—\-]\s+", data.get("title", ""))[0].strip()
    title_for_check = data.get("h1") or _og or data.get("title", "")
    for _src in (data.get("h1"), _og, _doc):
        if _src and check_title(_src).get("eligible"):
            title_for_check = _src
            break
    data["title_eligibility"] = dict(check_title(title_for_check), checked_title=title_for_check)

    form = data.get("form", {})
    n_fields = sum(form.get(k, 0) for k in
                   ("text_inputs", "textareas", "selects", "file_inputs", "radios", "checkboxes"))
    data["form"]["total_fields"] = n_fields
    data["funnel_suspect"] = bool(n_fields == 0 and form.get("signup_ctas")
                                  and not form.get("apply_buttons"))

    hidden = data.pop("hidden_raw", [])
    suspects = [h for h in hidden if TRAP_RE.search(h)]
    data["hidden_suspects"] = {"n_hidden_text_nodes": len(hidden), "instruction_like": suspects[:5]}
    return data


def compact(data):
    """Token-diet payload (2026-07-15): only the fields screening/tailoring actually
    read, JD text capped hard. `pipeline.py` stores this in queue.jsonl and `--compact`
    emits it — a full jd_text (up to 7k chars) is the single biggest payload in a turn
    and is rarely needed verbatim once the requirements are extracted. Returns a small
    dict; the full payload is still cached on disk for the rare verbatim re-read."""
    if not isinstance(data, dict) or data.get("error"):
        return data
    reqs = []
    for group in (data.get("requirements") or [])[:4]:
        for it in (group.get("items") or [])[:8]:
            reqs.append(it)
    return {
        "url": data.get("url"),
        "title": data.get("h1") or data.get("title"),
        "company": (data.get("meta") or {}).get("site_name"),
        "title_eligibility": data.get("title_eligibility"),
        "requirements": reqs[:20],
        "jd_excerpt": (data.get("jd_text") or "")[:1500],
        "jd_len": data.get("jd_text_full_len", 0),
        "salary_mentions": data.get("salary_mentions", []),
        "location_signals": data.get("location_signals", {}),
        "funnel_suspect": data.get("funnel_suspect", False),
        "total_fields": (data.get("form") or {}).get("total_fields", 0),
        "trap": (data.get("hidden_suspects") or {}).get("instruction_like", []),
        "_cache": data.get("_cache"),
    }


# ── per-run payload cache (speed lever #3: memoize) ──────────────────────────
# jd.py's payload gets re-derived downstream (tailor must_haves, cover-letter
# facts) and again on any SPA-retry re-run. Persisting it keyed by URL means a
# second fetch of the same posting within the TTL costs zero browser round-trips
# — and, crucially for --nav-batch, a mid-batch failure can be resumed without
# re-navigating the postings that already succeeded.
#
# THE UNDER-RENDER GUARD is what makes cache-READ safe even on a retry: a
# truncated SPA shell (jd_text_full_len < 300) is NEVER written to cache, so the
# classic "page came back empty, re-run once" flow still re-fetches fresh — only
# a fully-rendered payload is ever served from cache. A cache hit returns without
# navigating, so the tab is NOT left on the posting; pass --refresh if a caller
# needs the tab parked there.
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
CACHE_DIR = os.path.join(_ROOT, ".jd-cache")
# 24h (2026-07-15): a JD's body is static — only its closing date matters, and that's
# re-checked at apply time, not from cache. A day-long TTL lets a resumed run / a
# next-morning firing reuse yesterday's screen instead of re-navigating. (Was 6h.)
DEFAULT_TTL_MIN = 1440


def _cache_key(url):
    """Cache key = the posting's CANONICAL id, not the raw URL, so `?trk=`/`?theme=`
    tracking-param variants of the SAME posting share one cache entry (precheck.canon_ids
    is the same canonicalization the dedup uses). Falls back to the stripped URL when no
    canonical id can be extracted (e.g. an ATS with an opaque path)."""
    try:
        from precheck import canon_ids
        ids = canon_ids(url or "")
        if ids:
            return "id:" + sorted(ids)[0]
    except Exception:
        pass
    return "url:" + (url or "").strip()


def _cache_path(url):
    import hashlib
    return os.path.join(CACHE_DIR, hashlib.sha1(_cache_key(url).encode("utf-8")).hexdigest() + ".json")


def _cache_read(url, ttl_min):
    try:
        st = os.stat(_cache_path(url))
    except OSError:
        return None
    if (time.time() - st.st_mtime) > ttl_min * 60:
        return None
    try:
        with open(_cache_path(url), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _cache_write(url, data):
    # Never cache an error payload or an under-rendered shell — see the guard note.
    if not isinstance(data, dict) or data.get("error") or data.get("jd_text_full_len", 0) < 300:
        return
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        tmp = _cache_path(url) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, _cache_path(url))
    except OSError:
        pass  # cache is best-effort; a write failure must never break screening


def _fetch(nav_url, max_chars):
    """Navigate (if nav_url) and extract — the actual browser round-trip."""
    if nav_url:
        cfx.navigate(nav_url)
        cfx.poll("document.readyState", predicate=lambda r: r == "complete", timeout=15.0)
        # SPA boards render after readyState: wait for real body text, briefly.
        cfx.poll("(document.body.innerText||'').length",
                 predicate=lambda r: isinstance(r, (int, float)) and r > 400, timeout=10.0)
        # A cookie/consent overlay can hijack the first <h1> and swallow later
        # clicks (Hackney especially) — clear it before extracting. No-op if absent.
        cfx.dismiss_cookie_banner()
    return extract(max_chars)


def screen_one(nav_url, max_chars=7000, ttl_min=DEFAULT_TTL_MIN, use_cache=True):
    """Screen+extract ONE posting, honouring the payload cache. Returns the
    payload dict with an added `_cache` field ("hit"|"miss"). Only a real
    navigation (nav_url set) can hit cache — a current-tab extract always runs
    live. Raises cfx.CfxError on a browser failure (caller decides fatal vs skip)."""
    with stagetimer.timed("screen", meta=nav_url or "current-tab"):
        if nav_url and use_cache:
            cached = _cache_read(nav_url, ttl_min)
            if cached is not None:
                cached["_cache"] = "hit"
                return cached
        data = _fetch(nav_url, max_chars)
    if nav_url:
        _cache_write(nav_url, data)
    data["_cache"] = "miss"
    return data


def _read_url_list(src):
    """URLs for --nav-batch: from a file path, or '-' for stdin. One per line;
    blank lines and #-comments ignored; de-duplicated preserving order."""
    raw = sys.stdin.read() if src == "-" else open(src, encoding="utf-8").read()
    seen, urls = set(), []
    for line in raw.splitlines():
        u = line.strip()
        if not u or u.startswith("#"):
            continue
        if u not in seen:
            seen.add(u); urls.append(u)
    return urls


def main():
    args = sys.argv[1:]
    nav_url, batch_src, max_chars = None, None, 7000
    ttl_min, use_cache, want_compact = DEFAULT_TTL_MIN, True, False
    i = 0
    while i < len(args):
        if args[i] == "--nav" and i + 1 < len(args):
            nav_url = args[i + 1]; i += 2
        elif args[i] == "--compact":
            want_compact = True; i += 1
        elif args[i] == "--nav-batch" and i + 1 < len(args):
            batch_src = args[i + 1]; i += 2
        elif args[i] == "--max-chars" and i + 1 < len(args):
            try:
                max_chars = int(args[i + 1])
            except ValueError:
                print(f"--max-chars needs an integer, got {args[i + 1]!r}", file=sys.stderr)
                return 2
            i += 2
        elif args[i] == "--cache-ttl" and i + 1 < len(args):
            try:
                ttl_min = float(args[i + 1])
            except ValueError:
                print(f"--cache-ttl needs a number, got {args[i + 1]!r}", file=sys.stderr)
                return 2
            i += 2
        elif args[i] in ("--refresh", "--no-cache"):
            use_cache = False; i += 1
        else:
            print(__doc__)
            return 1

    # ── batch mode: N postings, ONE process call, ONE model turn (speed lever #1) ──
    if batch_src is not None:
        try:
            urls = _read_url_list(batch_src)
        except OSError as e:
            print(json.dumps({"error": f"cannot read url list {batch_src!r}: {e}"}))
            return 2
        results, thin = [], []
        for u in urls:
            try:
                data = screen_one(u, max_chars, ttl_min, use_cache)
            except cfx.CfxError as e:
                # One bad posting must not sink the batch — record it and move on.
                results.append({"url": u, "error": str(e), "_cache": "miss"})
                continue
            if not data.get("error") and data.get("jd_text_full_len", 0) < 300:
                thin.append(u)
            results.append(compact(data) if want_compact else data)
        print(json.dumps(results, indent=1, ensure_ascii=False))
        n_err = sum(1 for r in results if r.get("error"))
        n_hit = sum(1 for r in results if r.get("_cache") == "hit")
        print(f"batch: {len(results)} posting(s), {n_hit} cache-hit, {n_err} error(s).",
              file=sys.stderr)
        if thin:
            print("WARN: under-rendered (SPA may not have loaded) — re-run --nav on "
                  "each before screening: " + ", ".join(thin), file=sys.stderr)
        return 0

    # ── single mode ──
    try:
        data = screen_one(nav_url, max_chars, ttl_min, use_cache)
    except cfx.CfxError as e:
        print(json.dumps({"error": str(e)}))
        return 2
    thin_warn = data.get("jd_text_full_len", 0) < 300
    print(json.dumps(compact(data) if want_compact else data, indent=1, ensure_ascii=False))
    if thin_warn:
        print("WARN: very little page text — SPA may not have rendered; re-run once "
              "before screening on this.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
