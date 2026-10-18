---
tags: [spec, tasks]
created: "2026-05-13"
---

# Tasks - TOOL-001-secret-drift

> TDD order.

## Setup

- [ ] Branch created from main: `feat/TOOL-001-secret-drift`
- [ ] `proposal.md` decisions resolved: output format (plain default + `--format json`), shape comparison (type-level only).

## Implementation

- [ ] Write failing test: two identical SOPS fixtures -> diff empty + exit 0
- [ ] Write failing test: staging has extra key -> diff lists it + exit 1
- [ ] Write failing test: shape mismatch (string vs list) -> flagged + exit 1
- [ ] Write failing test: output never contains secret values (grep-negative assertion on fixture)
- [ ] Write failing test: decryption failure -> clear error + exit 2
- [ ] Write failing test: `--format json` emits valid parseable JSON
- [ ] Implement `toolkit/secrets/diff.py` (or equivalent) — SOPS decrypt + key/shape diff
- [ ] Wire up CLI: `toolkit secrets diff` subcommand
- [ ] Refactor: extract reusable SOPS-decrypt helper if not already isolated
- [ ] Manual smoke against real staging vs prod SOPS files

## Closing

- [ ] All tests green
- [ ] Type checks pass (mypy or equivalent)
- [ ] Lint pass
- [ ] No values leaked in any test output (manual review of fixtures + outputs)
- [ ] `verification.md` filled
- [ ] PR opened referencing `specs/TOOL-001-secret-drift/`
- [ ] TOOL-001 ticked in `kubelab/11-tasks.md` with PR link
