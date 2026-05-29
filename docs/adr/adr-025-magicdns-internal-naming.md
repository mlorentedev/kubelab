---
id: adr-025-magicdns-internal-naming
type: adr
status: active
created: "2026-03-26"
owner: manu
---


# ADR-025: MagicDNS for Internal Service Naming

> **Status:** Accepted
> **Date:** 2026-03-26
> **Supersedes:** None
> **Related:** ADR-010 (Headscale), ADR-023 (Hub-and-Spoke GitOps), ADR-006 (Tailscale)

## Context

KubeLab uses Headscale (self-hosted Tailscale) as its VPN mesh. Each node gets a stable Tailscale IP from the `100.64.0.0/24` range. Infrastructure configs (kubeconfigs, spoke registrations, Ansible inventories) reference these IPs directly.

The AWS hub (`aws1`) runs as a Spot instance that can be terminated and recreated at any time. Each recreation registers a new Tailscale identity, and Headscale assigns a **new IP**. This breaks all hardcoded references (kubeconfig, spoke configs, common.yaml).

Additionally, the original `base_domain` was `kubelab.vpn` — an invented TLD that:
- Could conflict if `.vpn` becomes a real gTLD (ICANN precedent)
- Doesn't follow DNS hierarchy conventions
- Isn't under a domain we own

## Decision

1. **Use Headscale MagicDNS** (`<hostname>.vpn.kubelab.live`) instead of hardcoded Tailscale IPs for cattle instances (nodes that can be destroyed and recreated).

2. **Set `base_domain: internal.kubelab.live`** — a subdomain of our owned domain, following proper DNS hierarchy. Cannot use any `*.kubelab.live` subdomain — Headscale v0.28 rejects base_domain sharing a parent domain with server_url (`https://vpn.kubelab.live`). `.internal` is IANA-reserved for private networks. Closes INTERNAL-001.

3. **Apply MagicDNS to aws1 immediately** (cattle instance). Other nodes (physical hardware, "pets") keep hardcoded IPs until hardware replacement (tracked as NET-001).

## How MagicDNS Works

```
Client query: aws1.vpn.kubelab.live
       ↓
Tailscale client (local on every VPN node)
       ↓
Queries Headscale coordination server
       ↓
Returns: 100.64.0.X (whatever IP aws1 currently has)
```

- Zero infrastructure overhead — MagicDNS is built into the Tailscale client
- Only resolves from within the VPN (not public DNS)
- IP can change freely; DNS name is stable

## What Changes

| Component | Before | After |
|-----------|--------|-------|
| Headscale `base_domain` | `kubelab.vpn` (fake TLD) | `kubelab.internal` (IANA-reserved `.internal` TLD) |
| aws1 in common.yaml | `tailscale_ip: "100.64.0.4"` | `tailscale_dns: "aws1.kubelab.internal"` |
| Hub kubeconfig | `https://100.64.0.4:6443` | `https://aws1.kubelab.internal:6443` |
| K3s TLS SAN | `--tls-san=$(tailscale ip -4)` | `--tls-san=aws1.kubelab.internal` + IP |
| cloud-init | No node cleanup | Deletes stale Headscale node via API before registration |
| Physical nodes (ace1, rpi4, etc.) | Hardcoded IPs | No change (NET-001 for future) |

## Consequences

### Positive
- aws1 Spot replacement is fully automated — no manual IP updates
- Proper DNS hierarchy under owned domain
- Pattern ready for any future cattle instances
- Zero resource overhead

### Negative
- Kubeconfig only works from VPN-connected machines (already the case with IPs)
- K8s EndpointSlice still needs IPs (can't use DNS) — argocd.yaml still hardcodes IP
- Physical nodes not yet migrated (NET-001 debt)

### Risks
- Headscale restart causes brief VPN disruption (~10s)
- If Headscale is down, MagicDNS doesn't resolve (same as current — VPN down = no access)

## Implementation

1. Update Headscale config template: `base_domain: vpn.kubelab.live`
2. Deploy VPS (Ansible restarts Headscale)
3. Update cloud-init, common.yaml, Makefile, kubeconfig with new domain
4. Recreate aws1 K3s TLS SAN with DNS name
5. Verify: `dig aws1.kubelab.internal` from workstation
