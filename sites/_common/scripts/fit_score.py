#!/usr/bin/env python3
"""
fit_score.py — rank queue rows by how well the JD fits the applicant, not just by how easy
the ATS is (feature-roadmap M.1).

WHY THIS EXISTS. apply_rank orders the queue by expected SUBMIT rate (easiest ATS first). But
the objective is INTERVIEWS, and a time-boxed run (they all are) should spend its budget on
the best-FIT roles, not merely the easiest-to-submit ones. This computes a 0..1 fit score for
each posting from the JD text vs the applicant profile + per-family base summaries, and the
pipeline folds it into the queue order so best-fit rises within reach of easiest-ATS.

BACKEND. Default is a dependency-free LEXICAL model (weighted token overlap / cosine over the
profile vocabulary) — it needs nothing installed and runs in microseconds. If
`sentence-transformers` happens to be importable, `--embed` uses a small CPU embedding model
instead (semantic, slower). Lexical is the shipped default precisely because this repo runs on
a NAS with no ML stack; the score is a RANKING signal, not a precise probability, so a good
lexical proxy is enough to float the right roles up.

CORPUS (all read at import, cached):
  * references/applicant-profile.md  — the answer-as-applicant source of truth (gitignored)
  * sites/_common/family-bases.json  — per-family summaries (gitignored)
  * references/target-roles.md       — the tiered role vocabulary
  Any absent (fresh clone) → fit() returns a neutral 0.5 (no effect on ordering), so the
  pipeline degrades gracefully rather than mis-ranking.

API:
  fit(jd_text, title="", family="") -> float in [0,1]
  fit_row(queue_row) -> float          # pulls text from the row's compact jd payload + title

CLI:
  fit_score.py "<jd text or title>" [--family design]
  fit_score.py --queue queue.jsonl     # print each row's fit, sorted
"""
import json
import math
import os
import re
import sys
from functools import lru_cache

_here = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_here, "..", "..", ".."))
PROFILE = os.path.join(_ROOT, "references", "applicant-profile.md")
FAMILY_BASES = os.path.join(_here, "family-bases.json")
TARGET_ROLES = os.path.join(_ROOT, "references", "target-roles.md")

_STOP = set("a an the and or of to in for with on at by from as is are be this that your you "
            "we our will role team work working job about who what why how within across "
            "have has using use strong ability able experience years year including etc via "
            "per plus into out over more most other others any all not no yes into".split())
_TOKEN = re.compile(r"[a-z][a-z+#.]{1,}")


def _tokens(text):
    return [t for t in _TOKEN.findall((text or "").lower())
            if t not in _STOP and len(t) > 2]


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except (OSError, ValueError):
        return ""


@lru_cache(maxsize=1)
def _profile_model():
    """Build the profile term-weight vector once. Returns (weights: {term: idf-ish weight},
    family_terms: {family: set(term)}, available: bool)."""
    prof = _read(PROFILE)
    roles = _read(TARGET_ROLES)
    fam_terms = {}
    try:
        fb = json.loads(_read(FAMILY_BASES) or "{}")
        if isinstance(fb, dict):
            for fam, v in fb.items():
                blob = v if isinstance(v, str) else json.dumps(v)
                fam_terms[fam] = set(_tokens(blob))
    except ValueError:
        pass
    corpus = prof + "\n" + roles
    available = bool(prof.strip()) or bool(fam_terms) or bool(roles.strip())
    # term frequency in the profile corpus -> a sublinear weight (a term the profile mentions
    # a lot is a strong fit signal; a hapax is weak). Not true idf (one doc), but a stable
    # emphasis map over the applicant's own vocabulary.
    tf = {}
    for t in _tokens(corpus):
        tf[t] = tf.get(t, 0) + 1
    weights = {t: 1.0 + math.log(c) for t, c in tf.items()}
    return weights, fam_terms, available


def fit(jd_text, title="", family=""):
    """0..1 fit of a JD to the applicant. Weighted overlap of the JD's tokens with the
    profile vocabulary, normalized by the JD's own token mass (so a long JD isn't penalized),
    with a small bonus for family-specific term hits. Neutral 0.5 if no profile corpus."""
    weights, fam_terms, available = _profile_model()
    if not available:
        return 0.5
    toks = _tokens((title + " ") * 3 + (jd_text or ""))  # weight the title heavily
    if not toks:
        return 0.5
    uniq = set(toks)
    matched = sum(weights.get(t, 0.0) for t in uniq)
    possible = sum(weights.get(t, 0.0) for t in uniq) + 1e-9
    # coverage: fraction of the JD's *distinct informative* tokens the profile knows about,
    # weighted. Anchored so a totally-unknown JD ~0, a heavily-overlapping one ~1.
    known = sum(1 for t in uniq if t in weights)
    coverage = known / (len(uniq) + 1e-9)
    weight_share = matched / (matched + 0.5 * len(uniq) + 1e-9)
    score = 0.5 * coverage + 0.5 * weight_share
    if family and family in fam_terms and fam_terms[family]:
        fam_hits = len(uniq & fam_terms[family]) / (len(fam_terms[family]) + 1e-9)
        score = min(1.0, score + 0.15 * fam_hits)
    return max(0.0, min(1.0, round(score, 4)))


def _jd_text_from_row(row):
    """Pull screenable text from a queue row's compact jd payload + title."""
    parts = [row.get("title") or ""]
    jd = row.get("jd") or {}
    if isinstance(jd, dict):
        reqs = jd.get("requirements") or jd.get("must_haves") or []
        if isinstance(reqs, list):
            parts.append(" ".join(str(x) for x in reqs))
        for k in ("summary", "jd_text", "text", "snippet"):
            if isinstance(jd.get(k), str):
                parts.append(jd[k])
    if row.get("snippet"):
        parts.append(str(row["snippet"]))
    return " ".join(parts)


def fit_row(row):
    return fit(_jd_text_from_row(row), title=row.get("title") or "",
               family=row.get("family") or "")


def _cli(argv):
    if "--queue" in argv:
        path = argv[argv.index("--queue") + 1]
        rows = []
        try:
            for line in open(path, encoding="utf-8"):
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
        except (OSError, ValueError) as e:
            print(f"FAIL: {e}", file=sys.stderr)
            return 2
        scored = sorted(((fit_row(r), r) for r in rows), key=lambda x: -x[0])
        for s, r in scored:
            print(f"{s:.3f}  {r.get('title','')[:40]:<40}  {r.get('family',''):<12}  "
                  f"rank={r.get('apply_rank')}  {r.get('company','')}")
        avail = _profile_model()[2]
        if not avail:
            print("\n(note: no profile corpus found — all scores neutral 0.5)", file=sys.stderr)
        return 0
    if len(argv) >= 2 and not argv[1].startswith("--"):
        fam = argv[argv.index("--family") + 1] if "--family" in argv else ""
        print(f"{fit(argv[1], title=argv[1], family=fam):.4f}")
        return 0
    print("Usage: fit_score.py \"<jd text/title>\" [--family f] | --queue queue.jsonl",
          file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(_cli(sys.argv))
