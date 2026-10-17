---
id: lesson-134-2026-03-17-phase-1-provisioning-session-known
type: lesson
status: active
created: "2026-05-01"
owner: manu
category: networking-dns
tags: [kubelab, networking-dns]
---

# 2026-03-17: Phase 1 Provisioning Session — Known Issues

#### Tailscale kills LAN connectivity on homelab nodes (UNSOLVED)
- **Symptom**: When `tailscaled` runs on ace2, all inbound LAN traffic is dropped. ace2 can ping out (172.16.1.1 OK) but nothing can ping in (172.16.1.5 unreachable from RPi4, ace1, workstation).
- **Proven not the cause**: iptables ts-input (0 references with nodivert), rp_filter (tested 0), UFW (22/tcp open from Anywhere).
- **Proven cause**: tcpdump shows ICMP requests arriving on enp1s0 but kernel never generates reply. Stopping tailscaled instantly fixes LAN.
- **Partial workaround**: `tailscale up --netfilter-mode=nodivert` restored LAN briefly but mesh didn't connect within 30s timeout.
- **To investigate**: `tailscale set --netfilter-mode=nodivert` (persists in state file), userspace networking mode (`--tun=userspace-networking`), or Tailscale version-specific bug.

#### Workstation Tailscale routing table 52 overrides LAN routes
- **Cause**: RPi4 advertises 172.16.1.0/24 via Tailscale. Workstation's table 52 takes priority over physical LAN route.
- **Fix (automated in Makefile BOOTSTRAP)**: `sudo ip rule add to LAN_CIDR lookup main priority 100` before provisioning, removed after.
- **WireGuard AllowedIPs asymmetry**: Outbound to 172.16.1.5 goes via RPi4 peer (subnet route), but ace2 responds directly (own peer). WireGuard drops response because 172.16.1.5 not in ace2's AllowedIPs — only 100.64.0.5/32 is.

#### tailscaled ExecStopPost corrupts state after crash
- **Cause**: `tailscaled --cleanup` tries to remove DNS routes for tailscale0 interface. After crash/power-cycle, interface doesn't exist → cleanup fails → next start fails.
- **Fix**: `systemctl edit tailscaled` → `[Service]\nExecStopPost=` (empty = disable cleanup). Must also `daemon-reload`.
- **/etc/default/tailscaled** uses `PORT` and `FLAGS` variables (NOT `TS_EXTRA_ARGS`). Default: `PORT=0`, `FLAGS=""`.
