#!/usr/bin/env python3
"""feed.py — enumerate remote job postings from Himalayas via its public JSON API.

Himalayas is a remote-first board whose firehose API is **public and keyless** — a plain
HTTPS GET returning structured JSON (97k+ live postings). No key, no login, no browser,
so it runs anywhere the other httpfeed boards do. It is the highest-yield keyless remote
source in the repo: unlike RemoteOK it carries real employers rather than email gates.

On-profile because the applicant is London-or-fully-remote: this board is 100% remote
roles, and the API states each posting's *eligibility* explicitly, so UK-eligibility is
decidable from the feed alone (see FILTER below) rather than guessed from a title.

API shape (verified live 2026-07-17):
    GET https://himalayas.app/jobs/api?limit=20&offset=0
    -> {comments, updatedAt, offset, limit, totalCount, jobs:[…]}
    job: {title, excerpt, companyName, companySlug, companyLogo, employmentType,
          minSalary, maxSalary, salaryPeriod, currency, seniority[], categories[],
          locationRestrictions[], timezoneRestrictions[], description(HTML),
          pubDate(epoch), expiryDate(epoch), applicationLink, guid}

THREE verified API facts this feed is built around — do not "optimise" them away:
  1. `limit` is HARD-CAPPED AT 20 server-side. Asking for 50/100/250 still returns 20 and
     still reports `"limit":20`. Volume therefore comes from `--pages` (offset paging),
     never from a bigger limit.
  2. There is NO server-side keyword search. `search=`/`q=`/`keywords=`/`category=` are all
     silently IGNORED — each returns the identical newest-first firehose. `--what` is
     accepted only as the cooldown key; it does NOT narrow the query. That is fine and
     intentional: precheck.py screens titles, feeds must not.
  3. Results are newest-first by `pubDate`, so `--pages` walks backwards in time.

FILTER (location sanity only — never title):
  A posting is kept when it is plausibly workable from the UK:
    - `locationRestrictions` names the United Kingdom, OR
    - `locationRestrictions` is empty (worldwide) AND `timezoneRestrictions` is empty or
      includes UTC+0 (London).
  Everything else is a residency requirement the applicant cannot meet ("United States",
  "Philippines", …) — a British citizen would need sponsorship abroad. `--europe` widens
  the keep-set to EEA/European countries (off by default: those still require the right to
  work in that country). Measured yield: 48/400 sampled postings (12%) are UK-eligible.

Apply-path reality (measured, not assumed): the API gives NO direct ATS link —
`applicationLink` == `guid` == the himalayas.app job page, and only 6/400 sampled
descriptions contain an ATS URL (43/400 contain a mailto:). The job PAGES sit behind
Cloudflare — HTTP 403 "Just a moment…" to any plain GET regardless of headers, AND to
headless Chrome — even though this API endpoint is wide open (200). So:
  - sourcing + screening are fully HTTP-only: the whole JD ships as `description` in the
    API row, so nothing needs a page fetch;
  - but reaching the real ATS to APPLY needs the stealth browser (camofox/CFX). Plain
    urllib and vanilla headless Chrome both get challenged.
Consequently the common claim that Himalayas "links straight to real ATSes" is NOT verified
here — the outbound link is only observable from behind the Cloudflare challenge.

Usage:
    python3 feed.py [--what "<cooldown key>"] [--where London] [--pages N] [--europe]
                    [--all] [--force]
  --pages  offset pages of 20 (default 1 → ~2 UK-eligible). Use 10–25 for a real harvest.
  --europe also keep EEA/European-restricted roles (needs local right to work).
  --all    include already-tracked postings + bypass the cooldown gate.
"""
import datetime
import json
import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_here, "..", "..", "_common", "scripts"))
import httpfeed  # noqa: E402

BASE = "https://himalayas.app"
PER_PAGE = 20          # server-side hard cap — see fact (1) above.

UK_NAMES = {"united kingdom", "uk", "great britain", "england", "scotland", "wales",
            "northern ireland", "britain"}

# Opt-in only (--europe): the applicant is a British citizen, so these still imply needing
# the right to work locally. Kept as an explicit list rather than a fuzzy match.
EUROPE_NAMES = {
    "ireland", "germany", "france", "netherlands", "spain", "portugal", "italy", "poland",
    "sweden", "norway", "denmark", "finland", "belgium", "austria", "switzerland",
    "czechia", "czech republic", "romania", "bulgaria", "greece", "hungary", "croatia",
    "slovakia", "slovenia", "estonia", "latvia", "lithuania", "luxembourg", "malta",
    "cyprus", "iceland", "ukraine", "serbia", "europe", "emea", "european union", "eu",
}

