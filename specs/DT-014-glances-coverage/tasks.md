---
tags: [spec, tasks]
created: "2026-05-18"
---

# Tasks - DT-014-glances-coverage (PR3a)

> Re-scoped after audit. Ansible roles in this repo have no unit-test framework; verification is lint + dry-run + live smoke.

## Setup

- [x] Branch: `fix/dash-glances-coverage`
- [x] `proposal.md` re-scoped for PR3a
- [x] Vault entry split into DASH-DT-014a (this PR) + DASH-DT-014b (PR3b)

## Implementation

- [ ] Create `infra/ansible/roles/glances/` (defaults, tasks, templates, handlers) — beelink tailscale_ip-bind pattern.
- [ ] Modify `infra/ansible/roles/ace2_services/tasks/main.yml`: remove the 3 legacy `/opt/glances` cleanup tasks (now redundant; we are re-adding Glances on ace2 via shared role).
- [ ] Update `infra/ansible/playbooks/provision-ace1.yml`: add `glances` role to roles list, tags `[services, monitoring]`, vars `tailscale_ip + glances_*` from `config.networking.nodes.ace1` + `config.apps.services.observability.glances`.
- [ ] Update `infra/ansible/playbooks/provision-ace2.yml`: same wiring for ace2.
- [ ] Run `yamllint` on new files + modified playbooks.
- [ ] Run `ansible-lint infra/ansible/roles/glances/` (expect FQCN + var-naming warnings matching existing convention; tracked TOOL-009).
- [ ] Run `ansible-playbook --syntax-check` on both modified playbooks.

## Live smoke (ace1 + ace2 reachable: confirmed 2026-05-18 9:25pm)

- [ ] `make provision NODE=ace1 ENV=staging TAGS=monitoring` (real deploy).
- [ ] `make provision NODE=ace2 ENV=staging TAGS=monitoring` (real deploy).
- [ ] `curl -sf http://100.64.0.11:61208/api/4/quicklook | jq .cpu.total` returns a float.
- [ ] `curl -sf http://100.64.0.5:61208/api/4/quicklook | jq .cpu.total` returns a float.
- [ ] Open Homepage cockpit; confirm ace1 + ace2 tiles render live metrics.

## Closing

- [ ] All 8 acceptance criteria covered.
- [ ] `verification.md` filled with commit hashes + curl outputs.
- [ ] No unrelated diff outside the agreed scope.
- [ ] PR opened referencing this spec folder + DASH-DT-014a vault entry + DASH-DT-014b as follow-up.
- [ ] On merge: `git mv specs/DT-014-glances-coverage specs/archive/DT-014-glances-coverage` + tick DASH-DT-014a in `11-tasks.md` with PR link.

## Note on TDD applicability

No `molecule` or `ansible-test` in repo. TDD-strict is infeasible without first introducing a test framework (out of scope here; potential TOOL-010). Verification chain: lint → syntax-check → dry-run (if applicable via `--check` mode) → live smoke captured in `verification.md`.
