---
tags: [spec, verification, ssot, authelia]
created: "2026-05-25"
---

# Verification — SSOT-014-authelia-user

## Evidence

- [ ] AC1 (`is_admin: true` + no username on admin entry) → commit `<hash>` + grep snippet
- [ ] AC2 (`git grep "username: manu" common.yaml` == 0) → command output
- [ ] AC3 (`apps.auth.admin_username` is still the single string source) → grep snippet
- [ ] AC4 (staging users_database.yml byte-identical) → `git diff --quiet`; echo $?
- [ ] AC5 (prod users_database.yml byte-identical) → same
- [ ] AC6 (drift gate green both envs) → `make config-check-drift` exit codes
- [ ] AC7 (tests green) → `make test` summary

## Test status

- Test suite: `make test` → `<pending>`
- Manual smoke test: inspect generated `users_database.yml` for both envs — admin entry still has `manu:` as YAML key (because admin_username unchanged); shape is identical
- No regressions: yes / no (pending)

## Decisions made during implementation

- (filled during implementation)

## Promotion candidates

- [ ] Lesson for `10_projects/kubelab/90-lessons.md`? **possibly** — "two generators iterating the same config list need mirrored resolution logic; consider extracting a shared helper to enforce parity"
- [ ] ADR-worthy decision for `10_projects/kubelab/30-architecture/`? **no** — incremental SSOT pattern, no architecture shift
- [ ] New pattern candidate for `00_meta/patterns/`? **no**

## Archive checklist

- [ ] `proposal.md` frontmatter → `status: archived`
- [ ] Folder moved: `specs/SSOT-014-authelia-user/` → `specs/archive/SSOT-014-authelia-user/`
- [ ] Vault backlog SSOT-014b ticked with PR link
