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
import urllib.parse

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


# Board-native id patterns for canon_ids: each is a host-scoped regex with ONE capture
# group = that board's stable posting id. Matched against a LOWERCASED url, so keep them
# lowercase. Kept as a module constant so the whole dedup key space is auditable in one
# place. Each entry MUST mirror the same board's feed.py re-source pattern
# (sites/<board>/scripts/feed.py `load_seen`/`seen_pattern`) — otherwise the sourcing
# funnel and the apply/log/queue funnel key on different things and the same posting slips
# through one of them. Extended 2026-07-24 to cover every SOURCED non-canon board
# (adzuna/nhs/talent/jooble/careerjet/…): those used to hit the full-URL fallback below, so
# the same posting re-sourced with a different utm/redirect/query param produced a NEW key
# and got re-applied. Now they dedup on native id like the canon boards.
_CANON_PATTERNS = (
    r"linkedin\.com/jobs/view/(\d+)",
    r"currentjobid=(\d+)",
    r"[?&]jk=([0-9a-z]+)",
    r"welcometothejungle\.com/jobs/([a-z0-9_-]+)",
    r"civilservicejobs[^\"]*?(?:jcode=|joblist_view_vac=)(\d+)",
    r"recruitment\.hackney\.gov\.uk/vacancy/([a-z0-9-]+)",
    # Reed: canonical URL is `…/jobs/<slug>/<id>` but tracker rows are BARE `…/jobs/<id>`
    # (and some slugs) — all three shapes must dedup to the same numeric id or re-sources
    # report ~100% "fresh" (false-exhaustion).
    r"reed\.co\.uk/jobs/(?:[^/]+/)?(\d{5,8})",
    # Reed SEARCH-RESULTS shape: `/jobs/<slug>-jobs-in-<city>?q=…&jobId=57050584` — the id is a
    # QUERY PARAM, not a path segment, so the path pattern above misses it and canon_ids fell
    # back to the full URL. Live cost (2026-07-24): reed job 57050584 was logged TWICE — once
    # from reed_apply's synthesized `/jobs/ux-designer/<id>` URL and once from this search URL —
    # and the pre-submit guard couldn't match them, so it counted as two applications.
    r"reed\.co\.uk/[^\s]*?[?&]jobid=(\d{5,8})",
    r"greenhouse\.io/[^/]+/jobs/(\d+)",
    # ⛔ THE SAME Greenhouse job has FOUR URL shapes and they must all dedup (2026-08-16).
    # A job advertised on the employer's own careers page carries ?gh_jid=<id>; the canonical
    # form is boards.greenhouse.io/embed/job_app?token=<id>; apply_queue REWRITES the former to
    # the latter before driving. Without these patterns the careers-page URL and the embed URL
    # produced two DIFFERENT fallback keys (the whole URL), so a posting applied to via one
    # shape would not dedup against the other -> a second real application to the same job.
    # That is the same class as the Reed 57050584 double-application noted above.
    r"[?&]gh_jid=(\d+)",
    r'greenhouse\.io/embed/job_app\?[^\s"\']*?token=(\d+)',
    r"jobs\.lever\.co/[^/]+/([0-9a-f-]{8,})",
    r"ashbyhq\.com/[^/]+/([0-9a-f-]{8,})",
    r"myworkdayjobs\.com/.*/job/[^/]+/([^/?]+)",
    r"jobs\.theguardian\.com/job/(\d+)",
    # amazon.jobs — driver board (amazon_apply.py) with NO id pattern until now, so a
    # re-drive of the same jid only fallback-matched on exact URL → re-applied.
    r"amazon\.jobs/(?:[a-z-]+/)?jobs/(\d+)",
    # --- sourced non-canon boards (each mirrors that board's feed.py load_seen id) ---
    r"adzuna\.co\.uk/details/(\d+)",
    r"talent\.com/view\?id=(\d+)",
    r"jobs\.nhs\.uk/candidate/jobadvert/([a-z0-9][a-z0-9-]+)",
    r"careerjet\.co\.uk/jobad/([a-z0-9_-]+)",
    r"jooble\.org/(?:away|jdp)/([a-z0-9_-]+)",
    r"jobserve\.com/[^\"'\s]*?-([a-f0-9]{16,})",
    r"cv-library\.co\.uk/job/(\d{6,})",
    r"totaljobs\.com/job/[^\"'\s]*?-job(\d{6,})",
    r"the-dots\.com/jobs/[a-z0-9-]*?(\d+)\b",
    r"charityjob\.co\.uk/jobs/[^,\s]+?/(\d{5,})",
    r"applicationtrack\.com/[^,\s]*?/opp/(\d+)-",
    r"cybersecurityjobsite\.com/job/(\d+)",
    r"efinancialcareers\.co\.uk/jobs-[^\"'\s]*\.id(\d+)",
    r"hackajob\.com/job/([0-9a-f-]{36})",
    r"(?:jobsgopublic|lgjobs)\.com/job/(?:[^/,\s]*-)?(\d+)",
    r"thirdsector\.co\.uk/jobdetail/(\d+)",
    r"news\.ycombinator\.com/item\?id=(\d+)",
    r"careers\.bbc\.co\.uk/job/(?:[^/,\s]*/)?(\d+)",
    r"creativepool\.com/jobs/[^\s\"',]*\.(\d+)",
    r"designweek\.co\.uk/job/([a-z0-9-]+)",
    r"dezeenjobs\.com/job/[a-z0-9-]*?(\d+)",
    r"dribbble\.com/jobs/(\d+)",
    r"escapethecity\.org/opportunity/([^/?\s,\"]+)",
    r"findapprenticeship\.service\.gov\.uk/apprenticeship/(vac\d+)",
    r"himalayas\.app/companies/([a-z0-9._-]+/jobs/[a-z0-9._-]+)",
    r"ifyoucouldjobs\.com/jobs/(\d+)",
    r"jobicy\.com/jobs/(\d+)",
    r"jobs\.ac\.uk/job/([a-z0-9]+)",
    r"musicbusinessworldwide\.com/jobs/job/(\d+)",
    r"remotive\.com/remote-jobs/[^/\"]+/[a-z0-9-]+-(\d+)",
    r"jobs2web\.com/tfl/job/(?:[^/,\s]*/)?(\d+)",
    r"gchq-careers\.co\.uk/(?:job|vacancy)/[^,\s]*?(\d{4,})",
    r"parliament\.uk/[^,\s]*?vacancy_id=([a-z0-9]+)",
)


