---
tags: [spec, verification, templates]
created: "2026-10-13"
---

# Verification - TF-007-remote-state

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof (commit hash, test name, or observed behavior).

PR 1a covers AC3 and AC4; the rest land with PR 1b.

- [x] AC3 -> `tests/test_terraform_single_entry.py` (Makefile recipes, toolkit AST scan, one `$(_TF)` line per target). Mutation: a raw `terraform plan` in `tf-dns-plan` goes red.
- [x] AC4 -> `tests/test_terraform_runner.py`, `tests/test_terraform_plan_guard.py`, `tests/test_vps_firewall_tfvars.py`. Mutations: legacy renders kept, inherited `TF_VAR_*` kept, guard ignored, tfvars 0644, `--allow-destroy` hardwired on dns: all red.
- [x] AC4 live -> msi, 2026-10-13: `make tf-dns-plan` and `make tf-r2-plan` read `No changes` with exit 0 on master `1b900c22` and on this branch `1fc2ddba`.
- [ ] AC1, AC2, AC5-AC10 -> PR 1b.

## Test status

- Test suite: `<command> -> <output / coverage %>`
- Manual smoke test: what was exercised, what was observed
- No regressions in existing test suite: yes / no (if no, document)

## Decisions made during implementation

- PR 1 was split into 1a (runner, local backend kept) and 1b (R2 backend), so the refactor is proven on the state it already has before the state moves.
- `aws1-replace` moved from `-auto-approve` to the guarded apply with an explicit `--allow aws_instance.argo_hub`.
- `compute` is not registered in the runner: it is DR-only and its deployer key is TF-018.
- A `terraform fmt` pre-commit hook was added because `compute/main.tf` had drifted unnoticed; the CI gate is TF-016.

## Promotion candidates

Answer each line `yes: <path>`, naming the file you promoted, or `no: <reason>`. `dotf spec archive` refuses a line left unanswered, a `no` without a reason, and a `yes` whose file does not exist; a `00_meta/` path is looked up in the vault.

- [ ] Lesson for the repo's `docs/lessons/`? <yes: path / no: reason>
- [ ] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? <yes: path / no: reason>
- [ ] New pattern candidate for `00_meta/patterns/`? Only if this recurs in >1 project. <yes: path / no: reason>

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/TF-007-remote-state/` -> `specs/archive/TF-007-remote-state/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
