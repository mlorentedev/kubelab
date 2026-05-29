---
id: "kubelab-adr-006-tailscale-over-wireguard"
type: adr
status: superseded
tags: [adr, kubelab]
created: "2026-02-09"
owner: manu
---

# ADR-006: Tailscale Over WireGuard for Homelab VPN

## Status

Partially superseded (2026-02-18) — **See [adr-010-headscale-over-tailscale-cloud](adr-010-headscale-over-tailscale-cloud.md)**

The Headscale self-hosted control plane option (noted below as "future evolution") has been executed. Tailscale clients remain but now point to a self-hosted Headscale server on the VPS instead of Tailscale cloud.

Original decision (2026-02-09):

## Context

The KubeLab homelab needs a VPN solution for:

1. Secure access to staging services from anywhere (workstation, mobile)
2. Connecting homelab nodes (MiniPC B, RPi 1) to each other
3. Future: connecting homelab to production VPS

The original plan ([adr-003-hybrid-rpi-hetzner](adr-003-hybrid-rpi-hetzner.md)) assumed WireGuard with the VPS as hub. This required:

- UDP port forwarding on the home router (port 51820)
- Manual key management across all peers
- Hub-and-spoke topology with the VPS as central relay

## Decision

Use **Tailscale** (built on WireGuard) instead of raw WireGuard.

## Rationale

### Hard constraint: no port forwarding

The home network is behind a NAT router without port forwarding access. WireGuard requires an inbound UDP port, making it impossible in this environment. This alone eliminates WireGuard as an option.

### Tailscale advantages

| Factor | WireGuard | Tailscale |
|--------|-----------|-----------|
| NAT traversal | Requires port forwarding | Works behind any NAT (DERP relay fallback) |
| Key management | Manual per-peer | Automatic via control plane |
| Peer discovery | Manual IP + public key exchange | Automatic mesh |
| Subnet routing | Manual iptables rules | `--advertise-routes` flag |
| Split DNS | Manual CoreDNS + manual client config | Built-in via admin console |
| Setup time | Hours (per peer) | Minutes (per device) |

### Trade-offs accepted

- **Dependency on Tailscale control plane**: Tailscale's coordination server is a SaaS dependency. Mitigated by Headscale (self-hosted alternative) as a future option once a public-facing node is available.
- **Free tier limits**: Tailscale free plan supports up to 100 devices and 3 users. More than sufficient for a personal homelab.
- **Less educational value**: Raw WireGuard teaches more about VPN internals. Accepted trade-off for a solo developer who needs a working staging environment, not a networking lab.

### Headscale as future evolution

When the production VPS is deployed (Stream A5), Headscale can be self-hosted on the VPS to eliminate the Tailscale SaaS dependency. The client-side setup (Tailscale clients) remains identical.

## Consequences

1. **No port forwarding needed** — homelab works behind any NAT
2. **RPi 1 as subnet router** — advertises LAN subnet to Tailscale mesh
3. **Split DNS via Tailscale** — `*.staging.kubelab.live` routes to CoreDNS on RPi 1
4. **Ansible inventory uses Tailscale IPs** — not LAN IPs
5. **VPS WireGuard hub plan (C1 original) is abandoned** — no longer needed
6. **Future option**: migrate to Headscale on VPS for full self-hosting

## Related

- [adr-003-hybrid-rpi-hetzner](adr-003-hybrid-rpi-hetzner.md) — Original hybrid architecture (superseded for VPN part)
- [tailscale-setup](../runbooks/tailscale-setup.md) — Setup procedure
- [dns-homelab](../runbooks/dns-homelab.md) — CoreDNS + split DNS configuration