def canon_ids(url):
    """Stable, board-agnostic ids for a posting URL — dedup on canonical id, not
    URL equality (carousel params like ?theme=/?query= defeat URL matching)."""
    ids = set()
    if not url:
        return ids
    u = url.strip().lower()
    for pat in _CANON_PATTERNS:
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


# ⛔ PERMANENTLY EXCLUDED SOURCES (user decree 2026-07-20; Indeed + Reed restated 2026-08-15).
# talent.com and indeed.com are Cloudflare Turnstile / SmartApply walls the run cannot pass
# honestly; reed.co.uk is excluded by the same decree and by this run's standing instruction.
#
# This list already existed — in scripts/convertible_pool.py, which is GITIGNORED and is an
# ANALYSIS tool. So the ban was advisory, enforced only where nothing applies. Meanwhile
# pipeline.py still sources talent.com (17 of its rows were sitting in queue.jsonl when this
# was written) and apply_queue.py had no notion of an excluded source at all: nothing but luck
# — those rows happening not to classify as a hard board — kept the lane off them. A decree
# that lives only in a gitignored file is not enforcement. It belongs here, in the shared
# tracked module every lane already imports.
EXCLUDED_SOURCES = ("talent.com", "indeed.com", "uk.indeed.com", "reed.co.uk")


def excluded_source(*fields):
    """-> the matching excluded domain, or None. Pass any mix of url/board/source strings."""
    hay = " ".join(str(f or "") for f in fields).lower()
    for dom in EXCLUDED_SOURCES:
        if dom in hay:
            return dom
    return None



