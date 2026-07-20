#!/usr/bin/env python3
"""ats_router.py — classify an external application URL to its ATS + the shipped driver that can
submit it. The single "auto-route brain" for every external-ATS hop: WTTJ's "Apply on company
website", escapecity / adzuna / LinkedIn "Apply on company website" redirects — anywhere a click
lands on some employer's own ATS and we need to know *which* recipe drives it.

Design honesty (matches references/convertible-drive-preaudit.md + SKILL.md):
  * Only **Ashby** and **Greenhouse** have shipped guest-submit drivers ("Greenhouse + Ashby are
    GUEST-DRIVABLE and convert — lead with those"). For those, `classify()` returns drivable=True
    plus the exact driver command template (a per-application config JSON is still built by the
    caller — there is no auto-config generator, by design; this router routes, it doesn't fabricate
    answers).
  * Lever / Workday / SmartRecruiters / Workable / … are RECOGNISED but have **no** submit driver,
    so they're drivable=False → routed to manual/VNC. Never a false auto-submit.
  * Unknown hosts → ats="unknown", drivable=False.

API:
    classify(url) -> dict(url, ats, drivable, driver, invoke, note)
CLI:
    python3 ats_router.py <url>          # prints the classification as JSON
    python3 ats_router.py <url> --brief  # prints "<ats>\t<drivable>\t<invoke-or-note>"
Exit: 0 if drivable (Ashby/Greenhouse), 3 if recognised-but-no-driver, 2 if unknown/missing url.
"""
import json
import re
import sys
from urllib.parse import urlparse

# Driver command TEMPLATES (relative to repo root). <config.json> is a placeholder the caller fills
# after building the application config (name/email/CV/answers) — the router never fabricates it.
_ASHBY = "python3 sites/ashbyhq/scripts/ashby.py apply <config.json> --submit"
_GREENHOUSE = "python3 sites/greenhouse/scripts/gh_apply.py <config.json>"

# host/URL pattern → (ats, drivable, driver-path-or-None, invoke-or-None, note)
# Order matters: first match wins, so put the most specific patterns first.
_RULES = [
    # ── the two GUEST-DRIVABLE ATSes (shipped submit drivers) ──────────────────────────────────
    (r"(^|\.)ashbyhq\.com($|/)|jobs\.ashbyhq\.com",
     ("ashby", True, "sites/ashbyhq/scripts/ashby.py", _ASHBY, "guest-drivable")),
    (r"(^|\.)greenhouse\.io($|/)|boards\.greenhouse\.io|job-boards\.greenhouse\.io|(^|\.)grnh\.se($|/)|greenhouse\.io/embed",
     ("greenhouse", True, "sites/greenhouse/scripts/gh_apply.py", _GREENHOUSE, "guest-drivable")),
    # ── RECOGNISED ATSes with NO shipped submit driver → route to manual/VNC ───────────────────
    (r"jobs\.lever\.co|(^|\.)lever\.co($|/)",
     ("lever", False, None, None, "recognised ATS, no shipped driver — manual/VNC")),
    (r"(^|\.)myworkdayjobs\.com|(^|\.)workday\.com($|/)",
     ("workday", False, None, None, "Workday — only nav_to_link.py exists, no submit driver — manual/VNC")),
    (r"(^|\.)smartrecruiters\.com",
     ("smartrecruiters", False, None, None, "recognised ATS, no shipped driver — manual/VNC")),
    (r"(^|\.)workable\.com|apply\.workable\.com",
     ("workable", False, None, None, "recognised ATS, no shipped driver — manual/VNC")),
    (r"(^|\.)recruitee\.com",
     ("recruitee", False, None, None, "recognised ATS, no shipped driver — manual/VNC")),
    (r"(^|\.)teamtailor\.com",
     ("teamtailor", False, None, None, "recognised ATS, no shipped driver — manual/VNC")),
    (r"(^|\.)bamboohr\.com",
     ("bamboohr", False, None, None, "recognised ATS, no shipped driver — manual/VNC")),
    (r"(^|\.)pinpointhq\.com|(^|\.)pinpoint\.xyz",
     ("pinpoint", False, None, None, "recognised ATS, no shipped driver — manual/VNC")),
    (r"(^|\.)jobvite\.com|(^|\.)jobs\.jobvite\.com",
     ("jobvite", False, None, None, "recognised ATS, no shipped driver — manual/VNC")),
    (r"(^|\.)icims\.com",
     ("icims", False, None, None, "recognised ATS, no shipped driver — manual/VNC")),
    (r"(^|\.)taleo\.net|(^|\.)tal\.net",
     ("taleo", False, None, None, "recognised ATS, no shipped driver — manual/VNC")),
    (r"(^|\.)breezy\.hr",
     ("breezy", False, None, None, "recognised ATS, no shipped driver — manual/VNC")),
    (r"(^|\.)rmkcloud\.com|successfactors|(^|\.)sapsf\.com|(^|\.)sac\.successfactors",
     ("successfactors", False, None, None, "SuccessFactors RMK — needs an RMK account (BBC/TfL) — manual/VNC")),
    (r"(^|\.)eightfold\.ai|(^|\.)apply\.eightfold",
     ("eightfold", False, None, None, "recognised ATS, no shipped driver — manual/VNC")),
    (r"(^|\.)typeform\.com|form\.typeform\.com",
     ("typeform", False, None, None, "Typeform — conversational form, no shipped driver + anti-bot — manual/VNC")),
    (r"(^|\.)ashbyhq|(^|\.)gh_",  # never hit (above), kept as a guard against accidental reorder
     ("unknown", False, None, None, "unknown")),
]


def classify(url):
    """Classify an external application URL. Returns a dict:
        {url, ats, drivable(bool), driver(path|None), invoke(cmd-template|None), note}
    `invoke` still contains a literal '<config.json>' the caller substitutes after building the
    per-application config. `drivable` is True ONLY for Ashby/Greenhouse."""
    u = (url or "").strip()
    out = {"url": u, "ats": "unknown", "drivable": False, "driver": None,
           "invoke": None, "note": "unknown host — no ATS recognised"}
    if not u:
        out["note"] = "empty url"
        return out
    # match against host + full url (some ATSes live on a path, e.g. company.com/careers?gh_jid=)
    host = (urlparse(u).netloc or "").lower()
    hay = f"{host} {u.lower()}"
    # greenhouse also embeds via query param gh_jid / gh_src on a company domain
    if re.search(r"[?&]gh_(jid|src)=", u):
        return {"url": u, "ats": "greenhouse", "drivable": True,
                "driver": "sites/greenhouse/scripts/gh_apply.py", "invoke": _GREENHOUSE,
                "note": "guest-drivable (greenhouse embed via gh_jid)"}
    for pat, (ats, drivable, driver, invoke, note) in _RULES:
        if ats == "unknown":
            continue
        if re.search(pat, hay):
            return {"url": u, "ats": ats, "drivable": drivable, "driver": driver,
                    "invoke": invoke, "note": note}
    return out


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 2
    res = classify(args[0])
    if "--brief" in argv:
        print(f"{res['ats']}\t{res['drivable']}\t{res['invoke'] or res['note']}")
    else:
        print(json.dumps(res, indent=2))
    return 0 if res["drivable"] else (2 if res["ats"] == "unknown" else 3)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
