---
id: lesson-130-tailscale-subnet-routes-intercept-lan-traffic
type: lesson
status: active
created: "2026-03-17"
owner: manu
category: networking-dns
tags: [kubelab, networking-dns]
---

# Tailscale subnet routes intercept LAN traffic from workstation

**Context:** ADR-023 Phase 1 — after ace2 joined Tailscale mesh, workstation lost LAN connectivity to 172.16.1.0/24
**Problem:** RPi4 advertises 172.16.1.0/24 via Tailscale (--advertise-routes). Workstation's Tailscale intercepts ALL traffic to that subnet via tailscale0 (table 52) instead of the physical LAN route. ace1 (not in mesh) worked because Tailscale routed it via RPi4→LAN→ace1. ace2 (new peer) failed because Tailscale tried direct peer routing before mesh was stable. Result: `ip route get 172.16.1.5` → `dev tailscale0`, not `dev wlp1s0`.
**Solution:** Pending investigation. Options: (1) Remove RPi4 subnet route advertisement if all LAN nodes join Tailscale directly, (2) Configure Tailscale exit node or split routing, (3) Add direct LAN route with higher priority than Tailscale table 52. Must fix before ace1 provisioning — BOOTSTRAP mode needs LAN connectivity.
**Tags:** `#tailscale` `#networking` `#routing` `#provisioning`
