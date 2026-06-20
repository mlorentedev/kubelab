---
id: "adr-023-hub-spoke-multicloud-gitops"
type: adr
status: accepted
date: "2026-03-16"
tags: [architecture, gitops, multi-cloud, multi-cluster, argocd]
created: "2026-03-16"
owner: manu
---

# ADR-023: Hub-and-Spoke Multi-Cloud GitOps Architecture

## Status

Accepted (2026-03-16). Extends ADR-020 (IaC Lifecycle), ADR-021 (Helm Packaging). Absorbs Stream E (GitOps), parts of Stream D (Observability), Stream R (Backup), VER-008 (CI optimization).

> **Refined by [ADR-029](adr-029-intelligence-layer.md)** (2026-03-28): ace2 repurposed from Platform Node to Ollama bare metal. kubelab-gateway and kubelab-memory absorbed.
> **Refined by [ADR-028](adr-028-operational-topology.md)** (2026-03-28): Topology redefined as always-on vs on-demand. VPS prod absorbs observability + Gitea + PostgreSQL. Beelink replaces ace2 as Platform Node (on-demand). RPi4 reclassified on-demand.
> **Backup leg superseded by [ADR-049](adr-049-edge-object-storage-placement-doctrine.md)** (2026-06-19): the "MinIO → Backblaze B2" 3-2-1 off-site leg is retired; `tier-offsite` = Hetzner Storage Box + Borg (bulk) + Cloudflare R2 (critical subset, zero-egress).

## Date

2026-03-16

## Context

KubeLab infrastructure has matured through several phases: VPS stabilization (Stream A ✓), K3s homelab staging (Stream B ✓), IaC lifecycle (ADR-020 Phases 1-2b ✓), and Helm packaging (ADR-021 H1 ✓). The remaining gaps form a coherent architectural evolution:

1. **No GitOps**: Deployments are push-based (`helm upgrade`, `kubectl apply`). No reconciliation loop, no drift detection, no automated promotion between environments.
2. **Prod is Docker Compose**: VPS still runs Docker Compose (ADR-020 Phase 3 pending). Argo CD requires K3s to manage prod as a spoke.
3. **No multi-cluster management**: Staging (homelab K3s) and prod (VPS) are operationally isolated. No shared tooling, no promotion pipeline, no centralized visibility.
4. **Single cloud provider**: All cloud infrastructure on Hetzner. No multi-cloud capability.
5. **Incomplete observability**: Prometheus + Grafana on staging. Missing: centralized dashboards, log aggregation pipeline, alerting.
6. **No K8s-aware backup strategy**: Hetzner server backup (active, $1.40/mo) covers VPS. No Velero, no offsite, no DR drill.
7. **CI bottleneck**: GitHub-hosted runners. Docker builds slow, rate-limited, no local cache.
8. **Hardware underutilization**: MiniPC2 (12GB Proxmox) runs a single K3s agent VM. MiniPC1 runs server + agent VMs — overkill for staging.

These gaps are addressed by 6+ scattered roadmap streams. This ADR consolidates them into one coherent architecture.

### Options evaluated

| Option | Description | Fit |
|--------|-------------|-----|
| A: Incremental (no AWS) | Argo CD on staging only, no new cloud | Misses multi-cloud, doesn't solve prod |
| **B: Hub-and-Spoke, AWS control plane** | **Argo CD on AWS, manages VPS + homelab** | **Multi-cloud, multi-cluster, clean separation** |
| C: Argo CD on VPS alongside prod | No new cloud provider | No multi-cloud, control plane failure = prod failure |

## Decision

### 1. Four architectural planes

```
MANAGEMENT PLANE (AWS eu-central-1)
  └── Argo CD: sync all spokes from Git

DATA PLANE (Hetzner VPS + Homelab MiniPC1)
  ├── Prod spoke: K3s on VPS
  └── Staging spoke: K3s on MiniPC1 (mirror of prod)

PLATFORM PLANE (Homelab MiniPC2)
  ├── MinIO: unified object storage (backups, logs, artifacts)
  └── GitHub Actions Runner: self-hosted CI

EDGE / SHARED SERVICES (RPi4, RPi3, Beelink, Jetson)
  └── Independent lifecycle, no K3s
```