# ⛔ RIGHT-TO-WORK ANSWERS ARE COUNTRY-SCOPED (2026-08-16). The bank and gen_gh_config's
# TRUTHS both answer "authorised to work" -> Yes and "require sponsorship" -> No. Those are
# true of the UNITED KINGDOM — he is a British citizen — and FALSE of anywhere else. The
# patterns match any country's phrasing, so a US-scoped form got:
#     "Are you legally authorized to work in United States?"            -> Yes   (false)
#     "Will you now, or in future, require sponsorship (H1-B) …?"       -> No    (false)
# Caught on Yugabyte, whose location reads "Remote" so the region gate had no reason to stop
# it — the QUESTION is what reveals the posting is US-scoped.
#
# A false eligibility claim is the worst answer this system can produce: it is a
# misrepresentation to an employer about legal status, not a preference or an approximation.
# And the truthful answers ("No" / "Yes I need sponsorship") would make the application
# pointless anyway. So treat a foreign-country work-authorisation question as what it is —
# evidence the posting is out of scope — and hand it to a human.
_FOREIGN_RTW = re.compile(
    # NB [^?] not [^?.] — the real phrasing contains "i.e." and "etc.", and excluding the
    # period stopped the match dead before it reached the country name.
    r"(authoris|authoriz|right to work|eligible to work|entitled to work|work permit|"
    r"sponsorship|visa)"
    r"[^?]{0,90}?\b(united states|u\.?s\.?a?\b|america|canada|australia|singapore|india|"
    r"germany|france|netherlands|ireland|new zealand|japan|brazil|mexico|uae|"
    r"switzerland|spain|poland|israel)\b", re.I)
_UK_TOKENS = re.compile(r"united kingdom|\buk\b|britain|england|scotland|wales|"
                        r"northern ireland", re.I)


def foreign_work_authorisation(label):
    """-> the foreign country named in a work-authorisation question, or None.

    None when the question is UK-scoped or names no country (the bank's UK answer is then
    correct). A country name that is NOT the UK means the banked answer would be a false
    statement about legal status."""
    lab = (label or "")
    if not lab or _UK_TOKENS.search(lab):
        return None
    m = _FOREIGN_RTW.search(lab)
    return m.group(2) if m else None


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


# Query params that are pure tracking/attribution noise — safe to drop when STORING a URL so
# the same posting logged from two sources (utm_source=…, gh_src=…, ?ref=…) collapses to one
# dedup key. Id-bearing params (jk/id/currentjobid/jcode/vacancy_id/…) are NEVER listed here.
_TRACKING_PARAM = re.compile(
    r"^(utm_[a-z_]+|gh_src|gh_jid|src|source|ref|referer|referrer|origin|from|trk|trackingid|"
    r"mc_cid|mc_eid|fbclid|gclid|cid|ito|cmpid|_ga|wt\.mc_id)$", re.I)


def canonical_url(url):
    """Return a stable, storable form of a posting URL for the tracker, or '' if `url` is not
    a plausible http(s) posting URL. Drops the #fragment, strips known tracking/attribution
    query params (utm_*, gh_src, ref, fbclid, …) so two sources of the same posting collapse to
    one dedup key, and removes a trailing slash. Case and id-bearing params are preserved
    (WTTJ/Workday ids are case-sensitive; jk/id/jcode carry the id).

    Returning '' is the REJECT signal log-application.py uses to refuse a malformed value — the
    `https://www.reed.co.uk/jobs/{"ok":true` JSON-blob row that landed in the URL column and
    made that posting invisible to canon_ids dedup (so it was Applied twice). Anything carrying
    a character that never appears unescaped in a real posting URL ({ } " < > backtick,
    whitespace, backslash) is rejected outright."""
    s = (url or "").strip()
    if not s:
        return ""
    if re.search(r'[\s{}"<>`\\]', s):        # JSON blob / shell fragment / note text
        return ""
    if not re.match(r"https?://[^/]+\.[^/]", s, re.I):  # must be http(s)://host.tld…
        return ""
    try:
        parts = urllib.parse.urlsplit(s)
    except ValueError:
        return ""
    if not parts.netloc:
        return ""
    kept = [(k, v) for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
            if not _TRACKING_PARAM.match(k)]
    query = urllib.parse.urlencode(kept)
    path = parts.path.rstrip("/") or parts.path
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, query, ""))


