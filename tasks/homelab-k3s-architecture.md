# ADR: Homelab K3s Migration Strategy

**Date**: 2026-02-18
**Status**: Proposed
**Supersedes**: Lesson "staging == prod en arquitectura" (2026-02-09)

## Context

The current CubeLab architecture uses Docker Compose for both staging (Acemagic) and production (Hetzner VPS). A strategic decision has been made to migrate to Kubernetes (K3s) to build SRE/Infrastructure skills and enable future production migration.

This ADR explicitly acknowledges a temporary violation of the principle "staging == prod in architecture" as a deliberate transition phase with a defined end state.

## Decision

### Phase 1: Homelab K3s (Current → 3 months)

Migrate staging from Docker Compose on Acemagic to K3s on Proxmox.

#### Hardware Allocation (REVISED)

```
┌─────────────────────┬───────────────────────────────────────────┐
│  VPS Hetzner        │ Production (unchanged)                    │
│  162.55.57.175      │ Docker Compose → Traefik + Apps + Services│
├─────────────────────┼───────────────────────────────────────────┤
│  Acemagic 12GB      │ Proxmox VE 8.x + K3s cluster             │
│  cubelab-staging    │ 3 VMs: 1 server (3.5GB) + 2 agents (3.5GB)│
│                     │ Staging environment for all CubeLab apps  │
│                     │ ArgoCD for GitOps                         │
├─────────────────────┼───────────────────────────────────────────┤
│  Beelink 8GB        │ Ollama bare metal                         │
│  cubelab-ai         │ Debian 12 + Ollama (llama.cpp)            │
│                     │ Accessible from K3s cluster via LAN       │
│                     │ Endpoint: http://<beelink-ip>:11434       │
├─────────────────────┼───────────────────────────────────────────┤
│  RPi 4 (8GB)        │ Network gateway (unchanged)               │
│  cubelab-edge       │ Bridge/NAT, Pi-hole, CoreDNS, Tailscale   │
├─────────────────────┼───────────────────────────────────────────┤
│  RPi 3 (1GB)        │ External monitor (unchanged)              │
│  cubelab-monitor    │ Uptime Kuma                                │
├─────────────────────┼───────────────────────────────────────────┤
│  Jetson Nano #1     │ Pollex (unchanged)                        │
│  cubelab-ai-gpu     │ GPU inference, Qwen 2.5                   │
└─────────────────────┴───────────────────────────────────────────┘
```

**Key change**: Acemagic (12GB) gets Proxmox + K3s instead of Beelink (8GB). 12GB allows 3 VMs of 3.5GB each with ~1GB for Proxmox overhead. Beelink (8GB) is dedicated to Ollama, which benefits from maximum available RAM for model loading.

#### Deployment Flow

```
git push develop → ArgoCD syncs → K3s cluster (Acemagic/Proxmox)
                                   ↓ validates
git merge to master → GitHub Actions CI/CD → Hetzner VPS (Docker Compose)
```

#### Ollama Integration (Staging)

Ollama runs on Beelink bare metal, outside the K3s cluster. Apps in K3s access it as an external service via LAN:

```yaml
# ExternalName service or ConfigMap with endpoint
apiVersion: v1
kind: Service
metadata:
  name: ollama
  namespace: cubelab
spec:
  type: ExternalName
  externalName: <beelink-tailscale-ip>
---
# Or simply as env var in deployments
env:
  - name: OLLAMA_ENDPOINT
    value: "http://<beelink-ip>:11434"
```

### Phase 2: Production K3s Migration (3-6 months)

Once K3s manifests are stable and GitOps is proven:

1. Install K3s single-node on Hetzner VPS
2. Deploy same manifests via ArgoCD
3. Validate all apps working
4. Cut DNS to new deployment
5. Remove Docker Compose from production

At this point, staging == prod in architecture again.

### Phase 3: Scale if Needed (future, no timeline)

If traffic grows:

```bash
# Add a node to production cluster
curl -sfL https://get.k3s.io | K3S_URL=https://vps:6443 K3S_TOKEN=<token> sh -
```

If production needs LLM inference:
- Evaluate API (OpenAI/Anthropic) vs GPU VPS cost
- API almost certainly wins for personal project volumes
- If self-hosted needed: add VPS with GPU, label node, use nodeSelector

## K3s Stack

| Component | Tool | Purpose |
|-----------|------|---------|
| Distribution | K3s | Lightweight Kubernetes |
| GitOps | ArgoCD | Continuous deployment from git |
| Ingress | Traefik | Already known, ships with K3s |
| Observability | Prometheus + Grafana + Loki | Metrics, dashboards, logs |
| Secrets | SOPS + age (existing) | Encrypted secrets in git |
| Storage | Local-path (K3s default) | Single-node, no distributed storage needed |

## Migration Path: Docker Compose → K3s Manifests

The existing Docker Compose files are the direct input:

| Compose Concept | K8s Equivalent |
|----------------|----------------|
| `services` | Deployment + Service |
| `ports` | Service (ClusterIP/NodePort) |
| `volumes` | PersistentVolumeClaim |
| `environment` | ConfigMap / Secret |
| `labels` (Traefik) | Ingress resource |
| `depends_on` | Not needed (apps must handle startup order) |
| `networks` | Namespace + NetworkPolicy |
| `restart: unless-stopped` | `restartPolicy: Always` (default) |
| `compose.base.yml` + `compose.{env}.yml` | Kustomize overlays or Helm values |

## SRE Learning Objectives

With Proxmox + 3-node K3s:

1. **Node failure simulation**: Stop a VM, observe pod rescheduling
2. **Rolling updates**: Deploy new versions with zero downtime
3. **Resource management**: Set requests/limits, observe OOMKills
4. **Network policies**: Isolate namespaces, debug connectivity
5. **etcd recovery**: Backup and restore cluster state
6. **HPA**: Horizontal Pod Autoscaler with resource metrics
7. **Chaos engineering**: Kill pods, corrupt PVs, document recovery
8. **Upgrades**: K3s version upgrades with VM snapshots as safety net

## What Does NOT Change

- RPi 4 remains network gateway (Pi-hole, CoreDNS, Tailscale)
- RPi 3 remains external monitor (Uptime Kuma)
- Jetson Nano remains Pollex AI inference
- VPS remains production until Phase 2
- Domain strategy unchanged (mlorente.dev + cubelab.cloud)
- SOPS secrets management unchanged
- CI/CD via GitHub Actions unchanged (ArgoCD is additive)

## Risks

| Risk | Mitigation |
|------|------------|
| Staging/prod divergence during transition | Time-boxed to 3 months, then converge |
| K3s cluster instability blocks staging | Proxmox snapshots for quick recovery |
| Overengineering the K3s setup | Start with single namespace, plain manifests, add complexity only when needed |
| Never completing Phase 2 | Set calendar reminder at 3 months to evaluate |

## Consequences

- The lesson "staging == prod en arquitectura" is temporarily suspended with an explicit convergence plan
- Docker Compose knowledge is preserved as input for K8s manifests
- Ansible roles for staging need rewriting for K3s provisioning
- Stream B in todo.md needs updating to reflect new hardware allocation
