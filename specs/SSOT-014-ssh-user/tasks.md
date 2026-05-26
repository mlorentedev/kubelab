---
tags: [spec, tasks, ssot, ansible]
created: "2026-05-25"
---

# Tasks — SSOT-014-ssh-user

> TDD order. One task = one focused commit (or staged within one commit if mechanically tied). Tick as you go.

## Setup

- [ ] Branch created from master: `feat/ssot-014a-ssh-user-ssot`
- [ ] `proposal.md` complete; AC are testable
- [ ] No open questions blocking implementation

## Audit (verification before changes)

- [ ] `git grep -n "ssh_user" toolkit/ tests/ infra/` — list every consumer of `ssh_user`
- [ ] Confirm the only programmatic consumer is `generator_ansible.py` (other reads would need migration)

## Implementation

- [ ] Add `networking.ssh_users.{homelab,cloud}` block to `infra/config/values/common.yaml` (keep per-node lines intact for now — additive change)
- [ ] Update `toolkit/features/generator_ansible.py` resolution: `ansible_user = node.get("ssh_user") or networking.ssh_users.cloud` (for vps/aws) or `networking.ssh_users.homelab` (for nodes.*)
- [ ] Regenerate inventory locally: `make config-generate ENV=staging`, `ENV=prod`, `ENV=hub`
- [ ] Verify `git diff infra/ansible/generated/` is empty (byte-identical output)
- [ ] Remove per-node `ssh_user: "manu"` lines from `networking.nodes.*` (6 lines)
- [ ] Remove `ssh_user: "deployer"` lines from `networking.vps` and `networking.aws` (2 lines)
- [ ] Regenerate inventory again — still byte-identical
- [ ] If any test references `networking.nodes.<x>.ssh_user` directly (e.g. `tests/infra/`), update to read from the new SSOT path

## Closing

- [ ] All 6 AC from `proposal.md` verified
- [ ] `make test` green
- [ ] `make config-check-drift ENV=staging` green
- [ ] `make config-check-drift ENV=prod` green
- [ ] `verification.md` filled with evidence
- [ ] PR opened referencing `specs/SSOT-014-ssh-user/`
- [ ] Vault `11-tasks.md` SSOT-014a ticked with PR link on merge

## Machine-readable features

Deferred for SSOT-014 series. The acceptance criteria are mechanical (grep + diff + drift gate) and verified by the existing CI-GATE-002/003 workflow. A `features.json` would duplicate that. If a future spec in the series needs harness-tracked verification, re-introduce here.