def guard(url=None, company=None, role=None, label=""):
    """MANDATORY pre-submit duplicate gate — the ONE call every apply driver makes immediately
    before it submits. Returns True (having printed a standard ALREADY_APPLIED line) when this
    posting is already 'Applied'/'Applied?' in the tracker and the driver MUST skip; False to
    proceed. Non-exiting on purpose, so a batch driver can skip ONE posting and keep going
    (sys.exit would abort the whole run on the first dup). Matches on canon_ids(url) first, then
    Company+Role — see already_applied(). Blocked/Saved/Skipped/Unverified are NOT treated as
    applied, so a legitimate retry still proceeds."""
    hit = already_applied(url, company, role)
    if hit and is_applied(hit[0]):
        who = url or (f"{company} | {role}" if (company or role) else "?")
        tag = f" [{label}]" if label else ""
        print(f"ALREADY_APPLIED status={hit[0]!r} matched={hit[1]}{tag} — "
              f"refusing duplicate submit: {who}")
        return True
    # OFF-PROFILE WARNING (advisory, never blocks). The title screen runs at SOURCING, so a
    # driver invoked on an explicit URL never saw it — that is how a High-Voltage "Design
    # Engineer", a mid-level Software Engineer and a Content Marketer were applied to on
    # 2026-07-24 and counted toward the target, against SKILL.md's "never pad with off-profile
    # roles". Deliberately NOT a refusal: a tier-C stretch the operator chose on purpose is
    # legitimate, and a hard gate here would silently kill those. It just makes the off-profile
    # call VISIBLE at the moment of submit instead of after the fact.
    if role:
        try:
            from check_title import check_title
            v = check_title(role)
            if not v.get("eligible"):
                why = ("industrial/engineering 'design engineer', not a design role"
                       if v.get("discipline_flag") else
                       "above the junior→mid target band" if v.get("seniority_flag") else
                       "no target-roles.md phrase matches")
                print(f"⚠ OFF-PROFILE {role!r} — {why}. references/target-roles.md is the "
                      f"scope; SKILL.md forbids padding the count with off-profile roles. "
                      f"Proceeding (advisory only) — apply ONLY if this is a deliberate, "
                      f"tailored stretch.")
        except Exception:  # noqa: BLE001 — advisory check must never break an apply
            pass
    return False


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
    def london(s):
        return bool(re.search(r"(?<!new )\blondon\b", s))
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
    # "remote" is not the only word employers use for it (2026-08-15): Canonical posts every
    # distributed role as "Home based - EMEA" / "Home based - Worldwide", and because neither
    # string matched, seven genuinely UK-eligible roles were classified
    # `abroad (Home based - EMEA)` and skipped by the apply lane. Recognise the common
    # synonyms; EMEA/Europe/Worldwide are UK-INCLUSIVE regions, not foreign locations.
    if re.search(r"\bremote\b|work from home|home[\s-]?based|home[\s-]?working|"
                 r"work from anywhere|distributed", low):
        note = "remote"
        uk_ok = re.search(r"london|united kingdom|\buk\b|england|britain|"
                          r"\bemea\b|\beurope\b|\beu\b|europe/|worldwide|anywhere|global", low)
        # ⛔ "REMOTE, US" IS NOT REACHABLE EITHER (2026-08-16). A remote role restricted to
        # another country is exactly as unavailable to a UK-based applicant as an onsite one
        # abroad — the right-to-work answer is the same "no". This branch already SUSPECTED
        # as much ("verify region restriction in JD") but still returned a bare `keep`, so the
        # apply lane drove them: Keeper Security ("Remote, US"), Tailscale ("Remote (United
        # States)"), MyFitnessPal ("Remote - US") and Cresta ("United States (Remote)") all
        # passed the gate, burned the single serial tab, and then blocked on "What U.S. State
        # do you currently reside in?" — which was the single most frequent blocker in
        # drain23. Name the restriction so the apply lane can refuse it up front, while
        # sourcing still keeps the row (a human reading the JD may find a UK req attached).
        # A US TIME ZONE is a region restriction too (2026-08-16). Liftoff advertises
        # "Pacific Time Zone (Remote)" — no country named, so the country list below missed it
        # and the apply lane drove it, where it then blocked on "If you are seeking a remote
        # position, which US time zone are you located in?". Naming a US/Canadian working zone
        # is the restriction, however it is spelled.
        foreign = re.search(r"\bu\.?s\.?a?\b|united states|\bcanada\b|\bcanadian\b|\bindia\b|"
                            r"\baustralia\b|\bsingapore\b|\bbrazil\b|\blatam\b|\bapac\b|"
                            r"\banz\b|\bjapan\b|\bmexico\b|\bphilippines\b|"
                            r"\b(pacific|eastern|central|mountain)\s+time\b|"
                            r"\b(pst|pdt|est|edt|cst|cdt|mst|mdt)\b", low)
        if not uk_ok and foreign:
            return "keep", f"remote — region-restricted to {foreign.group(0).strip()} (non-UK)"
        if not uk_ok and re.search(r"[a-z]", re.sub(r"remote|home[\s-]?based", "", low)) \
                and len(low) > 8:
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


