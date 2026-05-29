---
id: adr-028-operational-topology
type: adr
status: active
owner: manu
created: "2026-03-28"
---

# ADR-028: Operational Topology — Always-On vs On-Demand Service Placement

## Status

Accepted (2026-03-28). Refines ADR-023 (Hub-and-Spoke), ADR-027 (Intelligence Layer).

## Date

2026-03-28

## Context

ADR-023 defined four architectural planes (Management, Data, Platform, Edge) based on functional role. ADR-027 added intelligence layer services and hardware reallocation. However, neither addressed the operational reality of a homelab:

1. **Not all nodes are 24/7.** Cloud nodes (VPS, AWS) are always-on. Homelab nodes are on-demand — the operator turns them on when working, off when traveling or sleeping.
2. **Service placement must match availability requirements.** A public-facing widget ("Chat with Manu") can't depend on a homelab node. CI can tolerate homelab being off (GitHub-hosted fallback).
3. **Observability belongs where it matters.** Grafana monitoring staging from staging is circular — if staging dies, you lose the monitor AND the monitored. Observability should run on prod (always-on).
4. **ADR-023's "Platform Plane" assumed always-on.** Putting Gitea, Grafana, and Alertmanager on Beelink (homelab) would require 24/7 operation — an operational burden that doesn't match the homelab model.

### Design principle

**"Would I need this service to diagnose and recover from a failure, even at 3 AM?"**
- YES → always-on node (VPS prod, AWS, RPi3)
- NO → on-demand node (homelab)

This replaces the rigid "control plane vs data plane" taxonomy with an availability-first placement model.

## Decision

### 1. Two operational tiers replace four planes

| Tier | Nodes | Power | Purpose |
|------|-------|-------|---------|
| **Always-on** | VPS (8GB ARM), AWS t4g.micro, RPi3 (1GB) | 24/7 cloud + low-power | Production workloads, observability, GitOps, external monitoring |
| **On-demand** | ace1 (12GB), Beelink (8GB), ace2 (12GB), RPi4 (8GB), Jetson (4GB) | Homelab, powered when working | Staging validation, CI, AI/LLM, local development |

### 2. Service placement

#### Always-on tier

**VPS prod K3s (Hetzner CAX21, 8GB ARM):**
- Ingress: Traefik, Authelia, CrowdSec
- Apps: api, web, errors
- Data: PostgreSQL 16 + pgvector, Redis
- Observability: Grafana, Prometheus, Loki, Vector, Alertmanager
- Platform: Gitea (ArgoCD source, GitHub mirror), n8n
- Embedding pipeline: Ollama lightweight (nomic-embed-text ~300MB, CPU-only) or OpenRouter embeddings API
- Future: cert-manager

**AWS t4g.micro (Spot, ~$3.60/mo):**
- ArgoCD hub (source: Gitea on VPS via Tailscale)

**RPi3 (1GB, ~5W):**
- Uptime Kuma (external health monitoring of prod services)

#### On-demand tier

**ace1 (12GB x86) — Staging K3s spoke:**
- Mirror of prod manifests (ArgoCD-synced)
- Validate Traefik configs, manifests, OIDC flows before prod
- Ephemeral — no persistent data that matters

**Beelink (8GB x86) — CI + Storage + AI orchestration:**
- GitHub Actions self-hosted runner + QEMU/buildx (multi-arch CI)
- MinIO (backup target, CI artifact cache, Loki chunks)
- OpenClaw (AI assistant for operations)
- Glances (node metrics)

**ace2 (12GB x86) — LLM compute:**
- Ollama (Mistral Nemo 12B Q4, ~7GB)
- Glances (node metrics)

**RPi4 (8GB ARM) — Staging network gateway:**
- CoreDNS (staging DNS resolution)
- Pi-hole (DNS filtering)
- Tailscale subnet routing (172.16.1.0/24 for remote LAN access)
- Only needed when staging or on-demand nodes are active

**Jetson Nano (4GB ARM):**
- Pollex (independent project, own repo)

### 3. Intelligence layer placement (refines ADR-027)

| Component | Availability | Node | LLM backend |
|-----------|-------------|------|-------------|
| "Chat with Manu" (public widget) | 24/7 | VPS (Go API + pgvector) | OpenRouter (cloud, always available) |
| Embedding pipeline | 24/7 | VPS (Ollama nomic-embed-text or OpenRouter API) | CPU-only, ~300MB model |
| pgvector storage | 24/7 | VPS (PostgreSQL) | N/A |
| OpenClaw (AI assistant) | On-demand | Beelink | Ollama on ace2 (Tailscale) |
| Ollama chat models | On-demand | ace2 | Mistral Nemo 12B Q4 (local, free) |
| LLM gateway (`/v1/llm/*`) | 24/7 endpoint, on-demand backend | VPS API proxies to ace2 | Returns "unavailable" when ace2 off |
| n8n intelligence workflows | 24/7 trigger, on-demand execution | VPS (n8n) | Ollama ace2 if on, OpenRouter fallback |

