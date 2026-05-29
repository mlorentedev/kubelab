---
id: "kubelab-architecture-service-catalog"
type: architecture
status: active
tags: [kubelab, reference]
created: "2026-02-08"
owner: manu
---

# KubeLab — Service Catalog

> Inventory of services running on the hybrid platform. Update when adding/removing services.

## Infrastructure

| Service | Node | Purpose | Health Check |
| --- | --- | --- | --- |
| Traefik | VPS / Acemagic | Ingress controller, TLS termination, routing | `/ping` |
| Nginx | VPS / Acemagic | Error pages, caching | `/health` |
| CoreDNS | RPi 4 | DNS resolution for `*.staging.kubelab.live` | dig query |
| Tailscale | All | Mesh VPN (NAT traversal, no port forwarding) | `tailscale ping` |

## Applications (Custom-built)

| Service | Staging Node | Prod Node | Domain | Health Check |
| --- | --- | --- | --- | --- |
| Web (Astro) | Acemagic | VPS | `web.staging.kubelab.live` / `mlorente.dev` | `/` |
| API (Go) | Acemagic | VPS | `api.staging.kubelab.live` / `api.kubelab.live` | `/health` |
| Blog (Jekyll) | Acemagic | VPS | `blog.staging.kubelab.live` / `blog.kubelab.live` | `/` |

## Security

| Service | Node | Purpose | Health Check |
| --- | --- | --- | --- |
| Authelia | Acemagic / VPS | SSO, OIDC provider, 2FA | `/api/health` |
| CrowdSec | Acemagic / VPS | WAF, IP reputation, Traefik bouncer | `/health` |

## Observability

| Service | Node | Purpose | Health Check |
| --- | --- | --- | --- |
| Grafana | Acemagic / VPS | Dashboards and visualization | `/api/health` |
| Loki + Vector | Acemagic / VPS | Log aggregation + shipping | `/ready` |
| Uptime Kuma (internal) | Acemagic / VPS | Status page, uptime monitoring | `/` |
| Uptime Kuma (external) | RPi 4 | External monitoring (outside blast radius) | `:3001` |

## Core Services

| Service | Node | Purpose | Health Check |
| --- | --- | --- | --- |
| Portainer | Acemagic (dev/staging) | Container management UI (Docker Compose; NOT K8s) | `/api/system/status` |
| Gitea | Acemagic / VPS | Git hosting (mirrors) | `/api/healthz` |
| n8n | Acemagic / VPS | Workflow automation + agent orchestration | `GET /healthz` (node HTTP) |

## Data

| Service | Node | Purpose | Health Check |
| --- | --- | --- | --- |
| MinIO | Acemagic / VPS | S3-compatible object storage | `/minio/health/live` |

## Not Yet Deployed

| Service | Planned Node | Purpose | When |
| --- | --- | --- | --- |
| GitHub Runner | Acemagic | Self-hosted CI runner | When CI load grows |
| Ollama + WebUI | Acemagic (homelab) | AI/ML inference + chat UI | Stream B-ai |
| Vaultwarden | VPS | Password management | Prod deployment |
| Headlamp | Acemagic (K8s pod) | Kubernetes web UI (behind Authelia IngressRoute) | B6 / PROD-K3S-000b |
| Vikunja | Acemagic / VPS | Task management (replaces Google Keep) + agent delegation UI | Stream F |
| OpenClaw | Acemagic / VPS | AI agent execution and isolation | Stream F |
| Knowledge Base (Quartz) | Acemagic / VPS | Read-only Obsidian vault web viewer | Stream G |
| Prometheus | Acemagic / VPS | Metrics scraper + time-series database | Stream D2 |
| Node Exporter | All hosts | Host metrics (CPU, RAM, disk, network) | Stream D2 |
| cAdvisor | Acemagic / VPS | Per-container resource metrics | Stream D2 |

## Endpoints by Environment

| Service | Dev | Staging | Prod |
|---------|-----|---------|------|
| Web | `mlorente.test` | `web.staging.kubelab.live` | `mlorente.dev` |
| API | `api.kubelab.test` | `api.staging.kubelab.live` | `api.kubelab.live` |
| Blog | `blog.kubelab.test` (Jekyll) | `blog.staging.kubelab.live` | `blog.kubelab.live` |
| Traefik | `traefik.kubelab.test` | `traefik.staging.kubelab.live` | `traefik.kubelab.live` |
| Authelia | `auth.kubelab.test` | `auth.staging.kubelab.live` | `auth.kubelab.live` |
| Grafana | `grafana.kubelab.test` | `grafana.staging.kubelab.live` | `grafana.kubelab.live` |
| Loki | `loki.kubelab.test` | `loki.staging.kubelab.live` | `loki.kubelab.live` |
| Portainer | `portainer.kubelab.test` | `portainer.staging.kubelab.live` | — |
| Gitea | `gitea.kubelab.test` | `gitea.staging.kubelab.live` | `gitea.kubelab.live` |
| n8n | `n8n.kubelab.test` | `n8n.staging.kubelab.live` | `n8n.kubelab.live` |
| MinIO | `minio.kubelab.test` | `minio.staging.kubelab.live` | `minio.kubelab.live` |
| MinIO Console | `console.minio.kubelab.test` | `console.minio.staging.kubelab.live` | `console.minio.kubelab.live` |
| Uptime Kuma | `status.kubelab.test` | `status.staging.kubelab.live` | `status.kubelab.live` |
| CrowdSec | `crowdsec.kubelab.test` | `crowdsec.staging.kubelab.live` | `crowdsec.kubelab.live` |
| Headscale | — | — | `vpn.kubelab.live` |

## Summary

| Metric | Count |
| --- | --- |
| Total documented services | 23 |
| Staging services (Acemagic) | 13 |
| Edge services (RPi 4) | 3 |
| Production services (VPS) | Pending A5 |

## Related

- _index — KubeLab overview
-  — Hardware inventory and topology
- [deployment](../troubleshooting/deployment.md) — Deployment procedures
- Troubleshooting — Service-specific troubleshooting
