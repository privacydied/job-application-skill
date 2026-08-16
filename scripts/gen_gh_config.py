#!/usr/bin/env python3
"""gen_gh_config.py — build a gh_apply config from Greenhouse's KEYLESS questions API.

WHY (2026-08-15): building a config used to mean driving the browser to the posting, running
inspect_gh_form.py, opening every react-select to read its options, and hand-writing JSON —
several minutes of the single serial camofox tab per application, which is the scarcest
resource in the whole loop. But Greenhouse publishes the entire application form over a
keyless HTTP endpoint:

    https://boards-api.greenhouse.io/v1/boards/<slug>/jobs/<id>?questions=true

…returning every question's label, `required` flag, field type, AND — for selects — the exact
`.values[].label` strings a combo must match byte-for-byte. So a complete, correct config can
be produced with NO browser at all, and the tab is reserved purely for submitting.

USAGE (no browser, no credentials needed):
    python3 scripts/gen_gh_config.py <slug> <jobid> [--eu] [--out <path>]
    python3 scripts/gen_gh_config.py --batch <file>     # lines: slug|jobid[|eu]

Writes applications/_cfg/<slug>-<role-slug>.json and prints a report. Questions it cannot
answer TRUTHFULLY are left out and listed under NEEDS_HUMAN — never guessed. Review the
generated file before driving: free-text answers get a generic truthful value, and a role
worth applying to deserves a tailored one.
"""
import argparse
import json
import os
import re
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG_DIR = os.path.join(ROOT, "applications", "_cfg")

API = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{jid}?questions=true"

# Identity + résumé are filled by gh_apply from apply-defaults.json — never put them in a config.
SKIP = re.compile(
    r"^(first name|last name|full name|preferred name|email|phone|resume|cv|resume/cv|"
    r"cover letter|"
    # Personal links/pronouns: gh_apply fills these from the gitignored apply-defaults.json
    # via `defaults`. Emitting them here would mean hardcoding PII in a TRACKED file.
    r"linkedin.*|.*portfolio.*|website.*|.*github.*|pronouns?)$", re.I)

# (label pattern, answer). Order matters — first match wins, so put specific before generic.
# Every answer here is TRUE for this applicant: British citizen, London-based, no sponsorship,
# immediately available, no current employment at the target company.
TRUTHS = [
    (r"require.{0,30}(visa )?sponsorship|need.{0,20}sponsorship|sponsorship.{0,20}(now|future)", "No"),
    (r"authoris?z?ed to work|legal right to work|right to work|eligible to work", "Yes"),
    (r"notice period", "Available immediately"),
    (r"earliest.{0,20}(start|available)|when.{0,20}(can you|could you).{0,15}start", "Immediately"),
    (r"salary (expectation|requirement)|expected salary|compensation expectation", "GBP 55,000"),
    (r"referred.{0,30}(by|to this role)|employee referral", "No"),
    (r"(currently|ever|previously).{0,25}(employed|worked|been).{0,20}(by|at|for|part of)", "No"),
    (r"current or former .{0,20}employee", "No"),
    (r"interviewed.{0,25}(with|at|before)|previously (applied|interviewed)", "No"),
    (r"related to anyone|relatives.{0,20}work|know anyone.{0,25}(who works|at)", "No"),
    (r"who do you know that works", "No one"),
    (r"at least 18|over 18|18 years", "Yes"),
    (r"do you have a linkedin", "Yes"),
    # He IS a crypto/blockchain-sector alum — CryptoKnowledge (Frontend Dev & DevOps,
    # Dec 2024-Jul 2025) was a crypto/finance education company. Answering "Yes" is true.
    (r"(worked|experience).{0,30}(crypto|blockchain|digital asset)", "Yes"),
    (r"current (employer|company)", "CryptoKnowledge (most recent)"),
    (r"current job title|current.{0,10}role|most recent (job )?title", "Frontend Developer & DevOps"),
    (r"desired compensation", "GBP 55,000"),
    # Office-attendance questions: he lives in London, so a London-office requirement is a
    # truthful Yes. Deliberately narrow — it must name an office/days, not relocation.
    (r"(london )?office.{0,30}(days?|week)|work from our .{0,20}office", "Yes"),
    (r"interview.{0,40}(record|transcri|metaview|notetak)", "Yes"),
    (r"confidentiality regime|privacy and confidentiality", "__CONSENT__"),
    (r"data transfer", "__CONSENT__"),
    (r"willing to relocate|open to relocat", "No"),
    (r"reasonable adjustment|accommodation", "No"),
    (r"how did you hear", "Job Board"),
    # NOTE: LinkedIn / portfolio / website / GitHub / pronouns are deliberately NOT here.
    # They are personal data, and this file is TRACKED — hardcoding them is exactly the leak
    # AGENTS.md §PII forbids ("drivers must not hardcode PII"), which is why scrub_pii.py
    # rewrote an earlier version of these lines to placeholders. Placeholders would then be
    # written into real applications, which is worse than useless. They live in the gitignored
    # apply-defaults.json and gh_apply already fills them via `defaults`, so the right move is
    # to emit nothing and let the config-routing model supply the real values at drive time.
    # They are listed in SKIP below for the same reason.
    (r"country.{0,20}(reside|based|located|work)|where are you based|current country", "United Kingdom"),
    (r"^location|location \(city\)|city", "London"),
    (r"privacy (notice|policy|statement)|data protection|acknowledge", "__CONSENT__"),
    (r"gender", "Male"),
]

