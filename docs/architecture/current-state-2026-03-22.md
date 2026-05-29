---
id: current-state-2026-03-22
type: architecture
status: stale
stale_as_of: "2026-05-16"
superseded_by: adr-002-orchestrator-architecture
created: "2026-03-22"
owner: manu
---

# KubeLab — Current Architecture (2026-03-22)

> Snapshot after Phase 2 close + Phase 3 partial (AWS hub + Argo CD).

## Topology

```
┌──────────────────────────────────────────────────────────────┐
│                    MANAGEMENT PLANE                           │
│              AWS eu-central-1 · t4g.micro Spot · ~$3.60/mo   │
│              Node: aws1 (100.64.0.4 via Tailscale)           │
│                                                              │
│              K3s (no Traefik, no ServiceLB)                   │
│              └── Argo CD (5 pods, ~576MB, NodePort 30080)    │
│                                                              │
│              UI: argo.kubelab.live                            │
│              → proxied via VPS prod Traefik (EndpointSlice)  │
│              → protected by Authelia + CrowdSec              │
│              Storage: EBS 8GB (stateless, Git = truth)       │
│              Swap: 2GB (1GB RAM constraint)                  │
└──────────────────────────┬───────────────────────────────────┘
                           │
                    Headscale VPN mesh (vpn.kubelab.live)
                    (Docker Compose on VPS — ADR-015)
                           │
          ┌────────────────┼────────────────┐
          ▼                │                ▼
┌─────────────────────┐    │    ┌─────────────────────┐
│    PROD SPOKE       │    │    │   STAGING SPOKE     │
│  Hetzner VPS        │    │    │  ace1 (homelab)     │
│  162.55.57.175      │    │    │  100.64.0.11        │
│  CAX21 $8.99/mo     │    │    │  12GB bare metal    │
│                     │    │    │                     │
│  K3s v1.34.4+k3s1   │    │    │  K3s v1.34.4+k3s1   │
│  ├── Traefik (80/443)│    │    │  ├── Traefik (80/443)│
│  ├── api, web, errors│    │    │  ├── api, web, errors│
│  ├── Authelia + Redis│    │    │  ├── Authelia + Redis│
│  ├── CrowdSec       │    │    │  ├── CrowdSec       │
│  ├── Gitea, n8n     │    │    │  ├── Gitea, n8n     │
│  ├── Grafana, Loki  │    │    │  ├── Grafana, Loki  │
│  ├── MinIO          │    │    │  ├── MinIO          │
│  └── Vector         │    │    │  └── Vector         │
│                     │    │    │                     │
│  Also hosts:        │    │    │  Powered off when   │
│  └── Headscale      │    │    │  not developing     │
│      (Docker Compose)│    │    │  (Autonomous Spoke)  │
│                     │    │    │                     │
│  Proxies external:  │    │    │  Proxies external:  │
│  ├── argo-hub:30080 │    │    │  └── ollama:11434   │
│  ├── headscale:8080 │    │    │      (Beelink)      │
│  └── uptime-kuma    │    │    │                     │
│      (RPi3:3001)    │    │    │                     │
│                     │    │    │                     │
│  E2E: 58/0/19      │    │    │  E2E: 66/0/11       │
└─────────────────────┘    │    └─────────────────────┘
                           │
┌──────────────────────────┴───────────────────────────────────┐
│                    EDGE / SHARED SERVICES                     │
│                    (no K3s, independent lifecycle)            │
│                                                              │
│  RPi4 (172.16.1.1)     RPi3 (100.64.0.6)                    │
│  ├── Pi-hole            └── Uptime Kuma                      │
│  └── CoreDNS                (external observer)              │
│      (staging DNS)                                           │
│                                                              │
│  Beelink (172.16.1.3)  Jetson (172.16.1.4)                  │
│  └── Ollama 12GB        └── llama.cpp (Pollex)               │
│      (LLM inference)        (edge AI)                        │
│                                                              │
│  ace2 (172.16.1.5) — Ollama bare metal (LLM compute, on-demand) [ADR-028] │
└──────────────────────────────────────────────────────────────┘
```

## Traffic flow

```
Internet → Cloudflare DNS → VPS public IP (162.55.57.175)
  → K3s Traefik (ports 80/443)
    → IngressRoute match:
      ├── mlorente.dev         → web pod
      ├── api.kubelab.live     → api pod
      ├── auth.kubelab.live    → authelia pod
      ├── grafana.kubelab.live → grafana pod (Authelia protected)
      ├── traefik.kubelab.live → kube-system:9000 (Authelia protected)
      ├── argo.kubelab.live    → EndpointSlice 100.64.0.4:30080 (Authelia protected)
      ├── vpn.kubelab.live     → EndpointSlice 162.55.57.175:8080 (Headscale)
      ├── gitea/n8n/minio      → respective pods
      └── kubelab.live         → 301 redirect → mlorente.dev
```

## Costs

| Item | Monthly |
|------|---------|
| Hetzner VPS (CAX21) | $8.99 |
| AWS t4g.micro Spot | ~$3.60 |
| Domains (amortized) | ~$2.00 |
| **Cloud total** | **~$14.59** |
| Homelab electricity | ~€4-5 |

## Key decisions active

- **ADR-015**: Headscale stays in Docker Compose (bootstrap dependency)
- **ADR-020**: IaC lifecycle — Terraform + Ansible + Kustomize
- **ADR-021 Rev2**: Custom apps = Kustomize, third-party = Helm (future H2)
- **ADR-023**: Hub-and-Spoke GitOps — AWS hub, VPS + homelab spokes
- **ADR-024**: PVC backup via CronJob

## Phase 3 remaining

- ARGO-002: Register spokes (staging + prod kubeconfigs)
- ARGO-003: First app syncing (proof of concept)
- ARGO-004: ApplicationSet (all apps, auto-sync staging, manual prod)
- ARGO-005: App of Apps (Argo manages itself)
- ARGO-010: OIDC via Authelia (eliminate double login)
- SEC-ROTATE-001: Rotate all default usernames/passwords
