---
id: dash-001-homepage-cockpit
type: task-spec
status: active
created: "2026-03-23"
owner: manu
---


# DASH-001: Developer Cockpit (Homepage Dashboard)

> **Status:** In Progress (staging deployed, UI tuning + prod pending)
> **Priority:** Medium — after Phase 3 core (ARGO-004, ARGO-010), before Phase 4
> **Estimated effort:** 2 sessions (Session 1: Phases 0-2, Session 2: Phases 3-5)
> **Created:** 2026-03-23

## Vision

A single browser startpage (`home.{staging.}kubelab.live`) providing a real-time map of the entire KubeLab infrastructure. Replaces the need to remember 30+ URLs across 6 nodes and 2 environments.

**Use case:** Open browser → see everything at a glance → click to access any service → spot issues immediately.

**Not a replacement for Uptime Kuma** (yet). Complementary:
- Homepage = "where do I go?" (portal + quick access + at-a-glance status)
- Uptime Kuma = "is everything up?" (detailed monitoring + alerting + history)

Long-term: when ARGO-011 (notifications) + Grafana alerting are configured, Uptime Kuma becomes redundant.

## Decisions Made (2026-03-23)

| Decision | Answer | Rationale |
|----------|--------|-----------|
| Tool | Homepage (gethomepage.dev) | YAML config (GitOps), K8s auto-discovery, 80+ widgets, ~100-150MB RAM, multi-arch, Helm chart |
| Domain | `home.{staging.}kubelab.live` | |
| Environments | Both (staging + prod) | Same dashboard accessible from VPN (staging) or public (prod) |
| Browser usage | Startpage (new tab page) | Design optimized for frequent scanning |
| Layout | Scroll + grid responsive | No tabs — full infrastructure photograph visible at once |
| Auth | `one_factor` (Authelia) in both envs | |
| Node metrics | Glances (API agent on 6 nodes) | Lightest option, Homepage has native widget |
| Bookmarks | All proposed categories | Cloud, Dev, Docs, Ops, Costs, Content, Knowledge |
| Widgets | All proposed | GitHub, Docker Hub, Cloudflare, Glances ×6 |
| Pi-hole proxy | Included in this task (staging only) | Same EndpointSlice pattern as Ollama |

## Service Inventory (31 entries)

### Staging (15 services)

| # | Service | Node | Deployment | URL |
|---|---------|------|------------|-----|
| 1 | API | ace1 | K8s Deployment | `api.staging.kubelab.live` |
| 2 | Web | ace1 | K8s Deployment | `staging.mlorente.dev` |
| 3 | Authelia | ace1 | K8s Deployment | `auth.staging.kubelab.live` |
| 4 | CrowdSec | ace1 | K8s Deployment | `crowdsec.staging.kubelab.live` |
| 5 | Grafana | ace1 | K8s Deployment | `grafana.staging.kubelab.live` |
| 6 | Loki | ace1 | K8s Deployment | `loki.staging.kubelab.live` |
| 7 | Gitea | ace1 | K8s Deployment | `gitea.staging.kubelab.live` |
| 8 | n8n | ace1 | K8s Deployment | `n8n.staging.kubelab.live` |
| 9 | MinIO | ace1 | K8s Deployment | `minio.staging.kubelab.live` |
| 10 | MinIO Console | ace1 | K8s Deployment | `console.minio.staging.kubelab.live` |
| 11 | Traefik | ace1 | K8s HelmChartConfig | `traefik.staging.kubelab.live` |
| 12 | Uptime Kuma | RPi3 | Docker → K8s proxy | `status.staging.kubelab.live` |
| 13 | Ollama | Beelink | Bare metal → K8s proxy | `ollama.staging.kubelab.live` |
| 14 | Pi-hole | RPi4 | Docker → K8s proxy (NEW) | `pihole.staging.kubelab.live` |
| 15 | Error Pages | ace1 | K8s Deployment | (middleware, no direct UI) |

### Prod (16 services)

