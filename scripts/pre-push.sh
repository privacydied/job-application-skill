#!/bin/bash
# pre-push.sh — refuse to push a repo whose tests are red or whose tracked files carry PII.
#
# WHY THIS EXISTS (2026-08-16). The pre-commit hook is a symlink to check-no-pii.sh, so the
# only thing standing between a broken change and `origin/main` was a PII grep. That is a
# genuine gate — PII leaking into a public repo is unrecoverable — but it says nothing about
# whether the code works, and its cheerful "✓ check-no-pii" reads exactly like a green light.
#
# It misled me: commit 0bf10a3 added a bare `import feed` to classify_route.py, which broke
# the codebase-wide import test (43 boards ship a module named feed.py). check-no-pii printed
# ✓, so I pushed. The suite was red on origin/main until the follow-up commit.
#
# The suite is ~5 seconds. There is no reason not to run it here.
#
#   ln -sf ../../scripts/pre-push.sh .git/hooks/pre-push
#
# Bypass deliberately with `git push --no-verify` when you genuinely mean to (e.g. pushing a
# WIP branch that is expected to be red) — that is an explicit choice, which is the point.
set -u
ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || ROOT=""
[ -n "$ROOT" ] || ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 0

fail=0

# 1) PII — the same check the pre-commit hook runs. Re-run it here because a push can carry
#    commits made with --no-verify, or made before the hook was wired.
if ! bash scripts/check-no-pii.sh; then
  echo "pre-push: BLOCKED — personal data in a tracked file." >&2
  fail=1
fi

# 2) Tests. Prefer pytest; fall back to unittest discovery so this works on a bare checkout.
if python3 -c "import pytest" 2>/dev/null; then
  out="$(python3 -m pytest tests/ -q 2>&1)"
else
  out="$(python3 -m unittest discover -s tests -q 2>&1)"
fi
if [ $? -ne 0 ]; then
  echo "$out" | tail -20 >&2
  echo "pre-push: BLOCKED — the test suite is red. Fix it, or push with --no-verify if you" >&2
  echo "          genuinely intend to publish a failing state." >&2
  fail=1
else
  echo "✓ pre-push: $(echo "$out" | grep -oE '[0-9]+ passed' | tail -1), no PII."
fi

exit $fail
