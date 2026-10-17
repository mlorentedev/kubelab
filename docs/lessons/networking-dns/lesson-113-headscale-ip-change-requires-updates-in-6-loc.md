---
id: lesson-113-headscale-ip-change-requires-updates-in-6-loc
type: lesson
status: active
created: "2026-03-14"
owner: manu
category: networking-dns
tags: [kubelab, networking-dns]
---

# Headscale IP change requires updates in 6+ locations

**Context:** RPi4 reflash caused Headscale to assign new IP (100.64.0.10, was 100.64.0.5). Required updating references in 6 files + VPS config + SSH config.

**Files updated:**
- `infra/config/values/common.yaml` (networking.nodes.rpi4.tailscale_ip)
- `infra/ansible/inventories/homelab.yml` (ansible_host)
- `infra/stacks/services/core/headscale/config/config.yaml` (split DNS)
- `Makefile` (RPI4_HOST)
- VPS `/opt/headscale/config/config.yaml` (split DNS, applied manually)
- `~/.ssh/config` on workstation (alias rpi4)
- MEMORY.md (network reference)

**Files NOT updated (content, historical):**
- Blog notes (.mdx files referencing old IP in examples)

**Rule:** When a Headscale node changes IP, grep for the old IP across the entire repo (`grep -r "100.64.0.OLD"`). Also update VPS config and workstation SSH config manually.