| # | Service | Node | Deployment | URL |
|---|---------|------|------------|-----|
| 1 | API | VPS | K8s Deployment | `api.kubelab.live` |
| 2 | Web | VPS | K8s Deployment | `mlorente.dev` |
| 3 | Blog | VPS | K8s Deployment | `blog.kubelab.live` |
| 4 | Authelia | VPS | K8s Deployment | `auth.kubelab.live` |
| 5 | CrowdSec | VPS | K8s Deployment | `crowdsec.kubelab.live` |
| 6 | Grafana | VPS | K8s Deployment | `grafana.kubelab.live` |
| 7 | Loki | VPS | K8s Deployment | `loki.kubelab.live` |
| 8 | Gitea | VPS | K8s Deployment | `gitea.kubelab.live` |
| 9 | n8n | VPS | K8s Deployment | `n8n.kubelab.live` |
| 10 | MinIO | VPS | K8s Deployment | `minio.kubelab.live` |
| 11 | MinIO Console | VPS | K8s Deployment | `console.minio.kubelab.live` |
| 12 | Traefik | VPS | K8s HelmChartConfig | `traefik.kubelab.live` |
| 13 | Uptime Kuma | RPi3 | Docker → K8s proxy | `status.kubelab.live` |
| 14 | Headscale | VPS | Docker Compose | `vpn.kubelab.live` |
| 15 | Argo CD | aws1 | K8s → prod proxy | `argo.kubelab.live` |
| 16 | Error Pages | VPS | K8s Deployment | (middleware, no direct UI) |

### Node Metrics (6 nodes via Glances)

| Node | Role | Tailscale IP | Key Metrics |
|------|------|-------------|-------------|
| ace1 | K8s staging | 100.64.0.11 | CPU, RAM (12GB), disk, pods |
| VPS | K8s prod | 100.64.0.2 | CPU (4 vCPU), RAM (8GB), disk (80GB) |
| aws1 | Argo CD hub | 100.64.0.4 | CPU, RAM (1GB+2GB swap) — critical |
| RPi4 | DNS gateway | 100.64.0.10 | CPU, RAM (8GB), temperature |
| RPi3 | Monitoring | 100.64.0.6 | CPU, RAM (1GB), temperature |
| Beelink | Ollama/LLM | 100.64.0.3 | CPU, RAM (8GB), GPU, temperature |

### Bookmarks (external platforms)

| Category | Links |
|----------|-------|
| Cloud | AWS Console, Hetzner Cloud, Cloudflare Dashboard, Tailscale Admin |
| Development | GitHub (mlorentedev), Docker Hub (mlorentedev), PyPI |
| Documentation | K8s docs, Traefik docs, Argo CD docs |
| Operations | SSL Labs, Shodan (162.55.57.175), GitHub/Cloudflare/AWS Status pages |
| Costs | Hetzner billing, AWS billing |
| Content | Beehiiv, YouTube Studio, Google Analytics / Plausible |
| Knowledge | Obsidian vault (`obsidian://vault/knowledge`) |

### Widgets (live data)

| Widget | Source | Data shown |
|--------|--------|-----------|
| GitHub | GitHub API | Open PRs, Actions status, issues |
| Docker Hub | Docker Hub API | Pull count, latest tags per image |
| Cloudflare | Cloudflare API | Requests/day, threats blocked |
| Glances ×6 | Glances API (per node) | CPU, RAM, disk, temperature |

**Note:** GitHub, Cloudflare widgets require API tokens → SOPS → K8s Secret.

## Architecture

```
common.yaml (SSOT)
    ↓
K8s IngressRoutes (+ gethomepage.dev/* annotations)
    ↓ auto-discovery (K8s services)
Homepage ← ConfigMap (external services + bookmarks + widgets)
    ↓
home.{staging.}kubelab.live (Authelia one_factor)
```

**SSOT flow:**
- K8s services: auto-discovered via annotations on IngressRoutes (zero manual Homepage config)
- External services: listed in ConfigMap YAML (Pi-hole, Ollama, Uptime Kuma, Headscale, Argo CD)
- Adding a new K8s service: add annotations to IngressRoute → appears in dashboard automatically
- Adding a new external service: add EndpointSlice + IngressRoute with annotations → appears automatically

**Layout (scroll + responsive grid):**
```
┌─ home.kubelab.live ────────────────────────────────┐
│  🔍 Search                                          │
│                                                      │
│  ── Staging (4 cols) ──── ── Prod (4 cols) ──────── │
│  │ API    │ Web    │ Auth│ │ API  │ Web  │ Blog   │ │
│  │ Gitea  │ n8n    │MinIO│ │ Gitea│ n8n  │ MinIO  │ │
│  │ Graf.  │ Loki   │ ... │ │ Graf.│ Loki │ Argo CD│ │
│                                                      │
│  ── Infra (3 cols) ─────────────────────────────── │
│  │ ace1 CPU/RAM    │ VPS CPU/RAM    │ aws1 CPU/RAM │ │
│  │ RPi4 CPU/temp   │ RPi3 CPU/temp  │ Bee CPU/temp │ │
│                                                      │
│  ── External (3 cols) ── ── Bookmarks (4 cols) ─── │
│  │ GitHub widget   │ DockerHub      │ │ AWS │Hetzner│ │
│  │ Cloudflare      │                │ │ Docs│Costes │ │
└──────────────────────────────────────────────────────┘
```

