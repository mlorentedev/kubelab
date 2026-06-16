---
tags: [spec, tasks]
created: "2026-06-16"
---

# Tasks - TOOL-008-secrets-input-hardening

> TDD order. One task = one focused commit. The staging secret-set happens only AFTER the fixes are
> green (and is a NOTIFY-001 follow-on, not part of this PR's diff).

## Setup

- [x] Branch created from master: `fix/toolkit-secrets-input-hardening`
- [x] `proposal.md` complete; acceptance criteria testable
- [x] Open questions resolved (stdin pipe ≠ prompt; `--stdin` additive; `init` reads decrypted to
      detect empty/placeholder; `--rotate` validates catalog membership + machine-generable kind)

## Implementation — `secrets set --stdin`

- [ ] Failing test: `set KEY --env staging --stdin` with piped value stores it (incl. leading-dash `-100…`)
- [ ] Failing test: `set KEY VALUE --stdin` (both sources) → exit ≠ 0, clear "mutually exclusive" message
- [ ] Failing test: `set KEY --stdin` with empty stdin → exit ≠ 0, clear message
- [ ] Implement `--stdin` in `toolkit/cli/secrets.py:set_secret` (read `sys.stdin`, strip one trailing
      newline, guard mutual-exclusion); make positional `value` optional
- [ ] Refactor: extract a small `_resolve_value(value, use_stdin)` helper if it clarifies

## Implementation — idempotent `secrets init`

- [ ] Failing test: `init` on a populated env generates only MISSING keys; existing
      (e.g. `n8n.encryption_key`) is byte-identical afterwards
- [ ] Failing test: empty / `REPLACE_WITH_SOPS_VALUE` placeholder counts as missing → gets generated
- [ ] Failing test: `--force` regenerates all machine-generable keys
- [ ] Failing test: `--rotate KEY` regenerates only KEY; unknown/non-machine KEY → clear error
- [ ] Implement skip-existing in `secrets_manager.init_machine_secrets` (read decrypted current values;
      treat empty/placeholder as missing); add `force: bool` and `rotate: list[str]` params
- [ ] Wire `--force` / `--rotate` flags in `toolkit/cli/secrets.py:init`; update docstring + dry-run output
- [ ] Refactor: dedupe the existence/placeholder check with any existing resolver helper

## Closing

- [ ] Every acceptance criterion covered by ≥1 test; `make test` green (relevant subset)
- [ ] `features.json` emitted with a verification command per criterion
- [ ] Lint/format pass (pre-commit)
- [ ] No unrelated changes in the diff (no scope creep)
- [ ] `verification.md` filled (test output + `secrets audit` evidence)
- [ ] PR opened referencing this spec folder; merge BEFORE NOTIFY-001 rebases onto it
- [ ] Follow-on (NOTIFY-001, separate change): set `chat_log` via `set --stdin` + generate
      `webhook_secret` via idempotent `init`