### 2. Target topology

```
┌──────────────────────────────────────────────────────────┐
│                    MANAGEMENT PLANE                       │
│              AWS · t4g.micro Spot · ~$3.60/mo             │
│                                                          │
│              K3s stateless (Git = source of truth)        │
│              ├── Argo CD (non-HA, tuned)                 │
│              ├── Image Updater                           │
│              └── Notifications                           │
│              Storage: EBS 8GB (OS only, zero app data)   │
└──────────────────────────┬───────────────────────────────┘
                           │
                    Headscale VPN mesh
                           │
          ┌────────────────┼────────────────┐
          ▼ sync           │                ▼ sync
┌─────────────────────┐    │    ┌─────────────────────┐
│    PROD SPOKE       │    │    │   STAGING SPOKE     │
│  Hetzner VPS · ~9$  │    │    │  MiniPC1 · 12GB     │
│                     │    │    │                     │
│  K3s single node    │    │    │  K3s all-in-one     │
│  ├── Traefik        │    │    │  = mirror de prod   │
│  ├── cert-manager   │    │    │                     │
│  ├── api/web/errors │    │    │  Prometheus         │
│  │                  │    │    │   └► remote_write    │
│  │  OBSERVABILITY   │    │    │     to prod Grafana  │
│  │  ├── Prometheus  │    │    │                     │
│  │  ├── Grafana ◄───┼────┼────┤  Storage:           │
│  │  ├── Loki        │    │    │  local-path          │
│  │  └── Alertmanager│    │    │  (ephemeral)         │
│  │                  │    │    │                     │
│  │  Storage:        │    │    └─────────────────────┘
│  │  Local SSD 80GB  │    │
│  │  (CAX21)         │    │
│  │                  │    │
│  └── Velero ────────┼────┼──────────┐
└─────────────────────┘    │          │
                           │          ▼
              ┌────────────┴──────────────────────┐
              │       PLATFORM NODE                │
              │    MiniPC2 · 12GB · Ubuntu Server   │
              │                                    │
              │  ├── MinIO (S3-compatible)          │
              │  │   ├── Bucket: velero-backups     │
              │  │   ├── Bucket: loki-chunks        │
              │  │   ├── Bucket: artifacts          │
              │  │   └──► replica to Backblaze B2   │
              │  │                                  │
              │  └── GitHub Actions Runner          │
              │      ├── Docker builds              │
              │      └── Layer cache                │
              └───────────────────────────────────┘

┌─────────────────────────────────────────────────┐
│              EDGE / SHARED SERVICES              │
│              (sin K3s, independent lifecycle)     │
│                                                  │
│  RPi4          RPi3           Beelink   Jetson   │
│  Pi-hole       Uptime Kuma   Ollama    llama.cpp │
│  CoreDNS       (external      12GB      edge AI  │
│  (DNS GW)       observer)    (shared)            │
│                                                  │
│  Headscale VPN Hub                               │
│  (Docker Compose on VPS, bootstrap dependency)   │
└─────────────────────────────────────────────────┘
```

### 3. Key architectural decisions

#### 3.1 AWS for control plane

- **Why AWS**: Multi-cloud on CV (3 providers: AWS + Hetzner + on-prem). Cost is ~$3.60/mo (no Elastic IP — VPN-only access).
- **Why t4g.micro**: 1GB RAM is tight but sufficient for non-HA Argo CD managing 2 spokes with <15 apps. Upgrade to t4g.small ($5 more/mo) when needed — one line in Terraform.
- **Why Spot**: Argo CD down = no new deploys. Existing pods keep running (Autonomous Spoke pattern). Spot interruption (~5-15 min/month) is acceptable. Argo CD reconciles automatically on restart.
- **Stateless**: K3s with SQLite. Git is the source of truth. Instance dies → Terraform apply → cloud-init → K3s → Argo CD resyncs. Zero data loss, ~10 min RTO.

