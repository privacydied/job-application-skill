#!/usr/bin/env python3
"""
precheck.py — run the ENTIRE cheap pre-filter over a whole feed list in ONE call.

WHY THIS EXISTS (speed lever 4 against slow inference): the pre-filter (title
eligibility, location hard screen, tracker dedup, salary-cache lookup) is
deterministic code-shaped judgment, but the loop was spending model attention per
card — one check_title call here, a tracker grep there — and prose-recall misses
things (documented live 2026-07-13: on-profile Tier B/C roles silently dropped).
This composes all of it: pipe a feed.py output list in, get keep/review/drop
verdicts for every candidate back, in one model turn total.

    python3 precheck.py <candidates.json | ->        # '-' reads stdin
    python3 sites/linkedin/scripts/feed.py --nav "…" | python3 precheck.py -

Input: a JSON list (or {"candidates":[…]}) of {id?, url?, title, company?, location?}
— exactly what the feed.py scripts print.

Output: JSON {"keep":[…], "review":[…], "drop":[…]}; each entry is the original
candidate plus:
  verdict_reason   why it landed in that bucket (drop reasons are tracker-ready
                   Skipped notes)
  eligibility      check_title verdict (tier / matched_phrase / seniority_flag)
  salary_median    cached Glassdoor-median if salary-cache.csv has a role+location
                   match (absence means "no cache entry", NOT "no salary data")

Buckets:
  keep    title-eligible, location passes the hard screen, not a tracker dup —
          open these JDs (with jd.py) and do the full SKILL.md screen.
  review  ambiguous by metadata alone (generic "United Kingdom", abroad —
          sponsorship unknown, blocked-earlier retryable, no location) — the JD's
          own location/work-model line settles it; don't drop without looking.
  drop    deterministic rejects: ineligible/senior title, non-London UK city,
          already tracked. Log real on-board postings as Skipped with the given
          reason; junk promoted cards can drop silently (loop-prompt §2).

The location rules mirror SKILL.md "Location / relocation": London ok; genuinely
remote ok; other-UK-city onsite/hybrid NEVER (no UK relocation); abroad only with
sponsorship (=> review, JD decides). This is metadata screening — when in doubt it
says review, not drop.
"""
import csv
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from check_title import check_title  # noqa: E402

UK_CITIES = ("manchester", "leeds", "bristol", "birmingham", "edinburgh", "glasgow",
             "cambridge", "oxford", "brighton", "cardiff", "belfast", "sheffield",
             "liverpool", "newcastle", "nottingham", "reading", "milton keynes",
             "southampton", "york", "bath", "coventry", "leicester")


