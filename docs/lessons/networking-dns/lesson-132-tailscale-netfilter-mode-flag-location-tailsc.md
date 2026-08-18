---
id: lesson-132-tailscale-netfilter-mode-flag-location-tailsc
type: lesson
status: active
created: "2026-03-17"
owner: manu
category: networking-dns
tags: [kubelab, networking-dns]
---

# Tailscale netfilter-mode flag location: tailscale up, NOT tailscaled daemon

**Context:** ADR-023 Phase 1 — debugging Tailscale blocking LAN connectivity on ace2
**Problem:** tailscaled daemon kills LAN connectivity on ace2 when it starts. Tried --netfilter-mode=nodivert as daemon flag (FLAGS in /etc/default/tailscaled) — INVALIDARGUMENT. Tried as TS_EXTRA_ARGS — wrong variable name (service uses $FLAGS). The flag belongs to `tailscale up`, not `tailscaled`. With FLAGS="--netfilter-mode=nodivert" the daemon appeared to start once but then crashed on restart due to ExecStopPost cleanup corruption.
**Solution:** UNSOLVED. The flag --netfilter-mode=nodivert goes on `tailscale up` (client), not `tailscaled` (daemon). When applied via `tailscale up`, LAN worked but mesh didn't connect (timeout). Root cause: tailscaled modifies iptables/routing at startup before `tailscale up` is called, breaking LAN. ExecStopPost=--cleanup also corrupts state (DNS route for missing interface). Workaround: disable ExecStopPost via systemctl edit. Full fix needs fresh investigation — possibly tailscale set --netfilter-mode=nodivert (persists in state) or userspace networking mode.
**Tags:** `#tailscale` `#networking` `#iptables` `#systemd` `#debugging`
