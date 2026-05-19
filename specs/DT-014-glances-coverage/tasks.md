---
tags: [spec, tasks]
created: "2026-05-18"
---

# Tasks - DT-014-glances-coverage

> Implementation order: smallest verifiable steps first. Ansible roles do not have unit tests in this repo (no molecule, no ansible-test setup). Verification is via lint + `--check` dry-run + live smoke on the actual nodes.

## Setup

- [x] Branch created from master: `fix/dash-glances-coverage`
- [x] `proposal.md` complete with testable AC
- [x] No unresolved questions in `proposal.md`

## Implementation

- [ ] Create `infra/ansible/roles/vps_services/` skeleton (defaults/main.yml, tasks/main.yml, templates/compose.yml.j2) cloned minimal from `beelink_services` — only Glances.
- [ ] Create `infra/ansible/roles/rpi4_services/` skeleton (same minimal pattern).
- [ ] Update `infra/ansible/playbooks/provision-vps.yml` to add `vps_services` role after Docker/Tailscale prerequisites, tags `[services, monitoring]`.
- [ ] Update `infra/ansible/playbooks/provision-rpi4.yml` to add `rpi4_services` role after `docker` and `tailscale`, tags `[services, monitoring]`.
- [ ] Run `yamllint` on new files + modified playbooks — fix violations.
- [ ] Run `ansible-lint infra/ansible/roles/vps_services/ infra/ansible/roles/rpi4_services/` — fix violations.
- [ ] Run dry-run: `make provision NODE=vps ENV=prod TAGS=monitoring -- --check` — confirm no errors.
- [ ] Run dry-run: `make provision NODE=rpi4 ENV=prod TAGS=monitoring -- --check` — confirm no errors.

## Live smoke (requires VPS + rpi4 powered and reachable)

- [ ] `make provision NODE=vps ENV=prod TAGS=monitoring` (real deploy).
- [ ] `make provision NODE=rpi4 ENV=prod TAGS=monitoring` (real deploy).
- [ ] `curl -sf http://100.64.0.2:61208/api/4/quicklook | jq .cpu.total` returns a float.
- [ ] `curl -sf http://100.64.0.10:61208/api/4/quicklook | jq .cpu.total` returns a float.
- [ ] Open Homepage cockpit; confirm VPS + RPi4 tiles render live metrics.

## Closing

- [ ] All 9 acceptance criteria covered.
- [ ] `verification.md` filled with commit hashes + curl outputs + Homepage screenshot reference.
- [ ] No unrelated diff (only the 2 new roles + 2 playbook updates).
- [ ] PR opened referencing this spec folder.
- [ ] On merge: `git mv specs/DT-014-glances-coverage specs/archive/DT-014-glances-coverage` + tick DASH-DT-014 in `11-tasks.md` with PR link.

## Note on TDD applicability

Ansible roles in this repo are not unit-tested (no `molecule`, no `ansible-test`, no role-level pytest). Strict TDD (failing test first) is not feasible without first installing a test framework — out of scope for this PR. Verification is therefore lint → dry-run → live smoke, captured in `verification.md`. If we want strict TDD for future Ansible work, that is a separate ticket (potential TOOL-009: introduce molecule).
