---
id: "VPNACL-001-fleet-segmentation"
type: spec
status: draft # draft | implementing | verifying | archived
created: "2026-05-31"
tags: [spec, proposal]
template_version: "1.0"
---

# VPNACL-001: Agent-fleet Headscale ACL + first-agent onboarding

<!-- from 10_projects/kubelab/11-tasks.md: VPN-ACL-001/002/003 (ADR-041). Implements the first deployable increment of the tag-based Headscale ACL. -->

## Why

The Headscale mesh is **allow-all today** (`policy.path: ""`) — ADR-013 designed segmentation but it was never deployed. A new automation agent (`hermes`), the first of a planned fleet (more `hermes`, `openclaw`, …), is joining from an **external private cloud provider**. Without segmentation it inherits the same blanket trust as the operator's workstation: `100.64.0.0/10` is trusted in bulk by `trusted_cidrs`, CrowdSec, and Authelia. ADR-041 decided the model (Option A: dedicated `agents` user + per-type tags + file-mode deny-by-default, permissive-first); this spec ships the first runnable increment (vault `VPN-ACL-001/002/003`).

## What

After this PR:

- The `headscale` Ansible role accepts a **policy file** (`policy.path` parameterized) and **reloads** Headscale on change (`systemctl reload`, no restart/downtime).
- A git-versioned `policy.hujson` defines a dedicated Headscale user `agents`, per-type tags (`tag:hermes`), `tagOwners`, and a **permissive-first baseline** that preserves every current flow (admin→all, ArgoCD hub→spoke `:6443`, rpi4 subnet route `172.16.1.0/24`, intra-K3s, monitoring).
- CI runs `headscale policy check` (syntax gate; v0.28-available).
- An **external connectivity-probe harness** asserts the preserved flows after each reload and **auto-reverts** to the prior known-good policy on failure.
- `hermes` is onboarded: registered under user `agents` with `--advertise-tags tag:hermes`, its assigned IP recorded in `networking.nodes` SSOT, and it authenticates to its target services with **its own scoped credential** (C6 zero-trust), not via network trust.

## Out of scope

- **VPN-ACL-004** — least-privilege tightening (narrowing existing flows toward deny-by-default). This spec only deploys the permissive baseline + agent rules.
- **VPN-ACL-006** — Headscale v0.28→v0.29 upgrade (gains in-engine `tests` block). Done before the tightening iteration, not here.
- **VPN-ACL-005** — formal credential-rotation policy for tagged agents.

## Risks / open questions

- **[AGENT-DRAFT — review before archive]** Exact `dst` matrix for `tag:hermes`. Operator's steer: "like just another node but somewhat more controlled" → needs the concrete allow-list (which nodes/ports) PLUS the crown-jewels to exclude (e.g. the Headscale control plane, SOPS/secret surfaces). **MUST resolve before authoring `policy.hujson` (VPN-ACL-002).**
- Single **production** control plane, no staging (ADR-015): a wrong deny-by-default could sever the live mesh. Mitigated by permissive-first (baseline cannot break flows by construction) + external probe + auto-revert (reload is reversible in seconds). Note: on v0.28 `policy check` is **syntax-only**; the `tests` block is v0.29.0.
- **[AGENT-DRAFT — review before archive]** Confirm exact `headscale nodes tag` / `headscale preauthkeys create --tags` flags on the **live v0.28.0 install** before onboarding (flagged [UNCERTAIN] in the ADR-041 audit).
- **[AGENT-DRAFT — review before archive]** Per-service credential mechanics for C6 zero-trust (SSH keypair provisioning + which API tokens / service accounts) and where they live (toolkit + SOPS). Decide whether minting hermes's first credential is in-scope here or a thin follow-on.

## Acceptance criteria

- [ ] The `headscale` role exposes a policy-path parameter, mounts the HuJSON file, and **reloads** (not restarts) Headscale on change; deploy is driven through the Makefile/toolkit (no manual edits on the VPS).
- [ ] `policy.hujson` passes `headscale policy check` as a CI gate.
- [ ] After reload of the permissive-first baseline, the external probe confirms **all preserved flows** still work (admin→nodes SSH, ArgoCD hub→spoke `:6443`, rpi4 route, intra-K3s, monitoring); a deliberately-broken policy triggers **auto-revert** to the prior policy.
- [ ] `hermes` is reachable via SSH over the VPN at its recorded Tailscale IP, carries `tag:hermes` (verified in `headscale nodes list`), and authenticates to at least one target service with its **own scoped credential** (not the `100.64.0.0/10` network-trust bypass).

## References

- Repo ADR: `docs/adr/adr-041-agent-fleet-vpn-segmentation.md` (the "why"); extends `adr-013-vpn-consolidation.md`, `adr-015-vps-k3s-migration-strategy.md`.
- Vault: `10_projects/kubelab/11-tasks.md` — `VPN-ACL-001/002/003` (+ 004/005/006 follow-on).
- Repo paths: `infra/ansible/roles/headscale/`, `infra/config/values/common.yaml` (`networking.nodes`, `apps.services.core.headscale`), `toolkit/`.
