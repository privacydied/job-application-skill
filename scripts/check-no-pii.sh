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
# Resolve the repo root robustly: `git rev-parse` works whether this runs as a pre-commit
# hook (git sets cwd to the worktree root) or is invoked manually from anywhere in the tree.
# Fall back to the script's own location for a non-git checkout.
ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || ROOT=""
[ -n "$ROOT" ] || ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 0
CFG="sites/_common/apply-defaults.json"
PROFILE="references/applicant-profile.md"

TOKENS="$(python3 - "$CFG" "$PROFILE" <<'PY'
import json, os, re, sys
from urllib.parse import urlsplit
cfg, prof = sys.argv[1], sys.argv[2]
toks = set()

# Generic, non-identifying tokens to NEVER flag: common domains, URL parts, stock answers,
# and the shipped PLACEHOLDER values (from the *.example configs) — those legitimately appear
# in the committed docs, so an un-personalised config must not trip the guard.
STOP = {"github.com", "linkedin.com", "x.com", "twitter.com", "example.com", "example.org",
        "www", "http", "https", "http:", "https:", "in", "the", "your-handle",
        "available", "immediately", "london", "united", "kingdom", "prefer", "none",
        "jane", "doe", "she", "her", "him", "his", "yes", "no",
        # placeholder phone (Ofcom fictional range) + example address/postcode from *.example
        "447700900000", "07700900000", "7700900000", "900000", "7700 900000",
        "example", "street", "your-vpn-username",
        # your PUBLIC GitHub handle / repo owner — appears legitimately in LICENSE + the repo
        # URL, so it's allowed here (the guard still catches your real name/email/phone/address)
        "privacydied"}

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
    body = open(prof, encoding="utf-8", errors="replace").read()
    m = re.search(r"Applicant Profile\s*[—-]\s*(.+)", body.splitlines()[0] if body else "")
    if m:
        for w in m.group(1).split():
            add(w)
    # STRUCTURED identifiers anywhere in the profile — distinctive patterns that are safe to
    # grep literally (unlike demographic words such as "Man"/"Mixed"/"Jewish", which are common
    # English and would false-positive everywhere, so those can't be auto-checked — keep them
    # OUT of tracked files via the [your …] placeholder convention instead).
    for m in re.findall(r"\b[A-Z]{2}\d{6}[A-Z]\b", body):                 # National Insurance No.
        add(m)
    for m in re.findall(r"\b[A-Z]{1,2}\d[A-Z\d]? ?\d[A-Z]{2}\b", body):   # UK postcode
        add(m)
    for m in re.findall(r"\b\d{2}/\d{2}/(?:19|20)\d{2}\b", body):         # DOB dd/mm/yyyy
        add(m)

# CREDENTIAL SECRETS from ats-credentials.csv (passwords / API keys / memorable words) must
# NEVER appear in a tracked file. Checked here, but each is emitted with a `SECRET::` marker so
# the bash side can print a REDACTED label — a guard must never re-leak the secret it checks.
secret_lines = []
try:
    import csv as _csv
    with open("ats-credentials.csv", newline="", encoding="utf-8") as f:
        for r in _csv.DictReader(f):
            for col, val in (r or {}).items():
                cl = (col or "").lower()
                # A row with MORE commas than the header (e.g. an un-quoted comma in a value) makes
                # DictReader return a LIST under the restkey — `.strip()` on that raised an
                # AttributeError that ESCAPED the narrow except below and silently disabled the WHOLE
                # PII guard. Normalise to strings so a malformed creds row can never do that again.
                for v in (val if isinstance(val, list) else [val]):
                    if isinstance(v, str) and len(v.strip()) >= 5 and any(
                            k in cl for k in ("password", "secret", "token", "key",
                                              "pass", "pw", "memorable", "app_key", "apikey")):
                        secret_lines.append("SECRET::" + v.strip())
except Exception:   # a broken creds file must NEVER silently disable the name/email/PII checks
    pass

print("\n".join(sorted(toks) + secret_lines))
PY
)"

if [ -z "${TOKENS//[[:space:]]/}" ]; then
  echo "check-no-pii: no config to derive tokens from (fresh clone) — nothing to check."
  exit 0
fi

found=0
secret_found=0
while IFS= read -r tok; do
  [ -z "$tok" ] && continue
  is_secret=0
  case "$tok" in
    "SECRET::"*) is_secret=1; tok="${tok#SECRET::}";;   # a credential value — never echo it
  esac
  hits="$(git ls-files -z 2>/dev/null | xargs -0 grep -ilF -- "$tok" 2>/dev/null)"
  if [ -n "$hits" ]; then
    if [ "$is_secret" -eq 1 ]; then
      echo "🚨 a CREDENTIAL/secret value from ats-credentials.csv appears in tracked file(s):"
      secret_found=1
    else
      echo "✗ personal token '$tok' appears in tracked file(s):"
    fi
    echo "$hits" | sed 's/^/    /'
    found=1
  fi
done <<< "$TOKENS"

if [ "$found" -eq 0 ]; then
  echo "✓ check-no-pii: no personal tokens or credential secrets appear in any tracked file."
  exit 0
fi
echo ""
if [ "$secret_found" -eq 1 ]; then
  echo "🚨 A CREDENTIAL SECRET IS TRACKED. Scrub it (scripts/scrub_pii.py) AND rotate the"
  echo "credential — it is in git history/remote, which a working-tree scrub does not fix."
fi
echo "Above values are PII/secrets and are git-TRACKED. Move to a gitignored file or"
echo "placeholder before committing/pushing. See README '.gitignore'."
exit 1
