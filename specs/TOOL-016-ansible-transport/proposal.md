---
id: "TOOL-016-ansible-transport"
type: spec
status: draft # draft | implementing | verifying | archived
created: "2026-07-10"
issue: "kubelab#818"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal]
template_version: "1.0"
---

# TOOL-016: Ansible transport

> **Naming**: file lives at `<repo>/specs/<feature-id>/proposal.md`. `<feature-id>` is `AREA-NNN-slug` (e.g. `TOOL-001-secret-drift`).

## Why

<!-- from issue #818: TOOL-016: codify Ansible provision transport for non-mesh controllers (bastion / ts-bridge seam) -->

`make provision NODE=x` (→ `toolkit infra ansible run`) reaches nodes via the **raw
mesh IP** baked into the generated inventory: `generator_ansible.py` emits
`ansible_host: <tailscale-ip>` + a global `ansible_ssh_common_args:
-o StrictHostKeyChecking=accept-new` — no bastion, no ProxyJump, no ts-bridge seam.
From a **non-mesh controller** (the non-admin workstation with no native Tailscale, or
a bare WSL Ubuntu) provisioning cannot work: normal mode → `100.64.0.x` → no local
route → timeout; `BOOTSTRAP=1` → LAN IP → only works physically on the lab LAN.
kubectl-from-anywhere IS codified (ADR-052: `fetch-kubeconfig` + `connect` abstract the
transport); **Ansible-provision-from-anywhere is NOT**. This asymmetry blocks dev_node
(#816) hardware verification from a non-mesh box and breaks the "operate the fleet from
any machine" capability the project commits to.

## What

The inventory generator learns a **transport mode**. When the controller is off-mesh,
`toolkit infra ansible generate --transport bastion` (threaded through `make provision
… TRANSPORT=bastion`) emits `hosts.yml` where **mesh-only nodes** carry an
`ansible_ssh_common_args` with a `ProxyJump` through the VPS bastion, while
**public-IP nodes (the VPS itself)** are left jump-free. The default (`--transport mesh`,
i.e. no flag) reproduces today's inventory unchanged — zero regression for the
native-Tailscale workstation and CI. Concrete outputs:

1. `generate --transport bastion` → `hosts.yml` with per-host `-o ProxyJump=<bastion>`
   on ace1/ace2/rpi4/rpi3/aws1, none on the VPS.
2. `generate` with no flag → byte-for-byte identical to the current output.
3. New `AnsibleGenerator` unit tests asserting both branches (backfills missing coverage).

## Out of scope

- **ts-bridge integration for Ansible** (issue option 2) — deferred; the bastion seam is
  lighter, reuses the already-working `-J vps-pub` path, and needs no daemon. Revisit if a
  no-bastion topology ever appears.
- **Auto-detection** of controller context (ADR-052-style `resolve_transport` for SSH) —
  v1 is an explicit flag; a detected default can layer on later without redesign.
- **WSL-controller bootstrap** (installing ansible/sops/tailscale + the SOPS key inside
  WSL) — a separate enabler; this ticket ships the transport CODE only.
- **A separate `lan` transport value** — the existing `--bootstrap` flag already emits LAN
  IPs (pre-Tailscale, on-lab use). The flag is `--transport {mesh,bastion}`; `lan` is not
  duplicated as a third value (SSOT / no two-ways-to-do-one-thing).

## Risks / open questions

Failure modes, dependencies, and unknowns to clarify before implementation. If any item here is unresolved, do not move to `tasks.md` yet.

- **[RESOLVED — design decision, 2026-07-10]** (a) Detection: an explicit
  `--transport {mesh,bastion,lan}` flag on `toolkit infra ansible generate`, threaded as
  `make provision … TRANSPORT=bastion`; default `mesh` = today's behaviour (zero
  regression). Env-var / `machine.json` default / auto-detect are deferred layers, not v1.
  (b) Bastion reference: **SSOT-derived** — `<ssh_users.cloud>@<networking.vps.public_ip>`
  with the hop authenticating via `networking.ssh_key` (no dependency on the operator's ssh
  config; no IP/jump hardcoded in source). The exact emitted form (`ProxyJump` vs a
  `ProxyCommand` that passes `-i <ssh_key>`) is settled test-first in implementation so the
  hop provably uses the SSOT key, not the client default identity.
- **Verification ceiling on this box.** The SSH key is passphrase-protected and there is no
  persistent agent on the non-admin box; the transport CODE + unit tests are Windows/CI
  verifiable, but the end-to-end provision-through-bastion is exercised by the human from a
  Linux controller (same runtime-gated shape as #816/#859).
- **Correctness invariant.** ProxyJump must never apply to the VPS (it IS the jump) or any
  public-IP-reachable node — else self-proxy / wrong path. The generator must key the seam
  off "has no public path", not a blanket global arg.

## Acceptance criteria

Observable outcomes. Each must be testable.

- [ ] `generate --transport bastion` emits `ansible_ssh_common_args` with a `ProxyJump`
      for every mesh-only node and leaves the VPS (public-IP) node jump-free.
- [ ] Default / `--transport mesh` reproduces the current inventory unchanged (regression guard).
- [ ] The bastion target derives from `networking.*` SSOT — no IP or jump host hardcoded in source.
- [ ] `make provision NODE=x TRANSPORT=bastion` threads the mode through to the generator.
- [ ] New unit tests cover the generator's transport branches (mesh vs bastion), backfilling
      the currently-absent `AnsibleGenerator` coverage.

## References

- Bitácora board: `kubelab#818` (TOOL-016) — the work-gate for this spec
- Related ADR: `docs/adr/adr-052-cluster-access-transport.md` (kubectl transport — the sibling this mirrors for SSH)
- Related runbook: `docs/runbooks/non-admin-workstation-access.md` (the `vps-pub` / `*-ext` bastion aliases)
- Sibling specs: `specs/archive/TOOL-014-k8s-connect/`, `specs/archive/TOOL-015-fetch-over-transport/`