# Questions we must NOT answer without the applicant: personal preferences and facts the
# profile genuinely does not record. Guessing these is fabrication, and shift/travel/clearance
# answers in particular are life constraints, not form-filling details.
NEEDS_HUMAN = re.compile(
    r"shift|night|weekend|on-call|rota|"
    r"security clearance|\bSC\b|\bDV\b|vetting|"
    r"driving licen[cs]e|driver|own vehicle|"
    r"years of experience with|how many years",
    re.I)

# Anti-AI oath — never sign one (see atsform.combobox_pick's ANTI-AI OATH GUARD).
ANTI_AI = re.compile(r"only my own words|\bno ai\b|ai[- ]?generated|use of ai", re.I)

# Consent/acknowledgement questions rendered as a SELECT whose only option is the whole policy
# text. Deliberately narrow: it must read like an acknowledgement, not merely mention data.
_CONSENTISH = re.compile(
    r"by checking this box|i (confirm|agree|acknowledge|understand|consent)|"
    r"please confirm|acknowledge|privacy (notice|policy|statement)|"
    r"keeping your data safe|terms and conditions|data protection", re.I)


def _is_affirmative_answer(ans):
    """Only escalate to the __CONSENT__ matcher for an answer that is already a YES. Guards
    against turning a truthful refusal into agreement."""
    return str(ans or "").strip().lower() in {
        "yes", "y", "true", "agree", "i agree", "accept", "acknowledge", "__consent__"}


def fetch(slug, jid, eu=False):
    url = API.format(slug=slug, jid=jid)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


def pick_option(values, want):
    """Choose the option whose label best matches `want`, EXACTLY where possible.
    Greenhouse binds on exact option text, so a near-miss silently fails to bind."""
    labels = [v.get("label", "") for v in values if v.get("label")]
    if not labels:
        return None
    if want == "__CONSENT__":
        # A consent/acknowledgement select usually has ONE affirmative option — and it is
        # often the entire policy text as the label, so match loosely and fall back to the
        # sole option when there is exactly one.
        for l in labels:
            if re.search(r"acknowledge|i agree|^agree|confirm|accept|^yes\b|consent", l, re.I):
                return l
        return labels[0] if len(labels) == 1 else None

    if want == "Job Board":
        # "How did you hear about this job?" option sets are per-company and rarely contain
        # the literal words "Job Board". Prefer the company's own careers site (true: these
        # postings were sourced from the employer's own ATS board), then a generic job board,
        # then LinkedIn, then Other. Never leave it to a blind substring match, which would
        # happily pick "Facebook".
        # ⛔ AN OPTION CAN CARRY A CLAIM (2026-08-16 — submitted before this existed). The
        # `job ?board` pattern matched Jane Street's "University job board", so the
        # application states he heard about the role through a university board. He is not a
        # student — the SAME form recorded "Are you currently a student? No" three lines
        # later. A "how did you hear" option is not neutral when it names an affiliation:
        # university/alumni/veteran/diversity boards all assert something about the applicant.
        # Drop any option carrying such a qualifier before matching, and if only qualified
        # ones remain, fall through rather than pick one.
        affiliated = re.compile(r"universit|college|school|campus|alumni|student|"
                                r"veteran|military|bootcamp|diversity|women|hbcu|"
                                r"employee referral|referral", re.I)
        neutral = [l for l in labels if not affiliated.search(l)]
        # Order is by what is actually TRUE of how this run finds work: the employer's own
        # ATS board (job-boards.greenhouse.io IS the company's careers site), then a generic
        # job board, then "Other". `linkedin` used to sit in this chain and was dropped
        # (2026-08-16): the run cannot know the posting came from LinkedIn — most did not —
        # so selecting it states a specific sourcing channel that is simply not the case.
        # Small as that is, it is the same kind of untruth as the university-board pick.
        for pat in (r"career site|careers? page|company (web)?site|our website|jobs page",
                    r"job ?board|job ?site|other job",
                    r"^other$"):
            for l in neutral:
                if re.search(pat, l, re.I):
                    return l
        return None
    for l in labels:                                  # exact
        if l.strip().lower() == want.strip().lower():
            return l
    for l in labels:                                  # startswith
        if l.strip().lower().startswith(want.strip().lower()):
            return l
    for l in labels:                                  # substring
        if want.strip().lower() in l.strip().lower():
            return l
    return None


