---
id: "ANSIBLE-066-pinned-host-keys"
type: spec
status: draft # draft | implementing | verifying | archived
created: "2026-10-14"
issue: "mlorentedev/kubelab#2223"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal]
template_version: "1.0"
wip_override: "prerequisite of SEC-033 (P1, an exposed SSH key on every node): Ansible must verify host keys before it edits authorized_keys; SEC-032 and TF-007 are in review to archive (17 active, limit 10, 2026-10-14)"
---

# ANSIBLE-066-pinned-host-keys

> **Naming**: file lives at `<repo>/specs/ANSIBLE-066-pinned-host-keys/proposal.md`. `ANSIBLE-066-pinned-host-keys` is `AREA-NNN-slug` (e.g. `TOOL-001-secret-drift`).

## Why

Every Ansible run trusts host keys on first use: the generated inventory and the committed `homelab.yml` set `-o StrictHostKeyChecking=accept-new` for the whole fleet (#2223). A reinstalled node, or a mesh address that moved to another machine (lesson-113), is trusted by the first run from a fresh workstation without anyone comparing its key. That contradicts the owner's rule for the mesh (host keys are verified out of band, never accepted unseen), and it blocks SEC-033 (#2246): a play that rewrites `authorized_keys` must first know it is talking to the right machine.

## What

- The inventory verifies every stable node against the pinned file dotfiles deploys (`~/.ssh/known_hosts_pinned`, mlorentedev/dotfiles#2356, #2465): `-o StrictHostKeyChecking=yes -o UserKnownHostsFile=<pinned file>`. The path is declared once, as `networking.ssh_known_hosts` beside `networking.ssh_key`.
- A node whose machine is replaced by design (the hub: `tailscale_dns` with no `tailscale_ip`) keeps today's scoped `accept-new`, as a per-host override, until host certificates land (#1261, mlorentedev/dotfiles#2373). The exception is derived from the SSOT, never listed by name.
- The bastion hop to the VPS is verified the same way.
- `toolkit infra ansible run` refuses to start when the pinned file is missing, naming the file and how to get it, instead of failing on the first host with a bare "Host key verification failed".
- The committed `homelab.yml` carries the same arguments.
- A runbook covers adding a node: register it in `common.yaml`, verify its host key out of band, pin it in dotfiles, then provision.

## Out of scope

- The SSH CA (#1261, mlorentedev/dotfiles#2373), which replaces the pinned file and the hub exception.
- Which user keys a node accepts: SEC-033 (#2246).
- The `-lan` jump aliases refused by the node hardening: mlorentedev/dotfiles#2464.
- `k8s_kubeconfig`'s own scoped `accept-new` for the hub (TOOL-044), which has the same justification and the same exit (#1261).

## Risks / open questions

- The controller must have dotfiles deployed. It already must (the SSH aliases and the key come from there); the preflight makes the dependency explicit.
- A node not yet pinned can no longer be provisioned. That is the intent: the runbook puts pinning before the first run, including `--bootstrap` runs over the LAN, whose addresses each pinned line carries.
- Removing an override test-first: the existing mesh test asserts no per-host args; it is narrowed to stable nodes, and a new test asserts the hub override is derived from the SSOT shape.

## Acceptance criteria

- [ ] AC1: the generated inventory (mesh and bootstrap) sets `StrictHostKeyChecking=yes` and `UserKnownHostsFile` to `networking.ssh_known_hosts` for every host, and no stable host carries `accept-new`. Tested from the real `common.yaml`.
- [ ] AC2: a node with `tailscale_dns` and no `tailscale_ip` carries `StrictHostKeyChecking=accept-new` as a per-host override, and only such a node does. Tested with a fixture that adds and removes the `tailscale_ip`.
- [ ] AC3: in bastion transport, both the jump to the VPS and the proxied hop verify against the pinned file (the hub keeps its override on the proxied hop).
- [ ] AC4: `toolkit infra ansible run` exits non-zero before invoking `ansible-playbook` when the pinned file does not exist, and the message names the file and the dotfiles deploy.
- [ ] AC5: `infra/ansible/inventories/homelab.yml` carries the same global arguments, and a test fails if `accept-new` reappears anywhere in it.
- [ ] AC6: live, from the Mac: a read-only play (`ping`) against every stable node succeeds with the generated inventory, and the same play against a copy of the pinned file with one key swapped fails on that host.
- [ ] AC7: `docs/runbooks/add-a-node.md` exists and orders pinning before the first provisioning run; `wait-node-ready.yml`'s comments no longer say the inventory uses `accept-new`.

## References

- Bitácora board: the GitHub issue / Project item tracking this spec (see the `issue:` frontmatter field)
- Related ADR: `<repo>/docs/adr/adr-XXX.md` (if any)
- Related patterns: `00_meta/patterns/<pattern>.md` (if any)
