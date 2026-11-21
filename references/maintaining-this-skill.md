# Maintaining this skill — read BEFORE editing mirrored policy

Guidance for an agent **editing** this skill (not one running the apply loop —
that's why it lives here, out of `SKILL.md`'s per-turn context). `SKILL.md` keeps
a one-line pointer to this file at the CAPTCHA policy.

## Doc-consistency rule

The CAPTCHA policy (solve in place; 3 failures -> `Blocked`) is restated in `SKILL.md`, `GOAL.md`,
`goal-condition.txt`, `loop-prompt.md`, the prompt files, `references/captcha-policy.md` (canonical)
and some board NOTES. After any policy edit, grep for contradictions:

```bash
grep -rInE "full[ -]halt|non-sanctioned|halt procedure|captcha.*hard stop|hard stop.*captcha" --include=*.md --include=*.txt --include=*.py .
```

## Tooling pitfall (2026-07-13)

Large multi-line `patch` edits that contain literal `\n` in the new_string get
written with the backslash-n as TWO LITERAL CHARACTERS, not a newline — the edit
then half-applies (the old body dangles, the function signature is orphaned,
Pyright reports "undefined"). This happened twice this session (`recaptcha.py`
rewrite, `CAPABILITY-GAPS.md` block). Fix = full `write_file` of the file (can't
half-apply) then re-read to confirm. Always re-grep for `\n` after a patch that
spanned newlines.

## Verify, ownership, and deploy (moved out of SKILL.md's per-turn context)

These are editing/maintenance mechanics — a running (non-editing) apply-loop
instance never needs the full detail, so SKILL.md keeps only a one-line pointer
here (continuous-learning §7). The rules:

- **Verify before calling a fix done**: `python3 -m py_compile` / `bash -n` at
  minimum, a live call when practical. Un-run code isn't a verified fix. After a
  `patch`/`write_file` that touched multi-line blocks, re-read the region or grep
  for a stray literal `\n` (see the Tooling pitfall above). For a whole-function /
  whole-section rewrite, prefer a full `write_file` over `patch` mode=replace — the
  full rewrite can't half-apply and is easier to verify by re-reading.
- **Ownership**: `sites/_common/scripts/fix-perms.sh` (`chown <your-user>:<group>` +
  `chmod +x`) — Claude Code runs this automatically via a PostToolUse hook; Hermes
  has no hook and must run it at bootstrap and after writing any skill file.
- **Deploying `camofox-browser/server.js` — restart, not rebuild.** It's
  bind-mounted read-only. Use `docker compose restart camofox-browser`, **NOT
  `up -d`** — if the container is already running, `up -d` is a no-op (it only
  recreates on a tracked config change like image/env, not a bind-mounted file's
  contents changing) and silently leaves the old process running; `restart`
  actually cycles it. **This kills the live session (open tabs) — only deploy when
  idle** (`/health` → `activeTabs:0`); wait for `browserConnected:true` after.
  Changes to `lib/`/`plugins/`/`package.json` need a real rebuild — only
  `server.js` is mounted. Both agents can run this themselves, no password needed:
 `/etc/sudoers.d/camofox-restart` grants `<your-user>` NOPASSWD for exactly `docker
 compose -f compose.yaml restart camofox-browser` (also
 `up -d` for a not-yet-running container). This is also the fix for a real,
 confirmed fault where every mouse endpoint (click/hover/scroll) 500s across every
 tab while `/health` looks fine — see `CAPABILITY-GAPS.md`.
 - **⚠️ camofox restart reality-check (2026-07-15):** the NOPASSWD restart grant is
 **lapsed/fragile** on this NAS. Observed failure: `docker compose restart
 camofox-browser` errors with `Failed to load camofox-browser.env:
 permission denied`, AND `sudo -n true` returns `a password is required`. The Docker
 socket itself is also permission-denied for user `<your-user>`
 (`connect: permission denied` on `/var/run/docker.sock`). **Net: the agent CANNOT
 restart camofox unaided right now** — if a wedge won't clear via the tab-recovery
 sequence (POST /tabs → list-tabs), surface it to the user as a HARD STOP with the
 exact recipe (`docker compose restart camofox-browser` from a terminal with
 permissions, or restart the NAS container) rather than looping on the wedge. The
 user can also re-grant NOPASSWD via `/etc/sudoers.d/camofox-restart`.
 - **Tab-wedge recovery sequence (from `references/rotation-recovery-2026-07-15.md`):**
 when a sourced tab dies (`activeTabs` drops to 0, `GET /tabs` hangs or `POST /tabs`
 returns ids that 404 on verify), poll `POST /tabs` a few times (with a real `https://`
 URL — `about:blank`/`data:` 500s), then `cfx.py list-tabs` to find the one that stuck,
 and re-point `.jobenv.run` + `.runtab` `CFX_TAB` to it. Don't assume the old tab id
 survives.