#### 3.2 Headscale stays on VPS

Not an anti-pattern — separation of failure domains:
- Headscale down = VPN mesh down = cross-cluster connectivity lost
- Argo CD down = no deploys, pods keep running
- VPS has Hetzner 99.9% SLA, not Spot. Headscale needs stability.
- If VPS dies, prod dies anyway — VPN being down adds zero incremental impact.
- ADR-015 bootstrap dependency: K3s nodes need Tailscale → Tailscale needs Headscale → Headscale must exist before K3s.

A separate Hetzner node for Headscale was evaluated and rejected: the only scenario where it helps (VPS down but staging still connected) doesn't justify the operational overhead of managing another server.

#### 3.3 Staging = mirror of prod

No dev/sandbox spoke. Staging is the safe environment to test and break things. A third "dev" environment was evaluated and rejected:
- What would dev K3s test that staging doesn't? Nothing — staging has no SLA.
- A third environment = third set of manifests to maintain.
- Staging ephemeral by design: if broken, reinstall K3s + Argo CD reapplies from Git in 5 minutes.

#### 3.4 Proxmox removed from both MiniPCs

Both transition to bare-metal Ubuntu Server 24.04:
- **MiniPC1**: Was Proxmox with server VM + agent VM. Now: K3s all-in-one, all 12GB available.
- **MiniPC2**: Was Proxmox with agent VM. Now: Docker Compose (MinIO + Runner), all 12GB available.
- Proxmox overhead: ~1.5GB RAM, ~5-10% CPU, slower I/O. On 12GB machines, every GB matters.
- Single purpose per node → no need for multi-VM isolation.
- Ansible provisions both identically: consistent operational model.

#### 3.5 Shared services outside K3s

Each has a specific reason to be independent:

| Service | Reason outside K3s |
|---------|-------------------|
| RPi4 (Pi-hole + CoreDNS) | Bootstrap dependency — K3s needs DNS to resolve. DNS inside K3s = circular dependency. |
| RPi3 (Uptime Kuma) | Observer independence — monitors K3s from outside. Inside K3s, it can't detect K3s failures. |
| Beelink (Ollama) | Shared inference consumed by both clusters via ExternalName. Bare-metal GPU access. |
| Jetson (llama.cpp) | Edge device, single workload. K3s is overhead. |

Pattern: **services that K3s depends on, or that monitor K3s, MUST live outside K3s.**

#### 3.6 RPi4 is a conscious SPOF

RPi4 (Pi-hole + CoreDNS) is a Single Point of Failure for staging DNS resolution. This is a deliberate trade-off:

**If RPi4 dies:**
- `*.staging.kubelab.live` resolution fails from VPN clients
- Home network ad-blocking (Pi-hole) stops
- Prod `*.kubelab.live` is UNAFFECTED (resolves via Cloudflare public DNS — never touches RPi4)
- K3s internal DNS (cluster CoreDNS for pod-to-pod) is UNAFFECTED
- VPS, AWS, all cloud services UNAFFECTED

**Mitigation:** Headscale DNS fallback to public resolver:
```yaml
# Headscale config.yaml
dns:
  nameservers:
    - 100.64.0.10    # RPi4 (primary — split DNS for staging)
    - 1.1.1.1        # Cloudflare (fallback — all non-staging resolves)
```

**Why NOT redundant DNS:** The blast radius is staging-only. Redundant CoreDNS on another node adds operational overhead (zone sync, monitoring, Ansible role) for a SPOF that affects zero production traffic. RTO is ~30 min (flash SD + Ansible). Trade-off accepted.

#### 3.7 Power management — not everything runs 24/7

Devices categorized by availability requirement:

| Mode | Devices | Watts | Schedule |
|---|---|---|---|
| **Always on** | RPi4 (DNS), RPi3 (monitoring), switch/router | ~14.5W | 24/7 |
| **Scheduled** | MiniPC1 (staging), MiniPC2 (platform) | ~22W | Business hours (e.g. 08:00-00:00) |
| **On-demand** | Beelink (Ollama), Jetson (llama.cpp) | ~20W | Wake-on-LAN when inference requested |

