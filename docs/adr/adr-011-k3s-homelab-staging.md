---
id: "kubelab-adr-011-k3s-homelab-staging"
type: adr
status: accepted
tags: [adr, kubelab]
created: "2026-02-18"
owner: manu
---

# ADR-011: K3s on Homelab Staging + VPS Migration Strategy

## Status

Accepted (2026-02-18)

## Context

The original homelab architecture used Docker Compose on Acemagic (staging) mirroring Docker Compose on the VPS (production). This worked for the initial stabilization (Stream A) but has limitations:

1. **No container orchestration skills**: Docker Compose doesn't expose Kubernetes concepts (Deployments, Services, Ingress, ConfigMaps, PersistentVolumes). These are table stakes for SRE/DevOps roles in 2026.
2. **No cluster skills**: Pod scheduling, resource limits, health checks, rolling updates, namespaces — all invisible in Compose.
3. **Portfolio signal**: Kubernetes manifests in a public repo signals production-level infrastructure knowledge. Docker Compose alone doesn't.
4. **New hardware enables it**: Two 12GB Acemagic MiniPCs (both available for homelab) make a real multi-node K3s cluster feasible without sacrificing staging parity.
5. **VPS is K3s-capable**: Hetzner CAX21 (ARM64, 8GB RAM) has enough headroom for K3s single-node with all platform services (~500MB for K3s itself, ~5-6GB for pods).

## Decision

### Homelab: K3s multi-node cluster

Both Acemagic MiniPCs run Proxmox VE 8.x. K3s runs inside VMs for snapshot-based recovery:

| Node | Host | VM | RAM | Role |
|------|------|----|-----|------|
| k3s-server | kubelab-ace1 (Proxmox) | k3s-server VM | 5GB | Control plane |
| k3s-agent-1 | kubelab-ace1 (Proxmox) | k3s-agent-1 VM | 5GB | Worker (app workloads) |
| k3s-agent-2 | kubelab-ace2 (Proxmox) | k3s-agent-2 VM | 10GB | Worker (observability, data) |

Proxmox rationale: VMs give snapshot/rollback capability — production-like incident recovery drills. Not bare metal because the recovery skill is more valuable than the marginal ~1GB RAM saved.

### VPS: Docker Compose first, K3s later

VPS starts with Docker Compose (A5 validation). Migrates to K3s single-node in B6, after homelab K3s is validated and stable for ≥1 week. This sequencing ensures:
- A5 (prod validation) is not blocked by K3s cluster readiness
- K3s skills are proven on homelab before touching production

### Beelink: Ollama bare metal (external to cluster)

Beelink runs Ollama directly on Debian 12 — not inside K3s. It's exposed to the cluster as an `ExternalName` service or ConfigMap endpoint. This keeps Ollama always-on regardless of cluster state, avoids GPU passthrough complexity, and provides the same OpenAI-compatible API for agents and pods alike.

### Deploy method: kubectl apply (ArgoCD deferred)

Initial K3s deploys use `kubectl apply -k overlays/{staging|prod}/` (Kustomize, built into kubectl). ArgoCD is deferred to Stream E — learn raw cluster operations before adding GitOps abstraction.

### Manifests: Kustomize overlays

```
infra/k8s/
├── base/                  # Common manifests (Deployments, Services, ConfigMaps)
└── overlays/
    ├── staging/           # 1 replica, staging domains, low resource limits
    └── prod/              # prod domains, real limits, HTTPS
```

Docker Compose files in `infra/stacks/` are preserved for local dev only.

## Rationale

### Why not bare metal K3s on Acemagic

Proxmox + VMs costs ~1GB RAM per host but buys:
- Snapshot before risky operations (K3s upgrades, config changes)
- VM suspension when not needed (lab scenario drills)
- Practice with production-realistic hypervisor operations (Proxmox is used in industry)

The learning value of Proxmox snapshots outweighs the RAM cost.

### Why not K3s on VPS immediately

- A5 (prod validation) must prove the stack works on the VPS. If VPS is mid-K3s-migration, A5 is blocked.
- K3s on staging must be validated first (≥1 week soak) before production migration.
- Docker Compose on VPS is the fallback if K3s migration fails (B6 preserves Compose files).

### Cloud portability

K3s manifests are directly portable to AWS EKS, GCP GKE, and Azure AKS:
- Same `kubectl` CLI
- Same Kustomize overlays (just change domain/TLS annotations)
- Same Helm charts (if used later)

This architecture directly demonstrates cloud-portable Kubernetes skills in the portfolio.

## Consequences

1. **Stream B rewritten**: B3 (K3s cluster), B4 (manifests), B5 (staging validation), B6 (prod migration)
2. **ArgoCD deferred to Stream E**: Not in the critical path for B5 or B6
3. **Beelink role changed**: Proxmox lab → Ollama bare metal
4. **Both Acemagics run Proxmox**: Not Ubuntu bare metal
5. **VPS user**: `deploy` (not `kubelab`) for CI/CD; `manu` on all homelab nodes
6. **ADR references**: [adr-010-headscale-over-tailscale-cloud](adr-010-headscale-over-tailscale-cloud.md) for VPN topology

## Related

- [adr-006-tailscale-over-wireguard](adr-006-tailscale-over-wireguard.md) — VPN decision (now Headscale per ADR-010)
- [adr-010-headscale-over-tailscale-cloud](adr-010-headscale-over-tailscale-cloud.md) — VPN control plane decision
-  — Hardware inventory and topology
- [hardware-setup](../runbooks/hardware-setup.md) — B0 provisioning runbook
