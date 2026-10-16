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
>
> Node, domain and health path come from `infra/config/values/common.yaml` (`apps.services.*`); when a row and that file disagree, the file wins.

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
| Web (Astro) | Acemagic | VPS | `staging.mlorente.dev` / `mlorente.dev` | `/` |
| API (Go) | Acemagic | VPS | `api.staging.kubelab.live` / `api.kubelab.live` | `/health` |

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
| Gitea | Beelink (on-demand) | Canonical forge for private repositories, organized in orgs (ADR-061, ADR-065). Public code stays on GitHub, which Argo CD reconciles from | `/api/healthz` |
| act_runner | Beelink (on-demand) | Gitea Actions runner, registered as `kubelab-bee-gitea`. A job queues until the Beelink is on; it does not fail | Runner shown online in Gitea admin |
| n8n | Acemagic / VPS | Workflow automation + agent orchestration | `GET /healthz` (node HTTP) |
| Vikunja | K3s (ace1 staging, VPS prod) | The one task board (ADR-066): Deployment on `infra.postgres`, attachments in R2, OIDC against Authelia. `tasks.kubelab.live` | `/api/v1/info` |

## Data

| Service | Node | Purpose | Health Check |
| --- | --- | --- | --- |
| PostgreSQL | K3s (ace1 staging, VPS prod) | Shared relational database (ADR-051) | `pg_isready` (readiness probe) |

## AI / Agent tooling (ADR-068)

| Service | Node | Purpose | Health Check |
| --- | --- | --- | --- |
| Open WebUI | ace2 (on-demand, tailnet only) | Chat over NaN models, OIDC against prod Authelia. `http://ace2.kubelab.internal:3080`, role `agent_stack` | `/health` |

## Not Yet Deployed

| Service | Planned Node | Purpose | When |
| --- | --- | --- | --- |
| GitHub Runner | Beelink | Self-hosted CI runner; exists but idle by default, CI runs on GitHub-hosted runners (ADR-030) | Opt-in through `RUNNER_DOCKER` |
| Vaultwarden | VPS | Password management | Prod deployment |
| Headlamp | Acemagic (K8s pod) | Kubernetes web UI (behind Authelia IngressRoute) | B6 / PROD-K3S-000b |
| OpenClaw | Acemagic / VPS | AI agent execution and isolation | Stream F |
| Knowledge Base (Quartz) | Acemagic / VPS | Read-only Obsidian vault web viewer | Stream G |
| Prometheus | Acemagic / VPS | Metrics scraper + time-series database | Stream D2 |
| Node Exporter | All hosts | Host metrics (CPU, RAM, disk, network) | Stream D2 |
| cAdvisor | Acemagic / VPS | Per-container resource metrics | Stream D2 |

## Endpoints by Environment

| Service | Dev | Staging | Prod |
|---------|-----|---------|------|
| Web | `mlorente.test` | `staging.mlorente.dev` | `mlorente.dev` |
| API | `api.kubelab.test` | `api.staging.kubelab.live` | `api.kubelab.live` |
| Traefik | `traefik.kubelab.test` | `traefik.staging.kubelab.live` | `traefik.kubelab.live` |
| Authelia | `auth.kubelab.test` | `auth.staging.kubelab.live` | `auth.kubelab.live` |
| Grafana | `grafana.kubelab.test` | `grafana.staging.kubelab.live` | `grafana.kubelab.live` |
| Loki | `loki.kubelab.test` | `loki.staging.kubelab.live` | internal only (in-cluster `loki:3100`) |
| Gitea | `gitea.kubelab.test` | — (Beelink serves the one forge, ADR-061) | `gitea.kubelab.live` |
| n8n | `n8n.kubelab.test` | `n8n.staging.kubelab.live` | `n8n.kubelab.live` |
| Uptime Kuma | `status.kubelab.test` | `status.staging.kubelab.live` | `status.kubelab.live` |
| CrowdSec | `crowdsec.kubelab.test` | internal only (ClusterIP, no IngressRoute) | internal only (ClusterIP, no IngressRoute) |
| Vikunja | — | `tasks.staging.kubelab.live` | `tasks.kubelab.live` |
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