**Embedding pipeline execution model:**
- Trigger: Gitea webhook on vault push → n8n workflow → `toolkit embeddings sync`
- Embedding model: `nomic-embed-text` (~274MB) runs on VPS CPU. No dependency on homelab.
- Alternative: OpenRouter embeddings API (~$0.00002/1K tokens, effectively free)
- No OpenFaaS/Lambda — overkill at single-operator scale. Toolkit CLI + n8n webhook is sufficient.

### 4. CI integration (GH Runner)

The self-hosted runner on Beelink builds Docker images (amd64 native + arm64 via QEMU).

**CI workflow changes:**
- `ci-publish.yml`: add `runs-on: [self-hosted, linux, docker]` for Docker build jobs
- Fallback: if self-hosted runner is offline, CI queues until Beelink is on. For urgent hotfixes, manually trigger with GitHub-hosted runner override.
- QEMU + buildx pre-installed on Beelink (migrated from ace2 `minipc2_services` role)

### 5. Gitea as ArgoCD source

Moving Gitea to VPS prod enables:
- ArgoCD (AWS) pulls from Gitea (VPS) — both always-on, no homelab dependency
- GitHub remains the public mirror and collaboration platform
- Gitea is the authoritative GitOps source (push to GitHub → Gitea mirror → ArgoCD sync)
- Bootstrap independence: ArgoCD can sync even if GitHub has an outage

### 6. RPi4 reclassified as on-demand

RPi4 only serves staging DNS (CoreDNS + Pi-hole) and LAN subnet routing. Prod DNS is Cloudflare (public). When staging is off, RPi4 can be off.

**Impact:** Remote access to LAN IPs (172.16.1.x) requires RPi4 for subnet routing. Tailscale direct IPs (100.64.0.x) always work regardless. K8s EndpointSlices use LAN IPs — only relevant when staging K3s is running.

## Consequences

### Positive

- Homelab can be fully powered off without affecting production or public services
- Observability on prod (not staging) follows enterprise pattern
- "Chat with Manu" works 24/7 without homelab dependency
- Embedding pipeline autonomous on VPS — vault updates indexed regardless of homelab state
- CI has self-hosted runner for speed + GitHub-hosted fallback for availability
- Clear mental model: "always-on = cloud/critical, on-demand = homelab/development"
- Electricity savings: homelab off during nights/travel (~15-20W × 4 nodes)

### Negative

- VPS prod absorbs more services (~1.2GB additional RAM for Grafana + Loki + Prometheus + Gitea)
- Gitea migration from K3s staging to VPS prod is a non-trivial operation
- Self-hosted CI runner unavailable during homelab off hours (acceptable — GitHub fallback)

### Risks

- VPS 8GB RAM budget: prod apps + observability + Gitea + PostgreSQL. Monitor with Uptime Kuma. Mitigation: Hetzner CAX31 (16GB, ~$16/mo) if needed.
- Gitea as single ArgoCD source: if VPS dies, ArgoCD can't sync. Mitigation: GitHub as secondary source in ArgoCD.
- Ollama lightweight on VPS for embeddings: ARM64 compatibility for nomic-embed-text needs validation. Fallback: OpenRouter API.

## Implementation

### Migration order (iterative, each step verifiable)

1. **ANSIBLE-013 v1**: Provision Beelink (Docker, Tailscale, MinIO, GH Runner, Glances)
2. **CI integration**: Update `ci-publish.yml` for self-hosted runner
3. **IDP-024**: Rewrite `provision-ace2.yml` (Ollama + Glances, remove MinIO/Runner)
4. **Update manifests**: Ollama EndpointSlice IP → ace2, common.yaml ansible_groups
5. **VPS expansion**: Deploy Gitea on VPS prod K3s (Helm chart)
6. **VPS expansion**: Deploy observability stack (Grafana + Prometheus + Loki) on VPS prod
7. **ArgoCD source swap**: Gitea on VPS as primary, GitHub as mirror
8. **Embedding pipeline**: Ollama nomic-embed-text on VPS + pgvector + n8n webhook

Tasks tracked in `11-tasks.md` Stream IDP and Stream B.