CURRENCY_SYMBOL = {"USD": "$", "GBP": "£", "EUR": "€", "CAD": "CA$", "AUD": "A$"}


def _europe_enabled():
    return "--europe" in sys.argv


def search_url(what, where, page):
    """Offset paging. `what`/`where` are deliberately unused — the API ignores every
    keyword param (verified fact (2)); passing them would fake a filter that isn't real."""
    return f"{BASE}/jobs/api?" + httpfeed.urlencode({
        "limit": PER_PAGE, "offset": (page - 1) * PER_PAGE,
    })


def parse(text, ctx):
    """Pure: API JSON -> raw job rows. Returns ALL rows unfiltered so the runtime's
    short-page check (< PER_PAGE ⇒ end of results) stays meaningful; eligibility filtering
    belongs in normalize()."""
    try:
        payload = json.loads(text)
    except ValueError:
        return []
    jobs = payload.get("jobs")
    return [j for j in jobs if isinstance(j, dict)] if isinstance(jobs, list) else []


def eligibility(row, europe=False):
    """Pure: why this posting is (or isn't) workable from the UK.
    -> a short location label, or None to drop it."""
    restrictions = [str(c).strip() for c in (row.get("locationRestrictions") or []) if c]
    zones = row.get("timezoneRestrictions") or []
    lowered = {c.lower() for c in restrictions}

    if lowered & UK_NAMES:
        return "Remote (UK eligible)"
    if not restrictions:
        # Worldwide — keep only if London's timezone is actually workable.
        if not zones or 0 in zones:
            return "Remote (worldwide)"
        return None
    if europe and (lowered & EUROPE_NAMES):
        return "Remote (" + ", ".join(restrictions[:3]) + ")"
    return None


def _salary(row):
    cur = (row.get("currency") or "").upper()
    symbol = CURRENCY_SYMBOL.get(cur, (cur + " ") if cur else "£")
    text = httpfeed.money(row.get("minSalary"), row.get("maxSalary"), cur=symbol)
    if text and (row.get("salaryPeriod") or "annual") != "annual":
        text += f" / {row['salaryPeriod']}"
    return text


def _job_id(row):
    """Stable id from the guid path: '…/companies/indg/jobs/senior-ai-engineer'
    -> 'indg/jobs/senior-ai-engineer'. Verified consistent across 400/400 sampled rows,
    and matches seen_pattern's capture group exactly."""
    guid = (row.get("guid") or row.get("applicationLink") or "").split("?")[0]
    marker = "/companies/"
    if marker not in guid:
        return ""
    return guid.split(marker, 1)[1].strip("/")


def normalize(raw, ctx):
    """Pure: one API row -> the shared posting shape, or None when not UK-workable."""
    jid = _job_id(raw)
    title = httpfeed.clean(raw.get("title"))
    if not jid or not title:
        return None
    location = eligibility(raw, europe=ctx.get("europe", False))
    if not location:
        return None
    created = ""
    if raw.get("pubDate"):
        try:
            created = datetime.datetime.utcfromtimestamp(int(raw["pubDate"])).strftime("%Y-%m-%d")
        except (ValueError, OSError, OverflowError):
            created = ""
    return {
        "id": jid,
        "url": f"{BASE}/companies/{jid}",
        "title": title,
        "company": httpfeed.clean(raw.get("companyName")),
        "location": location,
        "salary": _salary(raw),
        "created": created,
        "ats_hint": "",        # resolves only on the (Cloudflare-walled) job page
        "source": "himalayas",
    }


BOARD = httpfeed.Board(
    board="himalayas", name="Himalayas", base=BASE,
    search_url=search_url, parse=parse, normalize=normalize,
    seen_pattern=r"himalayas\.app/companies/([A-Za-z0-9._-]+/jobs/[A-Za-z0-9._-]+)",
    fetch="http", per_page=PER_PAGE, default_where="Remote",
    headers={"Accept": "application/json"},
    sparse=True,   # ~12% of rows survive the UK filter — a barren page is normal, not the end
    apply_hint=("Iterate each .url; the full JD is already in the API row, but the job page "
                "is Cloudflare-challenged to plain HTTP AND headless Chrome, so reaching the "
                "apply link needs the stealth browser (camofox/CFX)."),
)

if __name__ == "__main__":
    BOARD.parse = parse
    _orig = normalize

    def _normalize_with_flag(raw, ctx):
        ctx["europe"] = _europe_enabled()
        return _orig(raw, ctx)

    BOARD.normalize = _normalize_with_flag
    sys.exit(httpfeed.main(BOARD))