def build(slug, jid, eu=False, out=None):
    data = fetch(slug, jid, eu)
    role = data.get("title", "").strip()
    host = "job-boards.eu.greenhouse.io" if (eu or str(jid).endswith("101")) else "job-boards.greenhouse.io"
    cfg = {
        "company": (data.get("company_name") or slug).strip(),
        "role": role,
        "url": f"https://{host}/embed/job_app?for={slug}&token={jid}",
        "cv": "base-resume.pdf",
        "eeo": True,
        "fill": {},
        "combo": {},
    }
    unanswered, human, oath = [], [], False

    for q in data.get("questions", []):
        label = (q.get("label") or "").strip()
        if not label or SKIP.match(label.rstrip("*").strip()):
            continue
        fields = q.get("fields") or [{}]
        ftype = fields[0].get("type", "")
        values = fields[0].get("values") or []
        required = bool(q.get("required"))

        if ANTI_AI.search(label):
            oath = True
            continue
        if NEEDS_HUMAN.search(label):
            # ⛔ A YEARS QUESTION IS NOT AUTOMATICALLY UNANSWERABLE (2026-08-16). This blanket
            # ban contradicts the applicant profile, which ships a "Years-of-experience quick
            # reference (for 'how many years of X?' screeners)" and says plainly: "Give these
            # when a form demands a number; they're defensible from the career history." What
            # the profile forbids is the opposite case — "Fabricate years-of-experience
            # numbers BEYOND the quick-reference table". The bank's specific years rows are
            # derived from that table; its `/years.*(of )?experience/ -> 5` catch-all is not,
            # and answering an arbitrary technology from it WOULD be fabrication.
            # So: answer from a SPECIFIC banked row, refuse when only the generic default
            # applies. Without this the bank's years rows could never be reached at all —
            # "How many years of software engineering experience do you have?" stayed a
            # blocker through three drains after the correct answer was banked.
            #
            # GENERALISED (2026-08-16): the same test is right for EVERY category this gate
            # bans, and it is self-enforcing. Security clearance and driving licence both have
            # specific, profile-backed rows ("No — enhanced DBS, no SC/DV, willing to be
            # vetted"; "No — provisional only"), and SKILL.md says outright that "clearance is
            # NOT a blocker (vetting is post-offer — apply, answer honestly)". Shift work,
            # on-call rota and vehicle ownership have NO bank row at all, so they continue to
            # need a human without needing to be named — which is the correct outcome, because
            # those are life constraints the applicant states, not facts the profile records.
            # The criterion is "does the bank hold a profile-backed answer", not "which
            # category is this".
            _years_ok = None
            if required:
                try:
                    sys.path.insert(0, os.path.join(ROOT, "sites", "_common", "scripts"))
                    import screener  # noqa: PLC0415
                    _hit = screener.lookup(label)
                    if _hit and "generic default" not in (_hit.get("source") or ""):
                        _years_ok = _hit["answer"]
                except Exception:  # noqa: BLE001
                    _years_ok = None
            if _years_ok is not None:
                cfg["fill"][label[:60]] = _years_ok
                continue
            if required:
                human.append(label[:90])
            continue

        answer = next((a for pat, a in TRUTHS if re.search(pat, label, re.I)), None)
        bank_answer = None
        if True:
            # SCREENER-BANK FALLBACK (2026-08-15). TRUTHS is this generator's own small
            # pattern list; screener-answers.csv is the skill's SHARED, learnable one, and
            # having two was why "Please select your right to work status" came back
            # UNANSWERED_REQUIRED on every Canonical/Graphcore posting even though the bank
            # had held the answer for weeks. Consult the bank second (TRUTHS still wins).
            # SAFE BY CONSTRUCTION HERE: the API hands us `values`, so a select answer is
            # validated against the REAL option list by pick_option below and simply stays
            # unanswered when nothing matches — the same closed-set rule as
            # atsform.fill_gaps_from_bank, which exists because the bank matches by substring
            # and a loose row ("bachelor") can otherwise answer a question it never meant.
            try:
                sys.path.insert(0, os.path.join(ROOT, "sites", "_common", "scripts"))
                import screener  # noqa: PLC0415
                hit = screener.lookup(label)
            except Exception:  # noqa: BLE001 — the bank is an optimisation, never a hard dep
                hit = None
            if hit:
                bank_answer = hit["answer"]
                if answer is None:
                    answer = bank_answer
        if answer is None:
            if required:
                unanswered.append(f"{label[:80]}  [{ftype}]")
            continue

        if "select" in ftype:
            chosen = pick_option(values, answer)
            if not chosen and _CONSENTISH.search(label) and _is_affirmative_answer(answer or bank_answer):
                # CONSENT SELECTS (2026-08-15). A tick-to-acknowledge question is rendered as a
                # select whose single option is the ENTIRE policy text ("By checking this box,
                # I confirm I have read, reviewed and understood the guidelines…"), so an
                # answer of "Yes" matches nothing and the required field stays empty — 10
                # postings in one drain died on exactly this. pick_option already knows how to
                # resolve these via the __CONSENT__ sentinel (acknowledge / I agree / accept /
                # the sole option); it simply was never reached once a truthful "Yes" had been
                # produced. Only fires when the question IS consent-shaped and the intended
                # answer is affirmative, so it can never turn a "No" into agreement.
                chosen = pick_option(values, "__CONSENT__")
            if not chosen and bank_answer:
                # ⛔ THE GATE MUST KNOW WHAT THE FILLER KNOWS (2026-08-16). atsform holds
                # _OPTION_SYNONYMS — exact synonyms of the SAME claim in different vocabularies
                # ("Native or bilingual" == "C2: Proficient", "Man" == "Male") — and
                # combobox_pick retries through it. pick_option did not, so this PRE-FLIGHT
                # gate declared a question unanswerable that the filler could in fact answer,
                # and _gh_config_from_api then refused to drive the posting at all. The bank
                # improvement never got a chance to help: the gate is strictly more
                # conservative than the thing it gates. Live on Parloa's English-proficiency
                # question, still listed as a blocker after the synonym retry shipped.
                try:
                    sys.path.insert(0, os.path.join(ROOT, "sites", "_common", "scripts"))
                    from atsform import _OPTION_SYNONYMS  # noqa: PLC0415
                    for alt in _OPTION_SYNONYMS.get(str(bank_answer).strip().lower(), []):
                        chosen = pick_option(values, alt)
                        if chosen:
                            break
                except Exception:  # noqa: BLE001 — synonyms are an optimisation
                    pass
            if not chosen and bank_answer and bank_answer != answer:
                # TRUTHS matched but its answer has the wrong SHAPE for this option list.
                # Live: "Please select your right to work status" hit the generic
                # `right to work -> Yes` rule, but the options are
                # ['British or Irish Citizen', 'EU Settled Status', …] — so "Yes" mapped to
                # nothing and every Canonical/Graphcore posting reported it
                # UNANSWERED_REQUIRED. The bank holds the option-shaped answer ("British"),
                # so try it before giving up. Still closed-set validated by pick_option.
                chosen = pick_option(values, bank_answer)
            if chosen:
                cfg["combo"][label[:60]] = chosen
            elif required:
                opts = [v.get("label") for v in values][:6]
                unanswered.append(f"{label[:70]}  [options: {opts}]")
        else:
            if answer == "__CONSENT__":
                answer = "Yes"
            cfg["fill"][label[:60]] = answer

    os.makedirs(CFG_DIR, exist_ok=True)
    slugrole = re.sub(r"[^a-z0-9]+", "-", role.lower()).strip("-")[:44] or "role"
    path = out or os.path.join(CFG_DIR, f"{slug}-{slugrole}.json")
    with open(path, "w") as f:
        json.dump(cfg, f, indent=2)

    return path, cfg, unanswered, human, oath


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug", nargs="?")
    ap.add_argument("jobid", nargs="?")
    ap.add_argument("--eu", action="store_true")
    ap.add_argument("--out")
    ap.add_argument("--batch", help="file of slug|jobid[|eu] lines")
    a = ap.parse_args()

    targets = []
    if a.batch:
        for line in open(a.batch):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            p = line.split("|")
            targets.append((p[0], p[1], len(p) > 2 and p[2] == "eu"))
    elif a.slug and a.jobid:
        targets.append((a.slug, a.jobid, a.eu))
    else:
        ap.error("give <slug> <jobid> or --batch")

    for slug, jid, eu in targets:
        try:
            path, cfg, unanswered, human, oath = build(slug, jid, eu, a.out)
        except Exception as e:  # noqa: BLE001
            print(f"FAIL {slug}/{jid}: {e}")
            continue
        status = "OK" if not (unanswered or human or oath) else "REVIEW"
        print(f"{status} {cfg['company']} | {cfg['role'][:44]} -> {os.path.basename(path)} "
              f"(fill={len(cfg['fill'])} combo={len(cfg['combo'])})")
        if oath:
            print("   ⛔ ANTI-AI OATH on this posting — the applicant must apply himself.")
        for h in human:
            print(f"   NEEDS_HUMAN: {h}")
        for u in unanswered:
            print(f"   UNANSWERED_REQUIRED: {u}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
