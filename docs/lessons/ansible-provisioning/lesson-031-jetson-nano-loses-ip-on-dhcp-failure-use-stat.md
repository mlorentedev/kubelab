---
id: lesson-031-jetson-nano-loses-ip-on-dhcp-failure-use-stat
type: lesson
status: active
created: "2026-03-19"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning]
---

# Jetson Nano loses IP on DHCP failure — use static nmcli config

**Context**: Jetson Nano (`kubelab-jet1`) went offline. No LAN or Tailscale response despite being powered on.

**Problem**: `eth0` was UP but had no IPv4 address — only link-local IPv6. NetworkManager connection `cubelab` was stuck in "connecting (getting IP configuration)" state. DHCP from RPi4 Pi-hole wasn't responding (reservation exists but DHCP server didn't assign).

**Solution**: `sudo nmcli connection modify cubelab ipv4.method manual ipv4.addresses 172.16.1.4/24 ipv4.gateway 172.16.1.1 ipv4.dns 172.16.1.1 && sudo nmcli connection up cubelab`. Survives reboot.

**Rule**: Jetson Nano (Ubuntu 18.04, NetworkManager) should use static IP via nmcli, not DHCP. DHCP reservations are fragile on this hardware. Document in ANSIBLE-014.
