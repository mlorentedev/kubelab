---
id: "kubelab-adr-010-headscale-over-tailscale-cloud"
type: adr
status: accepted
tags: [adr, kubelab]
created: "2026-02-18"
owner: manu
---

# ADR-010: Headscale Over Tailscale Cloud for VPN Control Plane

## Status

Accepted (2026-02-18)

## Context

ADR-006 chose Tailscale over raw WireGuard for the homelab VPN, with a noted future option:

> "When the production VPS is deployed (Stream A5), Headscale can be self-hosted on the VPS to eliminate the Tailscale SaaS dependency."

The production VPS is now confirmed (Hetzner CAX21, ARM64, 8GB RAM). The decision of whether to keep Tailscale cloud or self-host Headscale has been reopened for the following reasons:

1. **Professional skills signal**: WireGuard/Headscale is a common pattern in enterprise homelab and SRE environments. Knowing how to operate a self-hosted VPN control plane is a more transferable skill than clicking buttons in Tailscale's SaaS admin console.
2. **No SaaS dependency**: Eliminates Tailscale's coordination server from the critical path. Homelab continues to function if Tailscale has an outage.
3. **VPS is available**: The hard constraint that blocked Headscale originally (needing a public-facing server) is resolved.
4. **Cloudflare Tunnel remains**: Used only for Pollex public HTTP API — separate concern, unaffected by this decision.

## Decision

Deploy **Headscale** on the production VPS as the Tailscale-compatible coordination server. Use Tailscale clients unchanged on all homelab nodes. WireGuard is the underlying protocol.

Cloudflare Tunnel is NOT replaced by this — it serves a different purpose (public HTTPS ingress for Pollex API without exposing the VPS port directly).

## Rationale

### Why Headscale over Tailscale cloud

| Factor | Tailscale cloud | Headscale |
|--------|----------------|-----------|
| Control plane ownership | SaaS (Tailscale Inc.) | Self-hosted on VPS |
| WireGuard knowledge | Hidden/abstracted | Visible (control plane config) |
| Outage dependency | Tailscale outage = no VPN | VPS outage = no VPN (same blast radius) |
| Cost | Free (hobby tier, 100 devices) | Free (open source) |
| Client compatibility | Tailscale clients | Same Tailscale clients, different login URL |
| Admin UI | Tailscale web console | Headscale CLI + optional web UI |
| Split DNS | Admin console UI | Headscale config + Tailscale client config |
| Setup complexity | ~10 min | ~1 hour |
| Industry relevance | Moderate | High (self-operated VPN infra) |

### Why not raw WireGuard

WireGuard (without Tailscale) requires:
- Manual peer key exchange for every new device
- Manual DERP relay setup for NAT traversal (home router has no port forwarding)
- Manual routing rules per peer

Headscale gives WireGuard protocol knowledge (ADR-006's "less educational value" concern addressed) while keeping the ergonomics of Tailscale client tooling.

### Trade-offs accepted

- **Headscale is a community project**, not Tailscale Inc. Bugs/breaking changes possible. Mitigated by pinning versions and the ability to fall back to Tailscale cloud (just change login URL on each client).
- **VPS is now in the critical path for VPN**. If VPS goes down, new devices can't join the mesh. Existing peers continue WireGuard connections via cached keys (short-lived degradation). Acceptable for homelab.
- **Split DNS configuration is manual** (headscale config vs. admin console UI). Acceptable given the learning value.

## Implementation

Headscale runs as a Docker Compose service on the VPS (alongside other prod services):

```yaml
# infra/stacks/services/core/headscale/compose.base.yml
services:
  headscale:
    image: headscale/headscale:latest
    ports:
      - "8080:8080"   # Control plane API
      - "3478:3478/udp"  # DERP relay
    volumes:
      - ./config:/etc/headscale
      - headscale-data:/var/lib/headscale
```

Domain: `vpn.kubelab.live` → VPS IP (Cloudflare DNS A record).

Tailscale client login on each node:
```bash
sudo tailscale up --login-server=https://vpn.kubelab.live
```

## Consequences

1. **VPS hosts the VPN control plane** — adds a service to the VPS Docker Compose stack
2. **All nodes join via Headscale** — `--login-server=https://vpn.kubelab.live`
3. **Tailscale clients remain unchanged** — same binary, same CLI, different coordination server
4. **Runbook**: see [headscale-setup](../runbooks/headscale-setup.md)
5. **ADR-006 is partially superseded** — the "future option" has been executed

## Related

- [adr-006-tailscale-over-wireguard](adr-006-tailscale-over-wireguard.md) — Previous VPN decision (partially superseded)
- [adr-011-k3s-homelab-staging](adr-011-k3s-homelab-staging.md) — K3s topology that uses this VPN
- [headscale-setup](../runbooks/headscale-setup.md) — Setup procedure
- [tailscale-setup](../runbooks/tailscale-setup.md) — Legacy procedure (now references Headscale)
