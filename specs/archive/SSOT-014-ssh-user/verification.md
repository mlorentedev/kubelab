---
tags: [spec, verification, ssot, ansible]
created: "2026-05-25"
---

# Verification — SSOT-014-ssh-user

> Filled DURING implementation. Evidence below maps each AC to a concrete proof (commit hash, command output, test name).

## Evidence

- [ ] AC1 (new SSOT block + per-node lines removed) → commit `<hash>` + `git diff` summary
- [ ] AC2 (single `"manu"` match in common.yaml) → `git grep -c '"manu"' infra/config/values/common.yaml` output
- [ ] AC3 (staging hosts.yml byte-identical) → `git diff --quiet infra/ansible/generated/staging/hosts.yml; echo $?` → 0
- [ ] AC4 (prod + hub hosts.yml byte-identical) → same command for each env
- [ ] AC5 (drift gate green both envs) → `make config-check-drift ENV={staging,prod}` exit codes
- [ ] AC6 (existing tests pass) → `make test` summary

## Test status

- Test suite: `make test` → `<pending — fill on completion>`
- Manual smoke test: regenerate inventories, run `ansible -i infra/ansible/generated/staging/hosts.yml all -m ping` if possible (validates `ansible_user` field is still correct end-to-end)
- No regressions: yes / no (pending)

## Decisions made during implementation

- (filled during implementation)

## Promotion candidates

- [ ] Lesson for `10_projects/kubelab/90-lessons.md`? **probably yes** — short lesson on "consolidating duplicated SSOT values via category-inference is cheaper than per-entity overrides; YAML position can be a category signal without needing a `category:` field"
- [ ] ADR-worthy decision for `10_projects/kubelab/30-architecture/`? **no** — small refactor, no architectural shift; reuses ADR-036 (shared infra namespace) pattern
- [ ] New pattern candidate for `00_meta/patterns/`? **no** — single-project SSOT consolidation

## Archive checklist

- [ ] `proposal.md` frontmatter → `status: archived`
- [ ] Folder moved: `specs/SSOT-014-ssh-user/` → `specs/archive/SSOT-014-ssh-user/`
- [ ] Vault backlog SSOT-014a ticked with PR link
- [ ] Lesson promoted (if approved)
