---
id: lesson-064-lan-dns-dependency-breaks-tailscale-reconnect
type: lesson
status: active
created: "2026-02-22"
owner: manu
tags: [kubelab, lesson]
---

# LAN DNS Dependency Breaks Tailscale Reconnection

**Context**: Jetson Nano lost Tailscale connectivity and could not reconnect.

**Problem**: All LAN nodes use Pi-hole (RPi4) as DNS. If RPi4 goes down → DNS fails → nodes can't resolve `vpn.kubelab.live` (Headscale control server) → Tailscale can't reconnect → nodes become VPN-unreachable. Failure chain: RPi4 down → Pi-hole down → DNS down → Tailscale down → everything unreachable.

**Solution**: Ansible role `dns_resilience` manages a block in `/etc/hosts` with `blockinfile` on all homelab nodes. Entry: `162.55.57.175 vpn.kubelab.live`. Static inventory with Tailscale IPs at `infra/ansible/inventories/homelab.yml`.

**Rule**: Every domain critical for VPN connectivity must have a fallback in `/etc/hosts` managed by Ansible. Never depend on a DNS chain that can cascade-fail.

---