Estimated monthly electricity: ~23 kWh ≈ €3.9-5/mo (vs ~41 kWh ≈ €7/mo if 24/7).

Operational notes:
- Velero backup schedule must align with MiniPC2 "on" hours (MinIO must be reachable)
- Argo CD shows staging as "Unknown" when MiniPC1 is off — expected, not an alert
- WoL for Beelink/Jetson can be triggered from RPi4 (always on, same LAN)

### 4. Argo CD configuration

**Control plane (AWS K3s):**
- Non-HA installation (single-instance, tuned resource requests: ~576MB total)
- App of Apps pattern: Argo CD manages its own installation from Git
- Image Updater: auto-detects new Docker images → commits updated tag to Git → Argo CD syncs
- Notifications: webhook/Slack on sync failures

**Spoke registration via Headscale:**
```
Argo CD (AWS, Headscale IP)
  ├── spoke: prod    → https://<VPS Tailscale IP>:6443
  └── spoke: staging → https://100.64.0.4:6443
```

**ApplicationSet for multi-environment:**
```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: kubelab-apps
spec:
  generators:
    - list:
        elements:
          - cluster: staging
            url: https://100.64.0.4:6443
            values: staging
          - cluster: prod
            url: https://<VPS_TAILSCALE_IP>:6443
            values: prod
  template:
    spec:
      source:
        repoURL: https://github.com/mlorentedev/kubelab
        path: infra/helm/kubelab
        helm:
          valueFiles:
            - values.yaml
            - values-{{values}}.yaml
      destination:
        server: '{{url}}'
        namespace: kubelab
```

**Access:** Domain `argo.kubelab.live` → Tailscale IP via CoreDNS split DNS. Dashboard (HTTPS + Argo CD auth) + CLI via port-forward. Both accessible only through Headscale VPN.

### 5. Persistence strategy

| Environment | Block storage | Object storage | Backup |
|---|---|---|---|
| Prod (VPS) | Local SSD 80GB (CAX21 included) | MinIO on MiniPC2 via Headscale | Hetzner server backup ($1.40/mo) + Velero → MinIO → B2 |
| Staging (MiniPC1) | local-path-provisioner (K3s default) | Same MinIO | Optional (data is ephemeral) |
| Control plane (AWS) | EBS 8GB (OS + K3s only) | None | None needed (stateless) |

**Why NOT Hetzner Cloud Volumes**: Local SSD 80GB (included in CAX21) is sufficient for current workloads. Cloud Volumes add when >80GB needed or when detachable storage is required.

**3-2-1 backup rule:**
```
3 copies:  PV on prod SSD + MinIO on MiniPC2 + Backblaze B2
2 media:   Block storage (SSD) + Object storage (MinIO/B2)
1 offsite: B2 (geographically separate datacenter)
```

**Non-K8s backups**: BorgBackup (Stream R Phase 2) still applies to non-K8s nodes (RPi4 configs, Beelink Ollama models, VPS Docker volumes like Headscale SQLite + acme.json). Velero only covers K8s cluster state and PVs.

### 6. Observability architecture

Two independent, complementary layers:

**Layer 1: Internal observability (per-cluster metrics + centralized aggregation)**
```
Prod (VPS K3s):
  ├── Prometheus           (local scrape)
  ├── Grafana              (centralized dashboards — queries all clusters)
  ├── Loki                 (log aggregation — receives from all clusters)
  └── Alertmanager         (alerts → Slack/email)

Staging (MiniPC1 K3s):
  └── Prometheus           (local scrape, remote_write → prod Loki)

Control plane (AWS):
  └── no monitoring        (too small, Spot risk — don't lose dashboards to reclaim)
```

**Why Grafana on prod, not control plane**: Needs to be near the data (Prometheus, Loki). Spot interruption would lose dashboards. VPS has 99.9% SLA.

**Layer 2: External synthetic monitoring (independent observer)**
```
RPi3:
  └── Uptime Kuma          (probes all services from outside all clusters)
```

