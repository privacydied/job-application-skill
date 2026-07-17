#!/usr/bin/env python3
"""
scrub_pii.py — auto-replace the applicant's real PII with the placeholder convention in
git-TRACKED files, so a leak never persists (companion to check-no-pii.sh).

WHY THIS EXISTS. `check-no-pii.sh` DETECTS PII in tracked files and blocks a commit, but the
autonomous loop (and the concurrent Hermes loop) keeps WRITING the applicant's real name/email
into tracked notes as it documents runs — so the leak accumulates and every commit has to be
hand-scrubbed. This closes the loop by ENFORCING the placeholder convention automatically:
loop-preflight.py calls it at the top of every firing, so any leaked PII is scrubbed to
placeholders before more work happens — the "harness executes this, not the model" pattern
that prose PII rules can't achieve.

TYPED, not token-based. check-no-pii derives untyped tokens (good for detection); scrubbing
needs to know a token's TYPE to pick the right placeholder (a name → "Jane Doe", an email →
"you@example.com", a domain → "example.com"). So this reads the SAME gitignored sources
(sites/_common/apply-defaults.json `fill.*` + references/applicant-profile.md) and maps each
typed value to its canonical placeholder. **This script hardcodes only PLACEHOLDERS — never
the real values** (those are read at runtime), so it is itself PII-free and tracked-safe.

SAFE BY CONSTRUCTION:
  * Only touches `git ls-files` (TRACKED) text files. Gitignored files (the profile,
    apply-defaults, tracker, apply-100-hard-loop.md, GOAL.md, credentials) legitimately hold
    real PII and are NEVER touched.
  * Skips binary/image files and anything > 2 MB.
  * Replacements are specific literal values (the applicant's actual name/email/domain/NINO/
    postcode/DOB) → placeholders; low false-positive risk.
  * Best-effort: a read/write error on one file is skipped, never fatal.

Placeholders (the repo convention — SKILL.md applicant facts + check-no-pii's STOP list):
  name→"Jane Doe" · email→"you@example.com" · phone→"+44 7700 900000" · site→"example.com" ·
  NINO→"[NINO]" · postcode→"[postcode]" · DOB→"[DOB]".

CLI:
  scrub_pii.py            # scrub tracked files, print what changed
  scrub_pii.py --dry-run  # report what WOULD change, touch nothing
  scrub_pii.py --quiet    # scrub, print only a one-line summary (for the preflight)
"""
import json
import os
import re
import subprocess
import sys
from urllib.parse import urlsplit

_here = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_here)
CFG = os.path.join(_ROOT, "sites", "_common", "apply-defaults.json")
PROFILE = os.path.join(_ROOT, "references", "applicant-profile.md")

# The applicant's PUBLIC GitHub handle appears legitimately in LICENSE/repo URL — never scrub.
_ALLOW = {"privacydied", "example.com", "example.org", "jane", "doe"}
_SKIP_EXT = {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".ico", ".zip", ".gz", ".bundle",
             ".pyc", ".db", ".woff", ".woff2", ".ttf", ".mp4", ".webp"}


def _case_variants(real, placeholder):
    """Replacements for a word in its Title/lower/UPPER forms → matching-cased placeholder."""
    out = []
    for r, p in ((real, placeholder), (real.lower(), placeholder.lower()),
                 (real.upper(), placeholder.upper())):
        if r and r.lower() not in _ALLOW:
            out.append((re.compile(r"\b" + re.escape(r) + r"\b"), p))
    return out