## Implementation Plan

### Phase 0: Prerequisites (DNS + Pi-hole proxy)

**0.1 — Pi-hole EndpointSlice (staging only)**
- Create `infra/k8s/base/external/pihole.yaml` (Service + EndpointSlice → 100.64.0.10:80)
- IngressRoute `pihole.staging.kubelab.live` + Authelia `one_factor`
- Pattern: copy Ollama, change IPs/ports
- Pi-hole only in staging — RPi4 is LAN-only, no prod proxy needed

**0.2 — DNS records**
- Terraform (prod): `home.kubelab.live` → VPS IP
- Headscale split DNS (staging): add `home.staging.kubelab.live`
- common.yaml: add `home` and `pihole` to services/apps section

### Phase 1: Glances (metrics agent on 6 nodes)

**1.1 — Ansible role `glances`**
- `infra/ansible/roles/glances/` (tasks, templates, handlers)
- Install via pip or Docker (per node capability)
- Systemd unit or Docker Compose service
- Config: REST API on port 61208, bind 0.0.0.0
- Firewall: only accessible from Tailscale (100.64.0.0/24)
- common.yaml: add `glances_port: 61208` to networking or services section

**1.2 — Deploy to 6 nodes**
- Ansible group: `glances_nodes` (all nodes)
- Verify API: `curl http://<tailscale-ip>:61208/api/4/mem`

### Phase 2: Homepage — Helm + Kustomize base

**2.1 — Helm values**
- `infra/helm/homepage/values.yaml`
- Image: `ghcr.io/gethomepage/homepage:latest` (multi-arch)
- Resources: `requests: 64Mi/50m`, `limits: 192Mi/200m`
- `enableServiceLinks: false` (same pattern as Authelia/n8n)

**2.2 — ConfigMaps**
- `services.yaml` — external services (not auto-discovered)
- `widgets.yaml` — global widgets + Glances per node
- `bookmarks.yaml` — all external platform links
- `settings.yaml` — layout, theme (dark), title
- `kubernetes.yaml` — auto-discovery config (namespace: kubelab)

**2.3 — Kustomize base**
- `infra/k8s/base/services/homepage/` (deployment, service, configmap, serviceaccount, clusterrole)
- Add to `infra/k8s/base/kustomization.yaml`

### Phase 3: Homepage — Overlays

**3.1 — Staging overlay**
- IngressRoute `home.staging.kubelab.live`
- Middlewares: `secure-headers` + `crowdsec-bouncer` + `authelia`

**3.2 — Prod overlay**
- IngressRoute `home.kubelab.live`
- Same middleware stack
- Patch services.yaml for prod-specific URLs (Headscale, Argo CD)

### Phase 4: Auto-discovery — Annotations

**4.1 — Base IngressRoutes** (~8 files)
- Authelia, CrowdSec, Gitea, n8n, MinIO, MinIO Console, Grafana, Loki
- Add `gethomepage.dev/*` annotations

**4.2 — Staging IngressRoutes** (~3 files)
- API, Web, Traefik dashboard, Pi-hole, Ollama, Uptime Kuma

**4.3 — Prod IngressRoutes** (~5 files)
- API, Web, Blog, Traefik dashboard, Argo CD, Headscale, Uptime Kuma

### Phase 5: Deploy + Verification

- Deploy Glances to 6 nodes via Ansible
- Deploy Pi-hole EndpointSlice (`make deploy-k8s ENV=staging`)
- Deploy Homepage to staging, verify
- Deploy Homepage to prod, verify
- Verify Argo CD syncs both envs
- Configure browser startpage

## Dependencies

- **API tokens needed (SOPS):** GitHub PAT (read-only), Cloudflare API token (analytics read)
- **Glances port 61208** must be reachable from K8s pods via Tailscale
- **Homepage ServiceAccount** needs ClusterRole for K8s auto-discovery (list services, ingresses, pods)
- **Pi-hole v6** redirect `/` → `/admin` must work through Traefik proxy