def _root():
    d = os.path.dirname(os.path.abspath(__file__))
    while True:
        if os.path.isfile(os.path.join(d, "SKILL.md")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        d = parent


def canon_ids(url):
    """Stable, board-agnostic ids for a posting URL — dedup on canonical id, not
    URL equality (carousel params like ?theme=/?query= defeat URL matching)."""
    ids = set()
    if not url:
        return ids
    u = url.strip().lower()
    for pat in (r"linkedin\.com/jobs/view/(\d+)", r"currentjobid=(\d+)",
                r"[?&]jk=([0-9a-f]+)", r"welcometothejungle\.com/jobs/([a-z0-9_-]+)",
                r"civilservicejobs[^\"]*?(?:jcode=|joblist_view_vac=)(\d+)",
                r"recruitment\.hackney\.gov\.uk/vacancy/([a-z0-9-]+)",
                # Reed: canonical URL is `…/jobs/<slug>/<id>` but tracker rows are BARE
                # `…/jobs/<id>` (and some slugs) — all three shapes must dedup to the
                # same numeric id or re-sources report ~100% "fresh" (false-exhaustion).
                r"reed\.co\.uk/jobs/(?:[^/]+/)?(\d{5,8})",
                r"greenhouse\.io/[^/]+/jobs/(\d+)", r"jobs\.lever\.co/[^/]+/([0-9a-f-]{8,})",
                r"ashbyhq\.com/[^/]+/([0-9a-f-]{8,})", r"myworkdayjobs\.com/.*/job/[^/]+/([^/?]+)",
                r"jobs\.theguardian\.com/job/(\d+)"):
        m = re.search(pat, u)
        if m:
            ids.add(m.group(1))
    if not ids:
        # Fallback for boards with no known id pattern. Keep the query string —
        # stripping it collided every `…/viewjob?jk=X` into one key (found live in
        # testing: a fresh Indeed posting deduped against an old one). Only the
        # fragment is always safe to drop.
        ids.add(re.sub(r"#.*$", "", u).rstrip("/"))
    return ids


def _norm(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def load_tracker():
    """(id_or_url -> status, (company,role) -> status) from application-tracker.csv."""
    by_id, by_pair = {}, {}
    path = os.path.join(_root(), "application-tracker.csv")
    try:
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                status = (row.get("Status") or "").strip()
                if not status:
                    continue
                for i in canon_ids(row.get("URL") or ""):
                    by_id[i] = status
                pair = (_norm(row.get("Company")), _norm(row.get("Role")))
                if pair[0] and pair[1]:
                    by_pair[pair] = status
    except (OSError, csv.Error):
        pass
    return by_id, by_pair


def already_applied(url=None, company=None, role=None):
    """APPLY-TIME duplicate guard for DRIVERS that take a URL directly and thus BYPASS the
    sourcing precheck (e.g. jobs.theguardian.com/apply.py, reed_apply.py, a hand-driven URL).
    The sourcing funnel already drops tracked rows (merge_sources), but a driver invoked on an
    explicit URL never saw that screen — so it can re-drive an Applied posting and burn a real
    submit/CAPTCHA on a duplicate (the REVIVA 10126456 re-attempt). This is the ONE canonical
    check for that: it reuses canon_ids (board-agnostic id match, robust to slug/#fragment/query)
    then Company+Role, against the live tracker.

    Returns (status, matched_by) if a tracker row matches, else None. `matched_by` is
    "id:<canon>" or "company+role". Callers decide: `is_applied(status)` => skip the drive;
    a "Blocked" status => re-drive only if the blocker is known cleared. Never raises."""
    by_id, by_pair = load_tracker()
    for i in canon_ids(url):
        if i in by_id:
            return (by_id[i], f"id:{i}")
    if company and role:
        pair = (_norm(company), _norm(role))
        if pair in by_pair:
            return (by_pair[pair], "company+role")
    return None


def is_applied(status):
    """True if a tracker status means 'already submitted — do not re-drive' (Applied / Applied?).
    Blocked/Saved/Unverified are deliberately NOT applied (a driver may legitimately proceed)."""
    return (status or "").strip().lower().startswith("applied")


def load_seen(pattern, tracker=None):
    """Set of ids already in the tracker matching `pattern` (a regex with ONE capture group),
    scanned over RAW lines — csv-quoting-proof, so a malformed/quoted row can't blow it up
    (only the id tokens are needed, not a full parse). This is the board feeds' pre-source
    dedup, previously duplicated 5× as `load_seen_ids`/`load_seen_jks`/`load_seen_slugs`; each
    feed now passes its own board id regex (e.g. r'linkedin\\.com/jobs/view/(\\d+)')."""
    path = tracker or os.path.join(_root(), "application-tracker.csv")
    seen = set()
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                seen.update(re.findall(pattern, line))
    except FileNotFoundError:
        pass
    return seen


def load_salary_cache():
    rows = []
    path = os.path.join(_root(), "salary-cache.csv")
    try:
        with open(path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    except (OSError, csv.Error):
        pass
    return rows


def salary_for(title, location, cache):
    tl, ll = (title or "").lower(), (location or "").lower()
    # Same word-boundary+new-lookbehind guard as screen_location: a bare `"london" in ll`
    # would attach a London salary median to "Londonderry"/"New London" (naive-match class).
    london = lambda s: bool(re.search(r"(?<!new )\blondon\b", s))
    for row in cache:
        role = (row.get("Role") or "").lower()
        loc = (row.get("Location") or "").lower()
        if role and (role in tl or tl in role) and \
           (london(loc) and (london(ll) or "remote" in ll or not ll or "united kingdom" in ll)):
            return {"salary_median": row.get("Median"), "salary_currency": row.get("Currency"),
                    "salary_cached": row.get("DateChecked")}
    return {}


def screen_location(location):
    """-> (verdict, reason). verdict in keep/review/drop. Metadata-only — the JD's
    own location line is authoritative for anything ambiguous."""
    low = (location or "").strip().lower()
    if not low:
        return "review", "no location metadata — read the JD's location line"
    # "(?<!new )york" — "New York, NY" is NOT the UK city (found live in testing).
    cities = [c for c in UK_CITIES
              if re.search(r"(?<!new )\b" + c + r"\b" if c == "york" else r"\b" + c + r"\b", low)]
    if re.search(r"\bremote\b|work from home", low):
        note = "remote"
        if not re.search(r"london|united kingdom|\buk\b|england|britain", low) and \
           re.search(r"[a-z]", low.replace("remote", "")) and len(low) > 8:
            note = "remote — verify region restriction (non-UK wording) in JD"
        return "keep", note
    # Word-boundary + new-lookbehind (mirrors the york guard above): a bare
    # `"london" in low` naively kept "Londonderry" (NI, not commutable) and "New
    # London, CT" (US) as London — the same substring-false-cognate class as the
    # industrial-"design engineer" leak.
    if re.search(r"(?<!new )\blondon\b", low):
        return "keep", "london"
    if cities:
        return "drop", f"location — {cities[0].title()}, no relocation within UK"
    if re.search(r"united kingdom|\buk\b|england|scotland|wales|britain", low):
        return "review", "generic UK location — could be London/remote; JD decides"
    return "review", f"abroad ({location.strip()}) — onsite only acceptable WITH sponsorship; JD decides"


# In the UK Civil Service the seniority signal is the GRADE, not the title word:
# AA/AO/EO/HEO/SEO are junior→mid (SEO tops out ≈ £50–55k in London), G7/G6/SCS are
# senior. CSJ titles routinely say "Senior X" or "X Manager" at an SEO/HEO grade, so
# a plain title-word DROP silently kills genuinely on-band roles (measured: real
# design/UX/research matches at £40–52k were being dropped as "senior"). Below this
# ceiling a seniority-flagged CSJ title is DOWNGRADED to `review` (open the JD to read
# the grade) instead of dropped; above it, or with an unambiguous senior grade token,
# it stays dropped. Non-CSJ boards are untouched — there "Senior" is a real level.
CSJ_JUNIOR_MID_CEIL = 55000
_CSJ_HOST = "civilservicejobs.service.gov.uk"
# Unambiguous senior grades / titles — keep dropping even if the pay band is missing.
_SENIOR_GRADE_RE = re.compile(
    r"\b(g6|g7|grade\s*[67]|scs\d?|senior civil service|deputy director|director|"
    r"head of|chief|principal)\b", re.I)


def salary_band_top(s):
    """Top of the £ band on a card as an int, or None. '£42,665 to £50,495' -> 50495;
    '£37,456 - £42,084 p.a.' -> 42084. Ignores sub-£1000 noise (needs 4+ digits)."""
    nums = [int(x.replace(",", "")) for x in re.findall(r"£\s?([\d][\d,]{3,})", s or "")]
    return max(nums) if nums else None


def precheck(cands):
    by_id, by_pair = load_tracker()
    cache = load_salary_cache()
    out = {"keep": [], "review": [], "drop": []}
    for c in cands:
        if not isinstance(c, dict):
            continue
        entry = dict(c)
        title = c.get("title") or ""

        # 1) tracker dedup (id/url first, then Company+Role)
        # C.5: reuse merge_sources' stashed canonical-id set when present instead of
        # re-running the 10-regex canon_ids sweep on the same URL.
        status = None
        canon = set(c.get("_canon_ids") or ()) or canon_ids(c.get("url") or "")
        for i in canon | ({str(c.get("id")).lower()} if c.get("id") else set()):
            if i in by_id:
                status = by_id[i]
                break
        if status is None:
            pair = (_norm(c.get("company")), _norm(title))
            if pair[0] and pair[1] and pair in by_pair:
                status = by_pair[pair]
        if status:
            if status.lower() == "blocked":
                entry["verdict_reason"] = "tracked as Blocked — retry ONLY if the blocker is cleared"
                out["review"].append(entry)
            else:
                entry["verdict_reason"] = f"duplicate — already tracked ({status})"
                out["drop"].append(entry)
            continue

        # 2) title eligibility (code, not memory — full target-roles.md tier list)
        elig = c.get("eligibility") or check_title(title)
        entry["eligibility"] = elig
        if not elig.get("eligible"):
            if elig.get("discipline_flag"):
                reason = (f"off-profile discipline — industrial 'design engineer' "
                          f"(electrical/ICT/mechanical/CAD/…), not a UX/creative role")
            elif elig.get("seniority_flag"):
                reason = "title carries a seniority word — off-profile"
            else:
                reason = "title not in target-roles.md tiers"
            entry["verdict_reason"] = reason
            out["drop"].append(entry)
            continue
        if elig.get("seniority_flag"):
            is_csj = _CSJ_HOST in (c.get("url") or "")
            band_top = salary_band_top(c.get("salary"))
            grade = (c.get("grade") or "").upper().replace(" ", "")
            # An explicit grade token from the feed is authoritative when present:
            # G7/G6/SCS = senior (keep dropping), AA/AO/EO/HEO/SEO = junior→mid (rescue).
            grade_senior = grade in ("G7", "G6", "GRADE7", "GRADE6") or grade.startswith("SCS")
            grade_junior = grade in ("AA", "AO", "EO", "HEO", "SEO")
            # CSJ rescue: a target-tier role with a seniority WORD but junior-mid GRADE
            # (explicit) or PAY (inferred) is not a senior hire — review, don't drop.
            if (is_csj and not grade_senior and not _SENIOR_GRADE_RE.search(title)
                    and (grade_junior
                         or (band_top is not None and band_top <= CSJ_JUNIOR_MID_CEIL))):
                entry.update(salary_for(title, c.get("location"), cache))
                sig = (f"grade {grade}" if grade_junior
                       else f"junior-mid pay (£{band_top:,} top ≈ EO/HEO/SEO)")
                entry["verdict_reason"] = (
                    f"CSJ: matched {elig.get('matched_phrase')!r} with a seniority word BUT "
                    f"{sig} — open the JD to confirm the grade; not a title-word drop")
                out["review"].append(entry)
                continue
            entry["verdict_reason"] = (f"matched {elig.get('matched_phrase')!r} but title has a "
                                       "seniority word — off-profile on seniority grounds"
                                       + (f" (CSJ pay £{band_top:,} ≥ G7 senior band)"
                                          if is_csj and band_top else ""))
            out["drop"].append(entry)
            continue

        # 3) location hard screen
        verdict, reason = screen_location(c.get("location") or "")
        entry["verdict_reason"] = reason
        entry.update(salary_for(title, c.get("location"), cache))
        out[verdict if verdict != "keep" else "keep"].append(entry)
    return out


def main():
    a = sys.argv[1:]
    if len(a) != 1:
        print(__doc__)
        return 1
    try:
        raw = sys.stdin.read() if a[0] == "-" else open(a[0], encoding="utf-8").read()
        data = json.loads(raw)
    except (OSError, ValueError) as e:
        print(f"FAIL: cannot read candidates: {e}", file=sys.stderr)
        return 2
    cands = data.get("candidates") if isinstance(data, dict) else data
    if not isinstance(cands, list):
        print("FAIL: input must be a JSON list of candidates", file=sys.stderr)
        return 2
    out = precheck(cands)
    print(json.dumps(out, indent=1, ensure_ascii=False))
    print(f"precheck: {len(out['keep'])} keep / {len(out['review'])} review / "
          f"{len(out['drop'])} drop of {len(cands)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