# Causes that will NOT change on a re-drive. A Blocked row whose note names one of these is
# spent: re-driving it can only burn another turn on the single serial tab.
_TERMINAL_NOTE = re.compile(
    r"terminal, do not re-queue|do not re-queue|"
    r"own browser|needs the user|user must apply|apply himself|"
    r"oath|attestation|responsible use policy|"
    r"off-location|remote - (?!uk\b)|no truthful right-to-work|"
    r"account (?:wall|required)|must (?:register|create an account)|sign ?in required|"
    r"attempt cap|past the \d+-attempt|\d+ attempts, all|"
    r"turnstile|hcaptcha", re.I)

# Causes that a code fix or a retry can plausibly clear.
_RETRYABLE_NOTE = re.compile(
    r"submit blocked by required/invalid field|timed out|timeout|"
    r"no confirmation|nav_fail|engine died|stale_or_dead_tab|dead tab", re.I)


def classify_blocked(status, note=""):
    """Three-way verdict for a tracker row: 'terminal' | 'retryable' | 'unknown'.

    ⛔ WHY THIS EXISTS (2026-08-16). "Blocked" means BOTH "retry this" and "never retry this",
    so a retry pool built from Blocked rows re-drives dead postings. In one session that cost
    four wasted drives on the single serial tab: Dotmatics, GoFundMe (already diagnosed after
    three attempts as needing the applicant's own browser) and three Twilio reqs (an anti-AI
    oath the applicant must sign himself; one also advertised Remote - India).

    'unknown' is a FIRST-CLASS verdict, not a synonym for 'retryable'. 75 of 140 Blocked rows
    carry no reason at all and cannot be backfilled — the evidence was never written to disk.
    Treating those as retryable is precisely the assumption that produced the wasted drives, so
    a caller must opt into them explicitly rather than get them by default."""
    st = (status or "").strip().lower()
    if st in ("applied", "applied?", "skipped"):
        return "terminal"
    txt = (note or "").strip()
    if not txt:
        return "unknown"
    if _TERMINAL_NOTE.search(txt):
        return "terminal"
    if _RETRYABLE_NOTE.search(txt):
        return "retryable"
    return "unknown"


def retry_pool(rows, include_unknown=False):
    """Tracker rows worth re-driving. `rows` are dicts or the raw CSV lists.

    Defaults to retryable-only. Pass include_unknown=True deliberately, knowing that an
    unexplained Blocked row is a coin flip paid for in serial-tab minutes."""
    out = []
    for r in rows:
        if isinstance(r, dict):
            status, note = r.get("Status") or r.get("status"), r.get("Notes") or r.get("notes")
        else:
            status = r[5] if len(r) > 5 else ""
            note = r[7] if len(r) > 7 else ""
        verdict = classify_blocked(status, note)
        if verdict == "retryable" or (include_unknown and verdict == "unknown"):
            out.append(r)
    return out