## Patterns Followed

| Pattern | Reference |
|---------|-----------|
| Helm for third-party | `infra/helm/argocd/` (ADR-021 Rev2, H2) |
| EndpointSlice for external | `infra/k8s/base/external/ollama.yaml` |
| Ansible role | `infra/ansible/roles/k3s_server/` |
| SOPS secrets | `toolkit secrets set` → K8s Secret |
| DNS staging | `networking.staging_zones` in common.yaml |
| DNS prod | `infra/terraform/dns/` (Cloudflare) |
| Kustomize base + overlays | All existing services |
| Authelia one_factor | Same as Grafana, Loki, CrowdSec |

## Notes

- Proxmox no longer exists on ace1/ace2 (removed Phase 1, bare metal Ubuntu)
- Pi-hole proxy staging only — RPi4 is LAN, no prod use case
- Error Pages has no direct UI (middleware only) — listed for completeness but no dashboard entry
- Homepage replaces no existing service — purely additive
- Future: if Uptime Kuma becomes redundant (after ARGO-011 + Grafana alerting), can remove it and add history/alerting widgets to Homepage

## Lessons Learned (2026-03-23 implementation session)

1. **ConfigMap mount must use subPath** — Homepage needs writable `/app/config/logs/`. Mounting ConfigMap as directory makes it read-only. Use `subPath` per file.
2. **HOMEPAGE_ALLOWED_HOSTS required** — Next.js 15.x host validation rejects unknown domains. Must set env var with all domains.
3. **Authelia access_control needs explicit rules** — New domains don't match the `*.staging.kubelab.live` catch-all (restricted to `networks: internal`). Add explicit `one_factor` rule per new service.
4. **Glances v4 API is `/api/4/`** — Homepage defaults to `/api/3/`. Must set `version: 4` in widget config.
5. **`metric: info` broken in Glances widget** — Causes `forEach` JS error. Use `cpu` or `memory` instead.
6. **DNS cross-namespace fails from Homepage pod** — `traefik.kube-system.svc.cluster.local` doesn't resolve. Use ClusterIP directly (fragile if IP changes — consider ExternalName Service).
7. **GitHub/Cloudflare/DockerHub widgets don't exist** — Must use `customapi` widget type. `cloudflared` widget is for Tunnels only.
8. **Uptime Kuma status page API is public** — No auth needed. Slug is `kubelab`.
9. **Authelia restart invalidates browser sessions** — Users must clear `authelia_session` cookie for `staging.kubelab.live`. Added auto-restart in `make deploy-k8s`.
10. **Glances image tag `4-full` doesn't exist** — Correct tag: `4.5.2-full`.
11. **Bookmarks don't support tabs** — Must move bookmark content to services.yaml for tab layout support.
12. **subPath ConfigMap mounts don't auto-update** — K8s only updates full-directory ConfigMap mounts. subPath requires pod restart. Workaround: `configMapGenerator` with hash suffix (RELIAB-002).
13. **`make deploy-k8s` rollout restart is destructive** — Restarting Authelia invalidates all browser sessions. Users get 403 Forbidden until they clear cookies. Must fix with RELIAB-001 (initContainer) + RELIAB-002 (configMapGenerator) before prod deploy.
14. **Traefik API is port 9000, not 8080** — K3s bundled Traefik exposes API on 9000. Cross-namespace DNS doesn't resolve from pods; must use ClusterIP directly (fragile).

## Pending for next session

- [x] **RELIAB-001**: Authelia initContainer wait-for-redis ✓ 2026-03-23 — applied same session, Authelia now starts cleanly after every deploy.
- [ ] **RELIAB-002**: Migrate ConfigMaps to `configMapGenerator` with hash suffix — eliminates `rollout restart` hack in Makefile
- [ ] Fix Glances widget `forEach` error (metric: cpu still failing — investigate Homepage/Glances v4 compatibility)
- [ ] Traefik widget uses hardcoded ClusterIP 10.43.86.38 (fragile) — create ExternalName Service or fix cross-ns DNS
- [ ] UI tuning: verify tabs layout (Services/Infra/Links), theme refinement
- [ ] Deploy to prod
- [ ] Commit + PR
- [ ] Architecture diagram (iframe widget — Homepage supports it natively)
- [ ] Sidebar layout exploration (tabs implemented as alternative, CSS sidebar possible but fragile)
- [ ] Uptime Kuma: add missing monitors (only 5/15 services monitored)
