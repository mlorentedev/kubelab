---
id: lesson-035-ufw-forward-policy-must-be-accept-on-gateway-
type: lesson
status: active
created: "2026-03-19"
owner: manu
category: networking-dns
tags: [kubelab, networking-dns]
---

# UFW FORWARD policy must be ACCEPT on gateway nodes

**Context**: RPi4 acts as LAN gateway (NAT + DHCP + DNS). base_system role installs UFW with default FORWARD DROP.

**Problem**: LAN nodes could resolve DNS (goes to RPi4 INPUT chain, Pi-hole/CoreDNS containers) but couldn't reach internet (requires FORWARD through RPi4 to uplink, dropped by UFW).

**Solution**: Gateway role sets `DEFAULT_FORWARD_POLICY="ACCEPT"` in `/etc/default/ufw` + reload. This is standard for routers — filtering happens at INPUT (perimeter), not FORWARD.

**Rule**: Any node acting as a router/gateway must have UFW forward policy ACCEPT. Add this to the gateway role, not base_system (only gateway nodes need it).