def drive_block(location=None, url=None, company=None, title=None):
    """-> reason string if this posting MUST NOT be driven, else None. Call at the top of
    every apply driver, before the first navigation.

    ⛔ WHY THIS LIVES HERE AND NOT IN THE QUEUE (2026-08-16, caught by driving them).
    This screen used to be `apply_queue._location_block` — one caller. But FIVE modules submit
    applications (`apply_queue.py`, `sites/greenhouse/scripts/gh_apply.py`,
    `sites/ashbyhq/scripts/ashby.py`, `sites/lever/scripts/lever.py`,
    `sites/recruitmentplatform/scripts/talentlink.py`), and the other four had no screen at
    all. So the gate only existed on ONE of the paths into a submit: anything that handed a
    driver a config directly — a retry pool, a hand-built cfg, a Hermes drive — walked straight
    past it. That is exactly what happened: a retry pool drove Twilio "Technical Support
    Engineer 1", advertised **Remote - India**, plus two sibling reqs, and burned the single
    serial tab on forms with no truthful right-to-work answer.

    This is the SAME defect shape as the CLAUDE.md/AGENTS.md split fixed the same day, and as
    SKILL.md §12 (the PII rule that lived only in CLAUDE.md and so was invisible to Hermes):
    **a rule enforced on one path is not enforced.** Put the refusal where every path must go
    through it, and make bypassing it the unusual, explicit act.

    `screen_location` deliberately returns `keep` for a region-restricted remote row so that
    SOURCING keeps it (a human reading the JD may find a UK req attached). The DRIVE lane has
    no model and pays a whole serial-tab drive per attempt, so here it refuses."""
    for field in (url, company, title):
        if field and excluded_source(field):
            return f"excluded source ({field})"
    verdict, reason = screen_location(location or "")
    if verdict == "drop":
        return reason
    if reason.startswith("remote — region-restricted"):
        return reason
    if verdict == "review" and reason.startswith("abroad"):
        return reason
    return None


def precheck(cands):
    by_id, by_pair = load_tracker()
    cache = load_salary_cache()
    # INTRA-BATCH dedup state: the tracker snapshot above is fixed at load time, so it
    # cannot catch duplicates that are all NEW this run (a single harvest routinely repeats
    # the same agency role under many different URLs). Track the canonical-ids and
    # Company+Role pairs we've already selected THIS batch and collapse the rest.
    seen_ids, seen_pairs = set(), set()
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
        bkey_ids = canon | ({str(c.get("id")).lower()} if c.get("id") else set())
        for i in bkey_ids:
            if i in by_id:
                status = by_id[i]
                break
        bpair = (_norm(c.get("company")), _norm(title))
        if status is None and bpair[0] and bpair[1] and bpair in by_pair:
            status = by_pair[bpair]
        if status:
            if status.lower() == "blocked":
                entry["verdict_reason"] = "tracked as Blocked — retry ONLY if the blocker is cleared"
                out["review"].append(entry)
            else:
                entry["verdict_reason"] = f"duplicate — already tracked ({status})"
                out["drop"].append(entry)
            continue

        # 1b) INTRA-BATCH dedup — a single harvest frequently repeats the SAME agency role
        # under many different URLs (Reed "itol recruit / Business Analyst Trainee" x15,
        # "IT Career Switch / Trainee Business Analyst" x10). None are in the tracker yet, so
        # every one passes the id/Company+Role snapshot check above and each gets driven →
        # duplicate applications to one role in a single day. Collapse to the first occurrence
        # (keep #1; drop the siblings) using the same canon-id + Company+Role keys.
        if (bkey_ids & seen_ids) or (bpair[0] and bpair[1] and bpair in seen_pairs):
            entry["verdict_reason"] = ("duplicate — same Company+Role already selected earlier "
                                       "in this batch (agency repost under a different URL)")
            out["drop"].append(entry)
            continue
        seen_ids |= bkey_ids
        if bpair[0] and bpair[1]:
            seen_pairs.add(bpair)

        # 2) title eligibility (code, not memory — full target-roles.md tier list)
        elig = c.get("eligibility") or check_title(title)
        entry["eligibility"] = elig
        if not elig.get("eligible"):
            if elig.get("discipline_flag"):
                reason = ("off-profile discipline — industrial 'design engineer' "
                          "(electrical/ICT/mechanical/CAD/…), not a UX/creative role")
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
