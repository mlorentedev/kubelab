---
id: lesson-055-tailscale-dns-chicken-and-egg-on-pi-hole-node
type: lesson
status: active
created: "2026-02-21"
owner: manu
tags: [kubelab, lesson]
---

# Tailscale DNS Chicken-and-Egg on Pi-hole Nodes

**Context**: RPi 4 as subnet router for Headscale VPN mesh. After reboot, VPN mesh was down.

**Problem**: Dual cause: (1) Tailscale can rewrite `/etc/resolv.conf` with `100.100.100.100` → circular dependency. (2) Even with `--accept-dns=false`, `tailscaled.service` starts before Docker (Pi-hole) → `nameserver 127.0.0.1` fails because Pi-hole isn't ready → Tailscale enters retry loop and never recovers.

**Solution**: Four measures: (1) `--accept-dns=false` on `tailscale up`, (2) dual nameserver in resolv.conf: `127.0.0.1` (Pi-hole) + `8.8.8.8` (boot fallback), (3) `chattr +i /etc/resolv.conf`, (4) systemd drop-in: `After=docker.service` for tailscaled.

**Rule**: On DNS nodes without `systemd-resolved`: ALWAYS `--accept-dns=false` + public fallback nameserver + order boot sequence. Only affects RPi 4 — all other nodes have `systemd-resolved` and need no changes.