RPi3 stays independent. Its value IS its independence. It detects failures that internal monitoring can't (cluster-level outages, DNS failures, network partitions).

### 7. Security baseline

Integrated as a stream within the implementation plan, not a separate initiative.

| Priority | Item | Implementation phase | Interview question it answers |
|----------|------|---------------------|------------------------------|
| HIGH | Network Policies (default-deny per namespace) | Phase 4 | "How do you isolate workloads?" |
| HIGH | Pod Security Standards (restricted) | Phase 4 | "Can a pod run as root?" |
| HIGH | Trivy in CI (image scanning) | Phase 3 | "How do you prevent deploying vulnerable images?" |
| HIGH | DR drill (documented full restore) | Phase 5 | "Have you tested your backups?" |
| MEDIUM | Kyverno admission controller | Phase 6 | "What prevents bad configs from deploying?" |
| MEDIUM | SLOs/SLIs definition | Phase 6 | "What's your error budget?" |
| MEDIUM | Resource requests/limits on all pods | Phase 4 | "How do you prevent resource contention?" |
| MEDIUM | Alerting runbooks | Phase 6 | "An alert fires, what does oncall do?" |

### 8. Cost analysis

| Item | Monthly | Notes |
|------|---------|-------|
| Hetzner VPS (CAX21) | $6.99 | Existing — prod K3s + Headscale |
| Hetzner Backup | $1.40 | Existing — removable after Velero proven |
| Hetzner IPv4 | $0.60 | Existing |
| AWS t4g.micro Spot | ~$2.50 | NEW — control plane compute |
| AWS EBS 8GB gp3 | ~$0.80 | NEW — boot volume |
| ~~AWS Public IPv4~~ | ~~$3.60~~ | REMOVED — VPN-only access, temporary IP sufficient for Tailscale bootstrap |
| Backblaze B2 (~100GB) | ~$0.50 | NEW — offsite backup replica |
| Domains (amortized) | ~$2.00 | Existing |
| **Cloud total** | **~$14.79** | **Delta from current ($8.99): +$5.80/mo** |
| Homelab electricity | ~€6-9 | ~57W continuous × 24h × 30d ≈ 41 kWh × €0.15-0.22/kWh. Measure with power meter for actual. |

Comparable managed service: AWS EKS control plane alone = $72/mo. GKE Autopilot = $74/mo.

### 9. Implementation phases

**Dependency chain:** Phase 0 → Phase 1 → Phase 2 → Phase 3 ↔ Phase 4 (parallel) → Phase 5 → Phase 6

