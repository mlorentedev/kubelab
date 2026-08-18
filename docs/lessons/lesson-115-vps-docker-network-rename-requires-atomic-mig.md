---
id: lesson-115-vps-docker-network-rename-requires-atomic-mig
type: lesson
status: active
created: "2026-03-15"
owner: manu
tags: [kubelab, lesson, docker, networking, ansible, vps, outage]
---

# VPS Docker network rename requires atomic migration

**Context:** ADR-020 Phase 2 — deploying Headscale via Ansible with docker_network=kubelab (renamed from proxy)
**Problem:** Changing docker_network from 'proxy' to 'kubelab' in common.yaml broke Headscale connectivity. Traefik and 10 other VPS containers remain on 'proxy' network. Headscale recreated on 'kubelab' network couldn't communicate with Traefik — vpn.kubelab.live went down.
**Solution:** Reverted common.yaml to docker_network: proxy. Network rename deferred to Phase 2b (traefik_vps role) which will migrate ALL VPS containers atomically. Rule: never rename a shared Docker network piecemeal — all consumers must move together.
**Tags:** `#docker` `#networking` `#ansible` `#vps` `#outage`
