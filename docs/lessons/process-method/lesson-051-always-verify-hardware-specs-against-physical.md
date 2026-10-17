---
id: lesson-051-always-verify-hardware-specs-against-physical
type: lesson
status: active
created: "2026-02-10"
owner: manu
category: process-method
tags: [kubelab, process-method]
---

# Always Verify Hardware Specs Against Physical Devices

**Context**: Planning the homelab architecture (Stream B) using documented hardware specifications.

**Problem**: Documented specs were incorrect: 16GB for staging (actual: 12GB Acemagic), 4GB for RPi 4 (actual: 8GB). Additionally, devices were missing: RPi 3 with Pi-hole, Beelink with Proxmox. All planning was based on wrong data.

**Solution**: Physically verify each device (`free -h`, `lsblk`, model labels) before documenting or planning. Update all documentation (vault, todo.md, Ansible templates) with actual specs.

**Rule**: Before planning infrastructure, ALWAYS verify hardware specs against physical devices. Documents lie; `free -h` doesn't. A plan based on incorrect specs is worse than no plan.
