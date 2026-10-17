---
id: lesson-212-magicdns-eliminates-tailscale-ip-hardcoding-f
type: lesson
status: active
created: "2026-03-26"
owner: manu
category: networking-dns
tags: [kubelab, networking-dns]
---

# MagicDNS eliminates Tailscale IP hardcoding for cattle instances

**Context**: aws1 gets a new Tailscale IP on every Headscale re-registration.

**Problem**: Kubeconfig, spoke configs, and common.yaml referenced `100.64.0.4` (hardcoded). Every Spot replacement required updating these references.

**Solution**: Headscale MagicDNS was already enabled (`magic_dns: true`, `base_domain: kubelab.vpn`). `aws1.internal.kubelab.live` resolves to whatever IP Headscale assigns. Changed `base_domain` from `kubelab.vpn` (fake TLD) to `internal.kubelab.live` (owned subdomain, ADR-025). Cannot use `vpn.kubelab.live` — Headscale rejects base_domain sharing domain with server_url. Updated K3s TLS SAN, kubeconfig, and common.yaml to use DNS name instead of IP. Zero resource overhead — MagicDNS is built into Tailscale client.

**Rule**: For any node that can be destroyed and recreated (cattle), use `<hostname>.internal.kubelab.live` instead of hardcoded Tailscale IPs (ADR-025). For permanent hardware (pets), IPs are stable and acceptable. NET-001 tracks full migration.
