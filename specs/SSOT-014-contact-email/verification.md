---
tags: [spec, verification, ssot, contact, email]
created: "2026-05-25"
---

# Verification — SSOT-014-contact-email

## Evidence

- [ ] AC1 (SSOT added + 3 derived fields removed) → commit `<hash>` + diff
- [ ] AC2 (`grep "mlorentedev@gmail.com" common.yaml | wc -l` == 1) → command output
- [ ] AC3 (staging users_database.yml byte-identical) → `git diff --quiet`
- [ ] AC4 (prod users_database.yml byte-identical) → same
- [ ] AC5 (drift gate green both envs) → `make config-check-drift` exit codes
- [ ] AC6 (tests green + new injection test) → `make test` summary
- [ ] AC7 (Ansible consumers unaffected) → playbook syntax check or regen test

## Test status

- Test suite: `make test` → `<pending>`
- Manual smoke test: inspect generated Authelia config for both envs — admin email still resolves to `mlorentedev@gmail.com`
- No regressions: yes / no

## Decisions made during implementation

- (filled during implementation)

## Promotion candidates

- [ ] Lesson for `90-lessons.md`? **probably** — "loader-injection pattern for derived SSOT fields keeps consumer code unchanged but requires inline documentation to avoid 'magic value' debugging"
- [ ] ADR-worthy? **no** — small refactor within established SSOT discipline
- [ ] Pattern candidate? **no** — single-project

## Archive checklist

- [ ] `proposal.md` frontmatter → `status: archived`
- [ ] Folder moved to `specs/archive/`
- [ ] Vault SSOT-014c + SSOT-010 ticked with PR link
