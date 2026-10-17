---
id: lesson-048-tailscale-over-wireguard-when-no-port-forward
type: lesson
status: active
created: "2026-02-09"
owner: manu
category: networking-dns
tags: [kubelab, networking-dns]
---

# Tailscale Over WireGuard When No Port Forwarding

**Context**: Configuring VPN for remote access to the homelab.

**Problem**: WireGuard requires an open UDP port on the router. Without router access (NAT without port forwarding) → WireGuard is impossible. Headscale requires a public node.

**Solution**: Tailscale (or Headscale via public relay). Network constraints dictate the technology, not preference.

**Rule**: Before choosing a VPN, verify: do I have port forwarding? Yes → WireGuard. No → Tailscale/Headscale. Network architecture decides.
