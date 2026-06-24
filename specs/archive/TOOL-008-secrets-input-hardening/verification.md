---
tags: [spec, verification]
created: "2026-06-16"
---

# Verification - TOOL-008-secrets-input-hardening

## Evidence

All criteria proven by `tests/test_secrets_input_hardening.py` (9 tests, all green).

- [x] `set --stdin` stores a leading-dash value (`-100…`) → `TestSecretsSetStdin::test_stdin_value_with_leading_dash`
- [x] `set` with both positional VALUE and `--stdin` errors, no write → `test_both_value_and_stdin_is_error`
- [x] `set --stdin` with empty stdin errors → `test_empty_stdin_is_error`
- [x] positional VALUE back-compat unchanged → `test_positional_value_still_works`
- [x] `init` skips existing, generates only missing → `TestInitIdempotent::test_skips_existing_generates_missing`
- [x] `init --force` regenerates all machine secrets → `test_force_regenerates_all`
- [x] `init --rotate KEY` regenerates only that key → `test_rotate_targets_only_named_key`
- [x] `init --rotate` rejects unknown / non-machine keys → `test_rotate_unknown_key_errors`, `test_rotate_non_machine_key_errors`

## Test status

- New tests: `poetry run pytest tests/test_secrets_input_hardening.py` → **9 passed in 0.53s**
- Full suite (no regressions): `make test` → **180 passed, 108 deselected in ~12s**
- Lint/format: `ruff check` + `ruff format --check` on the three changed files → clean
- Manual smoke (real SOPS): DEFERRED to the NOTIFY-001 follow-on — the `chat_log` /
  `webhook_secret` catalog entries live on `feat/notification-routing-fabric`, not on master.
  After this PR merges and notify rebases, the live smoke is:
  `printf -- '-1004406031115' | toolkit secrets set apps.services.automation.apprise.telegram.chat_log --env staging --stdin`
  then `toolkit secrets init --env staging` (idempotent → generates only `webhook_secret`),
  verified via `toolkit secrets audit --env staging`.

## Decisions made during implementation

- Idempotency reuses `audit(env).present` (already merges common+env and treats empty as missing)
  instead of a new resolver — DRY, and audit was the single source of the "is it set?" check.
- `--force` and `--rotate KEY` are both provided (per maintainer choice): `--force` = the old
  regenerate-all behavior, now an explicit opt-in; `--rotate` = targeted, with catalog-membership +
  machine-generable-kind validation so it can never touch a password/external secret.
- `set` value input fixed via `--stdin` (pipe), not by fighting Typer's broken `--` separator. This
  also removes secret values from argv/shell history. Positional VALUE kept additive for back-compat.
- `--stdin` strips a trailing `\r\n` only (`rstrip("\r\n")`); secret values never legitimately end
  in a newline, so this matches `docker login --password-stdin` behavior.

## Promotion candidates

- [x] Lesson for `docs/lessons.md`? YES — "`secrets init` was destructive (regenerated live
      encryption keys); secret values must enter via stdin, never argv". Promote at archive time.
- [ ] ADR-worthy decision? No — localized CLI hardening, no architectural change.
- [x] New pattern candidate for `00_meta/patterns/`? Maybe — "secret values via stdin, never argv"
      recurs across CLIs (docker/gh/vault precedent). Flag for the maintainer; only promote if it
      shows up in a second project.

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/TOOL-008-secrets-input-hardening/` -> `specs/archive/TOOL-008-secrets-input-hardening/`
- [ ] Bitácora issue #104 ticked with PR link
- [ ] Promotions above executed (lesson to `docs/lessons.md`)
