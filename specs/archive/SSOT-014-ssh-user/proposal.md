---
id: "SSOT-014-ssh-user"
type: spec
status: archived
created: "2026-05-25"
tags: [spec, proposal, ssot, ansible, networking]
template_version: "1.0"
---

# SSOT-014a: Consolidate `ssh_user` as a single source of truth

<!-- from 10_projects/kubelab/11-tasks.md SSOT-014a: "Consolidate ssh_user — new SSOT networking.ssh_users.{homelab,cloud} in common.yaml. Generator (generator_ansible.py) infers category by YAML position (vps + aws → cloud; nodes.* → homelab). Per-node override stays optional." -->

## Why

`infra/config/values/common.yaml` currently repeats `ssh_user: "manu"` 6 times (once per homelab node: ace1, ace2, beelink, rpi3, rpi4, jetson) and `ssh_user: "deployer"` 2 times (vps, aws1). Changing any of these — for a rename, a new operator user, or a fork — means touching 8 lines that must stay in lockstep. The duplication is friction: every rename becomes an audit instead of a one-line change.

This is master plan SSOT-014's first sub-task (a/b/c). It does NOT change the value `"manu"` (that is the trivial SEC-PRIVACY-001 follow-up after the SSOT exists). It establishes the structure that makes the value change a one-liner.

## What

A new SSOT `networking.ssh_users.{homelab,cloud}` is the single declaration site for the SSH user per node category. The Ansible inventory generator (`toolkit/features/generator_ansible.py`) resolves each node's `ansible_user` as: per-node `ssh_user` override if present, else `networking.ssh_users.cloud` (for nodes under `networking.vps` or `networking.aws`), else `networking.ssh_users.homelab` (for nodes under `networking.nodes.*`).

Concrete output: regenerated `infra/ansible/generated/{staging,prod,hub}/hosts.yml` is byte-identical to the current committed versions (no semantic change — only the SSOT layer changes).

## Out of scope

- Renaming the value `"manu"` to anything else. That is SEC-PRIVACY-001 (Phase B in the master plan), done as a 1-line follow-up after SSOT-014a/b/c land.
- Consolidating `admin_username` (SSOT-014b) and `apps.contact.email` (SSOT-014c). Each is a separate spec/PR.
- Refactoring node category to an explicit `category:` field. The current spec uses YAML-position inference (vps/aws → cloud, nodes.* → homelab) per the design decision.

## Risks / open questions

- **Schema migration safety:** the 6 homelab `ssh_user: "manu"` lines are removed in this PR. If any consumer (other than the Ansible inventory generator) reads `networking.nodes.<x>.ssh_user` directly, it will see `None`. Mitigation: audit consumers before the PR via `git grep "ssh_user" toolkit/ tests/`. **Status:** to be verified during implementation; no blocker expected since the only known consumer is `generator_ansible.py`.
- **CI-GATE-003 drift gate:** the regenerated `hosts.yml` must be byte-identical to the committed version. If it isn't, the gate will fail and surface real semantic drift. Acts as a safety net, not a risk.

## Acceptance criteria

- [ ] AC1: `infra/config/values/common.yaml` declares `networking.ssh_users.homelab` and `networking.ssh_users.cloud`; the 6 per-node `ssh_user` lines under `networking.nodes.*` (homelab) and the 2 lines under `networking.vps` / `networking.aws` (cloud) are removed.
- [ ] AC2: `git grep '"manu"' infra/config/values/common.yaml` returns exactly **one** match (the new SSOT line) — down from 7.
- [ ] AC3: `make config-generate ENV=staging` regenerates `infra/ansible/generated/staging/hosts.yml` byte-identical to the committed version (verified via `git diff --quiet`).
- [ ] AC4: same as AC3 for `ENV=prod` and `ENV=hub`.
- [ ] AC5: `make config-check-drift ENV=staging` and `ENV=prod` both pass (CI-GATE-002/003 gate green).
- [ ] AC6: existing tests pass (`make test`).

## References

- Vault backlog: `10_projects/kubelab/11-tasks.md` SSOT-014 master + SSOT-014a sub-task
- Related ADR: ADR-036 (shared infra namespace pattern — same SSOT discipline applied here)
- Related patterns: `00_meta/patterns/pattern-spec-driven-development.md`
- Master plan context: session memory `MEMORY.md` Session Handoff 2026-05-25
- Sibling specs (future): SSOT-014b (admin_username), SSOT-014c (contact email)
