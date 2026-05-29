---
id: "kubelab-adr-004-ansible-for-config-management"
type: adr
status: accepted
tags: [adr, kubelab]
created: "2026-02-08"
owner: manu
---

# ADR-004: Ansible for configuration management

**Status**: Accepted

**Date**: 2024-01-01

## Context

KubeLab nodes (2-3 RPis + 1 Hetzner VPS) need consistent configuration: OS packages, user accounts, SSH keys, firewall rules, k3s installation, and system tuning. Options:

1. **Ansible**: agentless, SSH-based, YAML playbooks
2. **Terraform**: infrastructure provisioning, less suited for OS-level config
3. **Shell scripts**: simple but fragile, no idempotency guarantees
4. **Salt/Puppet/Chef**: agent-based, overkill for 3-4 nodes

## Decision

Use Ansible for all node configuration management. Terraform is reserved for cloud resource provisioning (Hetzner VPS, DNS records) where applicable.

## Consequences

**Positive**:

- Agentless: no daemon running on resource-constrained RPi nodes
- SSH-based: works immediately with existing access, no PKI setup
- Idempotent playbooks: safe to re-run, self-documenting infrastructure
- YAML syntax: readable by anyone, low learning curve
- Inventory files clearly define the hybrid topology

**Negative**:

- Push-based model: changes only apply when playbooks are run (no continuous enforcement)
- Slower execution than agent-based tools for large fleets (irrelevant at 3-4 nodes)
- Python dependency on target nodes (pre-installed on Raspberry Pi OS)

**Neutral**:

- Complements Terraform rather than replacing it: Terraform provisions, Ansible configures
- Ansible skills transfer directly to enterprise environments (widely used)

## References

- Runbooks — Ansible-driven operational procedures
