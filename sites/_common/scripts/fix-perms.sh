#!/bin/bash
# fix-perms.sh — make skill files usable regardless of who wrote them.
#
# WHY: tools that write files under this skill can leave them `root:root` (mode 700),
# and then `bash cfx.sh …` fails with `Permission denied` when run as your user, silently
# stranding a run. This restores YOUR ownership and `+x` on shell scripts. It is
# the SINGLE source of truth for that fix so it travels WITH the skill folder and works
# on ANY execution path — Claude Code calls it from a PostToolUse hook, the Hermes agent
# (which has no such hook) calls it directly at bootstrap / after writing skill files.
#
#   fix-perms.sh              # fix the WHOLE skill tree (use at bootstrap / end of run)
#   fix-perms.sh <path> ...   # fix only the given file(s) (use right after writing one)
#
# Idempotent and safe to run any time. Errors are swallowed (a chown you lack rights for
# just no-ops) so it never blocks the caller.

# Skill root = …/_common/scripts -> _common -> sites -> root
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
# Restore ownership to whoever runs this (derived, not hard-coded) so it works for any user.
OWNER="$(id -un):$(id -gn)"

fix_one() {
  local f="$1"
  [ -e "$f" ] || return 0
  chown "$OWNER" "$f" >/dev/null 2>&1 || true
  case "$f" in
    *.sh) chmod +x "$f" >/dev/null 2>&1 || true ;;
  esac
}

if [ "$#" -gt 0 ]; then
  for f in "$@"; do
    # Only touch paths inside the skill tree — never chown arbitrary files handed in.
    case "$(cd "$(dirname "$f")" 2>/dev/null && pwd)/$(basename "$f")" in
      "$ROOT"/*) fix_one "$f" ;;
    esac
  done
else
  chown -R "$OWNER" "$ROOT" >/dev/null 2>&1 || true
  find "$ROOT" -type f -name '*.sh' -exec chmod +x {} + >/dev/null 2>&1 || true
fi
