#!/usr/bin/env python3
"""feed.py — enumerate job postings from If You Could Jobs (ifyoucouldjobs.com).

It's Nice That's job board, and THE London junior/midweight design board. Highest
on-profile density of any board in this repo for the applicant's primary lane (§14
product/UX/digital design): the inventory is studios and in-house creative teams — Dusted,
Crown Creative, Apolitical, Future Factory — hiring at Junior/Midweight/Senior, and every
card ships an explicit **Level** field, so precheck can grade seniority without opening the
JD. Small board (~60 live), no aggregator noise, roles sit for weeks.

Plain server-rendered HTML — no browser, no key, no login. The whole board renders on ONE
page (there is no pagination: `?page=N` is ignored, verified live 2026-07-17), so a single
GET is a complete pass and `search_url` returns None for page>1.

Cards are `<article class="... job-item ...">` wrapping `a.job-link[href="/jobs/<ID>"]`
(ID is the stable numeric id used in the tracker URL). Verified live 2026-07-17:
  title    h2.heading-2
  company  h3.subtitle-2
  meta     a <dl> of <dt>Location|Level|Contract Type|Salary</dt><dd>value</dd> pairs

Search: `?search=<terms>` IS server-side (`?search=design` -> 30 of 61 cards, `?search=music`
-> 1 — verified live). The "Region or city" box is client-side only — there is no server-side
location param (`?location=London` returns the full 61), so `--where` is accepted and ignored
rather than pretended; precheck does the London/remote filtering.

Apply is off-site per employer and needs NO If You Could account: each JD carries either a
`mailto:` to the employer's careers address or a link to the employer's own site/ATS
(e.g. `edgecomply.com/jobs/...?ct=ifyoucould`). `ats_hint` is left empty — it only resolves
on the JD page (jd.py surfaces it).

Usage:
    python3 feed.py [--what "design"] [--all] [--force]
"""
import os
import re
import sys

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_here, "..", "..", "_common", "scripts"))
import httpfeed  # noqa: E402

BASE = "https://www.ifyoucouldjobs.com"

CARD_RE = r'(?is)<article class="[^"]*\bjob-item\b[^"]*".*?</article>'


def search_url(what, where, page):
    # The board is a single page — no server-side pagination exists.
    if page > 1:
        return None
    if what:
        return f"{BASE}/?" + httpfeed.urlencode({"search": what})
    return f"{BASE}/"


def parse(text, ctx):
    """Pure: HTML -> raw card chunks."""
    return [{"html": c} for c in httpfeed.cards(text, CARD_RE)]


def _dd(body, label):
    """Value of the <dd> following the <dt> whose text is `label`."""
    return httpfeed.first(
        body, rf'<dt[^>]*>\s*{re.escape(label)}\s*</dt>\s*<dd[^>]*>(.*?)</dd>')


def normalize(raw, ctx):
    """Pure: one card -> the shared posting shape."""
    body = raw.get("html") or ""
    m = re.search(r'(?is)href="(/jobs/(\d+))"', body)
    if not m:
        return None
    href, jid = m.group(1), m.group(2)
    title = httpfeed.first(body, r'(?is)<h2 class="heading-2"[^>]*>(.*?)</h2>')
    if not title:
        return None
    salary = _dd(body, "Salary")
    if salary.lower() in ("undisclosed", "competitive", "n/a", "-"):
        salary = ""
    return {
        "id": jid,
        "url": httpfeed.absolutise(href, BASE),
        "title": title,
        "company": httpfeed.first(body, r'(?is)<h3 class="subtitle-2"[^>]*>(.*?)</h3>'),
        "location": _dd(body, "Location"),
        "salary": salary,
        "level": _dd(body, "Level"),            # board-native seniority — precheck-friendly
        "contract": _dd(body, "Contract Type"),
        "ats_hint": "",                          # resolves per-employer on the JD
        "source": "ifyoucould",
    }


BOARD = httpfeed.Board(
    board="ifyoucould", name="If You Could Jobs", base=BASE,
    search_url=search_url, parse=parse, normalize=normalize,
    seen_pattern=r"ifyoucouldjobs\.com/jobs/(\d+)",
    fetch="http", default_where="London",
    apply_hint=("Iterate each .url; apply is off-site per employer (mailto: careers address "
                "or the employer's own site/ATS) — no If You Could account needed."),
)

if __name__ == "__main__":
    sys.exit(httpfeed.main(BOARD))
