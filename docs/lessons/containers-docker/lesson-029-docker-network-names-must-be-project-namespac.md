---
id: lesson-029-docker-network-names-must-be-project-namespac
type: lesson
status: active
created: "2026-03-15"
owner: manu
category: containers-docker
tags: [kubelab, containers-docker]
---

# Docker network names must be project-namespaced

**Context**: VPS Docker network was named `"proxy"` — copied from a common Traefik tutorial pattern. Homelab used `"kubelab"` (from `network_name` in common.yaml).

**Problem**: Generic name `"proxy"` risks collision with other tools, is not project-namespaced, and is inconsistent across environments. During ADR-020 Ansible migration, the inconsistency caused confusion about which network config was canonical.

**Solution**: Renamed to `"kubelab"` everywhere. The network's purpose (connecting services to Traefik) is implied by architecture, not the name. Rename was done during Ansible rebuild (requires stopping all containers).

**Rule**: Docker network names must be project-namespaced (e.g., `"kubelab"`, not `"proxy"`). Never use generic tutorial names in production. Align naming across all environments via the SSOT config (`common.yaml`).
