#!/bin/bash
# check-no-pii.sh — fail if YOUR personal details leak into any git-TRACKED file.
#
# It reads your identity tokens from your gitignored config (sites/_common/apply-defaults.json
# + references/applicant-profile.md line 1) and greps every tracked file for them. Because it
# derives the tokens from YOUR files, it stays correct for any user with no edits.
#
# Use it:
#   bash scripts/check-no-pii.sh            # manual check before committing/pushing
#   ln -sf ../../scripts/check-no-pii.sh .git/hooks/pre-commit   # or wire as a pre-commit hook
#
# Exit 0 = clean (or no config to check against); exit 1 = a personal token is tracked.
set -u
cd "$(dirname "$0")/.." || exit 0
CFG="sites/_common/apply-defaults.json"
PROFILE="references/applicant-profile.md"

TOKENS="$(python3 - "$CFG" "$PROFILE" <<'PY'
import json, os, re, sys
from urllib.parse import urlsplit
cfg, prof = sys.argv[1], sys.argv[2]
toks = set()

# Generic, non-identifying tokens to NEVER flag (common domains, URL parts, stock answers).
STOP = {"github.com", "linkedin.com", "x.com", "twitter.com", "example.com", "example.org",
        "www", "http", "https", "http:", "https:", "in", "the", "your-handle",
        "available", "immediately", "london", "united", "kingdom", "prefer", "none",
        "jane", "doe", "she", "her", "him", "his", "yes", "no"}

def add(t):
    t = (t or "").strip().strip("/:.")
    if len(t) >= 4 and t.lower() not in STOP:
        toks.add(t)

if os.path.exists(cfg):
    try:
        fill = json.load(open(cfg)).get("fill", {})
    except Exception:
        fill = {}
    for k, v in fill.items():
        if not isinstance(v, str):
            continue
        kl = k.lower()
        if "@" in v:                                    # email -> local part + domain
            local, _, dom = v.partition("@")
            add(local); add(dom)
        elif re.match(r"^https?://", v):                # any URL -> the HANDLE only (last path seg),
            path = urlsplit(v).path.rstrip("/")         # never the scheme/host (those are generic)
            if path:
                add(path.rsplit("/", 1)[-1])
        elif "name" in kl:                              # name fields -> each word
            for w in v.split():
                add(w)
        elif re.sub(r"\D", "", v) and len(re.sub(r"\D", "", v)) >= 7:  # phone -> digits
            add(re.sub(r"\D", "", v))
        # City / Notice period / other free-text: skipped (generic, not identifying)

# name from the profile heading ("# Applicant Profile — <Name>")
if os.path.exists(prof):
    first = open(prof, encoding="utf-8", errors="replace").readline()
    m = re.search(r"Applicant Profile\s*[—-]\s*(.+)", first)
    if m:
        for w in m.group(1).split():
            add(w)

print("\n".join(sorted(toks)))
PY
)"

if [ -z "${TOKENS//[[:space:]]/}" ]; then
  echo "check-no-pii: no config to derive tokens from (fresh clone) — nothing to check."
  exit 0
fi

found=0
while IFS= read -r tok; do
  [ -z "$tok" ] && continue
  hits="$(git ls-files -z 2>/dev/null | xargs -0 grep -ilF -- "$tok" 2>/dev/null)"
  if [ -n "$hits" ]; then
    echo "✗ personal token '$tok' appears in tracked file(s):"
    echo "$hits" | sed 's/^/    /'
    found=1
  fi
done <<< "$TOKENS"

if [ "$found" -eq 0 ]; then
  echo "✓ check-no-pii: no personal tokens from your config appear in any tracked file."
  exit 0
fi
echo ""
echo "Above tokens are your PII and are git-TRACKED. Move that content to a gitignored file"
echo "(or replace with a placeholder) before committing/pushing. See README '.gitignore'."
exit 1
