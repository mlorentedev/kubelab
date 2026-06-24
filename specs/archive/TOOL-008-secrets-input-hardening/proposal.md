---
id: "TOOL-008-secrets-input-hardening"
type: spec
status: archived # draft | implementing | verifying | archived
created: "2026-06-16"
issue: "mlorentedev/knowledge#104"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal, toolkit, secrets, sops, cli]
template_version: "1.0"
---

# TOOL-008-secrets-input-hardening

## Why

<!-- from issue mlorentedev/knowledge#104: TOOL-008: secrets CLI input hardening — set --stdin + idempotent init -->

Two footguns in the toolkit secrets subsystem block safe, automatable secret management, and both
were hit head-on while wiring NOTIFY-001 staging secrets. First, `toolkit secrets set` cannot store
a value beginning with `-` (every Telegram chat ID is `-100…`): the value is a positional argument
parsed as flags, and Typer's `--` escape is broken here — and secret values on argv leak to shell
history and `ps`. Second, `toolkit secrets init` is destructive: it regenerates *every*
machine-generable secret and overwrites existing ones — confirmed it would clobber the live
`n8n.encryption_key` and Authelia `storage_encryption_key`/`session_secret` in staging, orphaning
encrypted data. Both must be fixed for secret provisioning to be automatable, SSOT, and safe to run
against a populated environment.

## What

1. **`secrets set … --stdin`** — `toolkit secrets set KEY --env E --stdin` reads the value from
   stdin, e.g. `printf -- '-100…' | toolkit secrets set <key> --env staging --stdin`.
   Non-interactive and scriptable (precedent: `docker login --password-stdin`, `gh secret set`).
   The positional `VALUE` is retained for back-compat; passing both is a clear error. Result:
   leading-dash values work and secret values stay out of argv/history.
2. **Idempotent `secrets init`** — `init` skips secrets that already exist (non-empty) and generates
   only the missing ones. `--force` regenerates all machine-generable secrets (the old behavior, now
   an explicit opt-in). `--rotate KEY...` regenerates only the named key(s). Result:
   `make secrets-init ENV=staging` is safe on a live env and fills exactly what is missing (here,
   only `webhook_secret`).

## Out of scope

- TOOL-001 (`secrets diff`) and TOOL-002 (sync) — separate specs.
- Interactive TTY prompt / getpass for `set` — pipe-only for now.
- Fixing Typer's global `--` separator handling — sidestepped by stdin.
- The `dotf spec init` bitácora-repo assumption — tracked separately as dotfiles HARNESS-023.

## Risks / open questions

- **[RESOLVED]** Does stdin break automation? No — a piped stdin is non-interactive; only a blocking
  getpass would. We implement pipe-reading, not prompting.
- **[RESOLVED]** Back-compat: `--stdin` is additive; existing positional callers are untouched.
- **[OPEN — implementation]** The `init` existence check must read the *decrypted* current value: a
  key may be present but empty / a `REPLACE_WITH_SOPS_VALUE` placeholder. Treat empty/placeholder as
  "missing" so init fills it.
- **[OPEN — implementation]** `--rotate KEY` must validate the key is in `SECRET_CATALOG` and is a
  machine-generable kind; reject external/password kinds with a clear message.

## Acceptance criteria

- [ ] `printf -- '-1004406031115' | toolkit secrets set <key> --env staging --stdin` stores the
      value; `secrets show` round-trips it.
- [ ] `secrets set <key> <value> --stdin` (both sources) exits non-zero with a clear
      "mutually exclusive" error.
- [ ] `secrets init --env staging` on a populated env generates ONLY missing secrets; a pre-existing
      `n8n.encryption_key` is byte-identical afterwards.
- [ ] `secrets init --force --env <e>` regenerates all machine-generable secrets.
- [ ] `secrets init --rotate <key> --env <e>` regenerates only that key; others untouched.
- [ ] Sibling unit tests cover all of the above and pass via `make test`.

## References

- Surfaced by: NOTIFY-001 (`specs/NOTIFY-001/`, mlorentedev/knowledge#90)
- Code: `toolkit/cli/secrets.py` (`set`, `init`), `toolkit/features/secrets_manager.py`
  (`set_secret`, `init_machine_secrets`)
- Related: TOOL-001 (`secrets diff`), TOOL-002 (sync)
- Tooling bug found en route: dotfiles HARNESS-023 (dotf spec init bitácora-repo assumption)
