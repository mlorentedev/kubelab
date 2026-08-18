---
id: lesson-100-tailscale-bootstrap-circular-dependency-on-rp
type: lesson
status: active
created: "2026-03-01"
owner: manu
category: networking-dns
tags: [kubelab, networking-dns]
---

# Tailscale Bootstrap Circular Dependency on RPi4

**Context**: RPi4 rebooted and Tailscale failed to reconnect. All `*.kubelab.live` DNS resolution from VPN clients broke because RPi4 is the DNS gateway.

**Problem**: Circular dependency — Tailscale on RPi4 needs to reach Headscale at `vpn.kubelab.live`, but `vpn.kubelab.live` was resolved by RPi4's own CoreDNS to `100.64.0.2` (VPS Tailscale IP), which is only reachable with Tailscale already connected. Error: `dial tcp 100.64.0.2:443: connect: connection timed out`. RPi4 stuck in `unexpected state: NoState`.

**Solution**: Three-layer fix:
1. **Corefile**: Changed `vpn.kubelab.live` from Tailscale IP (`100.64.0.2`) to public IP (`162.55.57.175`). Headscale is the bootstrap service — MUST always be reachable without VPN.
2. **`/etc/hosts` on RPi4**: Added `162.55.57.175 vpn.kubelab.live` as permanent fallback (works even if CoreDNS is down).
3. **Systemd watchdog timer**: `tailscale-watchdog.timer` runs every 5 min, checks if Tailscale is connected, auto-reconnects with correct flags (`--accept-dns=false --advertise-routes=172.16.1.0/24`).

**Rule**: Bootstrap services (Headscale, Cloudflare DNS) must NEVER resolve to VPN-only IPs. Always use public IPs for services that are required to establish the VPN itself. Any node that is part of the DNS/VPN bootstrap chain must have `/etc/hosts` entries as fallback.

---