#### Phase 0: Close pending work (prerequisite)
- [ ] Merge pending PRs → api 1.0.0 release
- [ ] Clean stale branches (develop, old feature/*, fix/*)
- [ ] Clean DockerHub RC tags

#### Phase 1: Hardware re-provisioning (~2 days)
- [ ] MiniPC2: Reimage Ubuntu Server 24.04, Docker Compose (MinIO + GH Runner)
- [ ] MiniPC1: Reimage Ubuntu Server 24.04, K3s all-in-one staging
- [ ] Ansible roles: extend `base_system`, `docker` for MiniPC2; extend `k3s_server` for all-in-one mode
- [ ] MinIO: Docker Compose with `minio/minio`, console on Headscale-only
- [ ] GitHub Actions Runner: `actions/runner` self-hosted, Docker-in-Docker enabled
- [ ] Verify staging K3s operational: `helm upgrade` manually (Argo CD not yet available)

#### Phase 2: VPS K3s migration (~1 week) — ADR-020 Phase 3
- [ ] K3s install on VPS via Ansible (Pattern C: side-by-side with Docker Compose)
- [ ] TLS SAN: public IP `162.55.57.175` + Tailscale IP (configure BEFORE first K3s start)
- [ ] Migrate services: Docker Compose → K3s Helm charts (ADR-021 H2 + H3)
- [ ] Headscale STAYS in Docker Compose (ADR-015, bootstrap dependency)
- [ ] Hetzner Backup continues (safety net during migration)
- [ ] Validate: all prod services running on K3s, Docker Compose services stopped (except Headscale)
- [ ] Delete raw `infra/k8s/base/` and `infra/k8s/overlays/` (Helm is now authoritative — ADR-021 H3)

#### Phase 3: AWS Control Plane + Argo CD (~1 week)
- [ ] Terraform module: `infra/terraform/aws/` — t4g.micro Spot, EBS 8GB, security group (6443 + Tailscale), cloud-init
- [ ] Cloud-init: Ubuntu 24.04, K3s server, Tailscale client (`--login-server=https://vpn.kubelab.live`)
- [ ] Ansible: extend `k3s_server` role for AWS target (minimal — cloud-init does most work)
- [ ] Argo CD: Helm chart install (non-HA, tuned resource requests)
- [ ] Register spokes: `argocd cluster add` for staging + prod (via Headscale IPs)
- [ ] ApplicationSet: all apps deployed to both clusters from umbrella chart
- [ ] App of Apps: Argo CD manages its own installation
- [ ] DNS: `argo.kubelab.live` → Tailscale IP via CoreDNS on RPi4
- [ ] Image Updater: watches DockerHub, commits updated tags to Git
- [ ] Notifications: Slack webhook on sync failures
- [ ] Trivy: reintroduce image scanning in CI pipeline
- [ ] Self-hosted runner: configure repo to use MiniPC2 runner for Docker builds

#### Phase 4: Security baseline (~3 days, parallel with Phase 3)
- [ ] Namespace restructure: `infra`, `monitoring`, `apps` (on both clusters)
- [ ] Network Policies: `default-deny-all` per namespace + explicit allows (Traefik → apps, apps → DB)
- [ ] Pod Security Standards: `restricted` profile enforced on `apps` namespace
- [ ] Resource requests/limits: defined in all Helm values files
- [ ] RBAC: ServiceAccount per app, no default SA usage

#### Phase 5: Backup + DR (~3 days)
- [ ] Velero: Helm chart on both clusters, managed by Argo CD
- [ ] MinIO buckets: `velero-backups`, `loki-chunks`, `artifacts`
- [ ] Velero schedule: daily prod backup, weekly staging
- [ ] B2 replication: MinIO server-side replication → Backblaze B2 bucket
- [ ] BorgBackup: non-K8s nodes (RPi4, Beelink, VPS Docker volumes) → MinIO (Stream R Phase 2, adapted)
- [ ] **DR drill**: Full cluster restore from Velero backup. Document observed RTO/RPO. This MUST be executed, not just planned.

#### Phase 6: Observability + hardening (~1 week)
- [ ] Loki: Helm chart on prod, storage backend → MinIO `loki-chunks` bucket
- [ ] Prometheus federation: staging remote_write → prod
- [ ] Grafana: datasources for both clusters, pre-built dashboards (cluster health, app metrics)
- [ ] Alertmanager: basic rules (pod restarts >3, error rate >5%, disk >80%)
- [ ] Runbooks: one per alert, linked in Alertmanager annotations
- [ ] Kyverno: admission controller (block privileged pods, require labels, image registry whitelist)
- [ ] SLOs/SLIs: define for api + web (availability, latency p99)

### 10. Roadmap task consolidation

#### Streams ABSORBED (fully or partially)

| Stream / Task | Absorbed into | Notes |
|---|---|---|
| **Stream E** — ARGO-001..006 | Phase 3 | Core of this ADR |
| **Stream E** — SEAL-001..004 | Deferred | External Secrets Operator evaluated later. SOPS pipeline continues. |
| **Stream D** — MinIO setup | Phase 1 | Platform Node |
| **Stream D** — Loki completion | Phase 6 | Observability stack |
| **Stream D** — Prometheus federation | Phase 6 | Observability stack |
| **Stream R** — Phases 1-3 (K8s backup) | Phase 5 | Velero + MinIO + B2. BorgBackup for non-K8s nodes stays from Stream R Phase 2. |
| **Stream R** — Phase 4-5 (monitoring + DR test) | Phase 5-6 | Alerting on backup jobs + DR drill |
| **Stream B11** — H2 (third-party Helm charts) | Phase 2 | VPS migration uses official charts |
| **Stream B11** — H3 (prod deploy via Helm) | Phase 2 | Raw manifests deleted after migration |
| **Stream B11** — H4 (Argo CD consumes charts) | Phase 3 | ApplicationSet → umbrella chart |
| **ADR-020 Phase 3** (K3s on VPS) | Phase 2 | Critical dependency |
| **ADR-020 Phase 4** (Terraform compute) | Phase 3 | Extended to AWS |
| **VER-008** (CI build optimization) | Phase 1 | MiniPC2 as self-hosted runner |

#### Streams that REMAIN independent

| Stream | Why independent |
|---|---|
| **Stream C** (Repo Separation) | Organizational, not architectural. Argo CD supports multi-repo via ApplicationSets. Proceed independently. |
| **Stream V** (VPN Consolidation) | Headscale stays on VPS. ACLs, Headplane UI are independent features. |
| **Stream Q** (Testing & Quality) | Benefits from GitOps (sync status as quality gate) but test authoring is independent. |
| **Stream T** (Mobile Ops) | Independent tooling (Termux + kubectl). |
| **Stream CLOUD** (Personal Cloud) | Requires dedicated hardware. See conflict below. |
| **Stream OPS** (Domain transfer) | Independent operational task. |
| **Stream G** (CI/CD Versioning) | RC + CalVer pipeline already working. No changes needed. |

#### CONFLICT: Stream CLOUD vs MiniPC2

Stream CLOUD roadmap specifies "Dedicated Acemagic mini PC" for Nextcloud + Immich. This ADR repurposes MiniPC2 as Platform Node.

**Options:**
- (a) Stream CLOUD uses a NEW third Acemagic (~€150 purchase) — clean separation
- (b) Stream CLOUD shares MiniPC2 — 12GB tight for MinIO + Runner + Nextcloud + Immich + PostgreSQL + Redis
- (c) Stream CLOUD deferred until Platform Node stable, then evaluate

**Recommendation:** Option (a). 12GB is insufficient for cohabitation. Stream CLOUD proceeds independently when hardware is purchased.

## Consequences

### Positive

- **Multi-cloud, multi-cluster, multi-environment** on real infrastructure — rare outside enterprise
- **GitOps end-to-end**: push → CI → image → Image Updater → commit → Argo CD sync. Zero manual kubectl for deploys.
- **Stateless control plane**: destroy and rebuild in 10 min. Zero RPO. Interview-ready DR story.
- **3-2-1 backups**: Velero + MinIO + B2 with documented DR drill
- **Consolidated roadmap**: 6+ scattered streams → one coherent plan with clear phases
- **Faster CI**: self-hosted runner with local Docker layer cache (VER-008)
- **CV differentiator**: Hub-and-Spoke GitOps with Argo CD across AWS + Hetzner + on-prem
- **Security narrative**: Network Policies + PSS + Trivy + Kyverno + DR drill. Answers all common interview security questions.

### Negative

- **Increased operational surface**: 1 new cloud provider (AWS), 1 new tool (Argo CD), 1 new backup tool (Velero)
- **MiniPC reimaging downtime**: staging unavailable during Phase 1 (~1 day)
- **AWS IPv4 hidden cost**: $3.60/mo is 50% of AWS spend
- **Spot interruption**: Argo CD unavailable during reclaim (~5-15 min/month). Mitigated by Autonomous Spoke pattern.
- **CLOUD stream conflict**: MiniPC2 repurposed, CLOUD needs separate hardware purchase

### Neutral

- **Hetzner Backup becomes redundant** after Velero + DR drill proven. Can remove ($1.40/mo saved).
- **Kustomize fully replaced by Helm**: ADR-021 H3 consequence, no raw manifests survive.
- **Sealed Secrets deferred**: SOPS + toolkit pipeline continues until External Secrets Operator evaluated.
- **BorgBackup coexists with Velero**: BorgBackup for non-K8s nodes (RPi4, Beelink, VPS Docker volumes), Velero for K8s clusters. Different tools for different scopes.

## Phase 3 Implementation Notes (added 2026-03-22)

### No Elastic IP — VPN-only access

**Decision:** Skip AWS Elastic IP ($3.60/mo saved). All Argo CD communication uses Headscale VPN.

**Rationale:**
- Argo CD → spokes: Tailscale IPs (stable, independent of public IP)
- Argo CD → GitHub: outbound HTTPS (works with any public IP)
- User → Argo CD UI: via Tailscale (VPN-only, Authelia protected)
- Elastic IP adds zero value when all traffic is VPN

**Bootstrap flow:** cloud-init uses temporary public IP (free, assigned by AWS to running instances) to register with Headscale. After registration, all communication is VPN. Temporary IP is never used again.

**Spot interruption recovery (~10 min):**
1. AWS reclaims instance → Tailscale disconnects → Argo CD stops
2. Pods on spokes KEEP RUNNING (Autonomous Spoke pattern)
3. Spot fleet launches new instance (new temporary public IP)
4. cloud-init re-executes: K3s + Tailscale re-register + Argo CD restarts
5. Argo CD reconciles automatically — full recovery

**Tailscale IP stability:** Use reusable pre-auth key with `--hostname=argo-hub`. Headscale assigns IP from pool. If IP changes on re-registration, update `extra_records` in Headscale config. Expected frequency: ~1/month.

### Staging offline is normal

Staging (ace1) is powered off when not developing. Argo CD handles this natively:
- Spoke status: "Unknown" (not an error)
- No alerts for staging unreachable
- On power-on: Argo CD detects reconnection → full reconciliation
- Sync policy: `retry` with backoff, notification filter excludes staging-offline

### Hub has no ingress controller — proxied via prod Traefik

**Decision:** aws1 runs K3s with `--disable=traefik`. Argo CD UI is exposed via VPS (prod) Traefik using the EndpointSlice pattern (same as Headscale).

**Flow:** `argo.kubelab.live` → Cloudflare DNS → VPS public IP → prod K3s Traefik → IngressRoute → EndpointSlice (100.64.0.4:8080) → aws1 argocd-server via Tailscale VPN

**Rationale:**
- aws1 has 1GB RAM — no room for Traefik + Authelia + CrowdSec
- Reuses existing prod Traefik (TLS, Authelia, CrowdSec) — zero additional software on hub
- Same proven pattern as Headscale (Docker Compose on VPS, proxied through K3s Traefik)
- Argo CD `--insecure` mode (TLS terminated at prod Traefik, not at Argo CD)

**Alternatives rejected:**
- Traefik on aws1: RAM pressure on 1GB instance, duplicated ingress stack
- NodePort: works but no TLS, no Authelia, unprofessional
- Port-forward: not a real solution, manual each time

### Kustomize, not Helm umbrella (updated from original ADR)

ADR-021 Rev2 (2026-03-19) reverted the Helm umbrella chart. Current state:
- **Custom apps** (api, web, errors): Kustomize base + overlays
- **Third-party services**: Kustomize now, Helm official charts in H2 (deferred)
- **Argo CD sources**: `infra/k8s/overlays/{env}/` per spoke (Kustomize)

ApplicationSet references Kustomize paths, not Helm values files.

## References

- [adr-020-iac-lifecycle-strategy](adr-020-iac-lifecycle-strategy.md) — Extended: adds GitOps layer. Phase 3 (K3s VPS) is Phase 2 of this ADR.
- [adr-021-helm-k8s-packaging](adr-021-helm-k8s-packaging.md) — Extended: H2-H4 absorbed. Argo CD consumes umbrella chart.
- [adr-015-vps-k3s-migration-strategy](adr-015-vps-k3s-migration-strategy.md) — Headscale constraint respected. Pattern C (side-by-side) for VPS migration.
- [adr-012-environment-strategy](adr-012-environment-strategy.md) — Staging = mirror of prod. No dev environment.
- Stream E tasks: ARGO-001..006, SEAL-001..004
- Stream R: Phases 1-5
- Stream D: MinIO, Loki, Prometheus federation
- VER-008: CI build time optimization