def build_replacements():
    """Ordered (compiled-regex, placeholder) list, derived from the gitignored config at
    runtime. Longest/most-specific first so an email is replaced before its domain, etc.
    Returns [] if no config (fresh clone) — nothing to scrub."""
    reps = []           # order matters
    fill = {}
    if os.path.exists(CFG):
        try:
            fill = json.load(open(CFG, encoding="utf-8")).get("fill", {})
        except (OSError, ValueError):
            fill = {}

    def get(*keys):
        for k in keys:
            v = fill.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return ""

    email = get("Email")
    full = get("Full name")
    first = get("First name")
    last = get("Last name")
    pref = get("Preferred name")
    phone = get("Phone")
    linkedin = get("LinkedIn")
    portfolio = get("Portfolio", "Website")

    # 1) full email FIRST (before domain/name pieces)
    if email and "@" in email:
        reps.append((re.compile(re.escape(email), re.I), "you@example.com"))
    # 2) LinkedIn handle (the last path segment) → janedoe, before name-word scrub
    if linkedin:
        seg = urlsplit(linkedin).path.rstrip("/").rsplit("/", 1)[-1]
        if seg and seg.lower() not in _ALLOW:
            reps.append((re.compile(re.escape(seg), re.I), "janedoe"))
    # 3) full name → "Jane Doe" (before first/last so a two-word name collapses cleanly)
    if full:
        reps.append((re.compile(r"\b" + re.escape(full) + r"\b", re.I), "Jane Doe"))
    # 4) portfolio/site domain → example.com (after email)
    if portfolio:
        host = urlsplit(portfolio if "//" in portfolio else "//" + portfolio).netloc or portfolio
        host = host.strip("/")
        if host and host.lower() not in _ALLOW and "." in host:
            reps.append((re.compile(re.escape(host), re.I), "example.com"))
    # 5) structured identifiers from the profile → bracket placeholders (specific real values)
    if os.path.exists(PROFILE):
        body = open(PROFILE, encoding="utf-8", errors="replace").read()
        for pat, ph in ((r"\b[A-Z]{2}\d{6}[A-Z]\b", "[NINO]"),
                        (r"\b[A-Z]{1,2}\d[A-Z\d]? ?\d[A-Z]{2}\b", "[postcode]"),
                        (r"\b\d{2}/\d{2}/(?:19|20)\d{2}\b", "[DOB]")):
            for val in set(re.findall(pat, body)):
                reps.append((re.compile(re.escape(val)), ph))
    # 6) name words (Title/lower/UPPER) → Jane / Doe
    for real, ph in ((first, "Jane"), (pref, "Jane"), (last, "Doe")):
        if real:
            reps.extend(_case_variants(real, ph))
    # 7) phone digits → the Ofcom fictional placeholder
    if phone:
        digits = re.sub(r"\D", "", phone)
        if len(digits) >= 7:
            reps.append((re.compile(re.escape(phone)), "+44 7700 900000"))
            reps.append((re.compile(re.escape(digits)), "447700900000"))
    return reps


def tracked_text_files():
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=_ROOT, capture_output=True,
                             text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    files = []
    for rel in out.split("\0"):
        rel = rel.strip()
        if not rel:
            continue
        if os.path.splitext(rel)[1].lower() in _SKIP_EXT:
            continue
        p = os.path.join(_ROOT, rel)
        try:
            if os.path.getsize(p) > 2_000_000:
                continue
        except OSError:
            continue
        files.append(rel)
    return files


def scrub(dry_run=False):
    """Apply the replacements to every tracked text file. Returns a dict {relpath: n_subs}."""
    reps = build_replacements()
    if not reps:
        return {}
    changed = {}
    for rel in tracked_text_files():
        p = os.path.join(_ROOT, rel)
        try:
            with open(p, encoding="utf-8") as f:
                text = f.read()
        except (OSError, UnicodeDecodeError):
            continue
        new = text
        n = 0
        for rx, ph in reps:
            new, k = rx.subn(ph, new)
            n += k
        if n and new != text:
            changed[rel] = n
            if not dry_run:
                try:
                    with open(p, "w", encoding="utf-8") as f:
                        f.write(new)
                except OSError:
                    changed.pop(rel, None)
    return changed


def main():
    argv = sys.argv[1:]
    dry = "--dry-run" in argv
    quiet = "--quiet" in argv
    changed = scrub(dry_run=dry)
    total = sum(changed.values())
    if not changed:
        if not quiet:
            print("scrub_pii: no applicant PII found in tracked files ✓"
                  if build_replacements() else "scrub_pii: no config to derive PII from.")
        return 0
    verb = "would scrub" if dry else "scrubbed"
    if quiet:
        print(f"scrub_pii: {verb} {total} PII occurrence(s) in {len(changed)} tracked file(s): "
              f"{', '.join(sorted(changed))}")
    else:
        print(f"scrub_pii: {verb} {total} PII occurrence(s) -> placeholders "
              f"in {len(changed)} tracked file(s):")
        for rel, k in sorted(changed.items()):
            print(f"    {rel}  ({k})")
        if dry:
            print("(dry-run — nothing written. Run without --dry-run to apply.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
