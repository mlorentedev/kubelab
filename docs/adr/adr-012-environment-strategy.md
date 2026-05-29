---
id: "kubelab-adr-012-environment-strategy"
type: adr
status: accepted
tags: [adr, kubelab]
created: "2026-02-25"
owner: manu
---

# ADR-012: Environment Strategy — K3s Everywhere, Dual Domain

## Status

Accepted (2026-02-25). Extends ADR-011.

## Context

Before executing B6 (VPS K3s migration), a validation was needed for whether the architecture was over-engineered, how the two domains should map to environments, and where mobile ops tooling fits. This ADR crystallizes those decisions.

### Questions resolved

1. **Is K3s on a single VPS over-engineering?** No — K3s was built for this. ~300MB overhead on an 8GB CAX21 (3.7%) buys self-healing, declarative ingress, rolling updates, and manifest parity with staging.
2. **Second VPS for HA?** Not now. Add later as a natural evolution story ("I started single-node, then scaled when I needed HA").
3. **Domain mapping?** Both `mlorente.dev` and `*.kubelab.live` are DNS routing concerns on the same K3s cluster, not separate environments. Different IngressRoutes, same infrastructure.
4. **Tailscale + Termux + Crush?** Three tracks with staggered timelines (see below).

## Decision

### Three environments, one manifest set

```
LOCAL DEV (workstation)
├── Tech: Docker Compose
├── Domains: *.kubelab.test + mlorente.test
├── Purpose: Fast iteration, full stack local
└── Config: infra/config/values/dev.yaml

LAB / STAGING (K3s homelab, 3 nodes on Proxmox)
├── Tech: K3s multi-node (server + 2 agents)
├── Domains: *.staging.kubelab.live
├── Access: Tailscale VPN only
├── Purpose: Test, experiment, learn, break things
└── Config: infra/config/values/staging.yaml

PRODUCTION (K3s on Hetzner VPS, single node)
├── Tech: K3s single-node (→ HA later)
├── Domains: mlorente.dev + *.kubelab.live
├── Access: Public internet (Cloudflare DNS + Let's Encrypt)
├── Purpose: Public-facing portfolio, technical showcase, monetization
└── Config: infra/config/values/prod.yaml
```

Promotion path: `local dev (Compose) → staging K3s → prod K3s`. Same Kustomize manifests, different overlays.

### Prod service distribution

| Tier | Services | Auth | Rationale |
|------|----------|------|-----------|
| **PUBLIC** | mlorente.dev, api, blog, status, wiki | None (CrowdSec only) | Portfolio & monetization |
| **PROTECTED** | grafana, traefik | Authelia one-factor | Show real dashboards in interviews |
| **OWN AUTH** | gitea, n8n, console.minio | Service-native login | Self-hosted alternatives showcase |
| **INTERNAL** | loki, vector, redis, authelia, crowdsec | Cluster-only | Infrastructure — no public access |

### K3s single-node on VPS — what we gain

| Capability | Docker Compose | K3s single-node |
|------------|---------------|-----------------|
| Self-healing | Restart policy only | Full reconciliation loop |
| Rolling updates | Manual pull+restart | Zero-downtime by default |
| Health checks | Basic healthcheck | Liveness + readiness + startup probes |
| Secret management | .env / SOPS | K8s Secrets + SOPS integration |
| Ingress | Manual Traefik config | Declarative IngressRoute CRDs |
| Manifest parity | None (Compose ≠ K8s) | Same overlays dev→staging→prod |

### Domain strategy

Nothing changes in DNS. `mlorente.dev` and `*.kubelab.live` already point to VPS IP. Only the backend changes (Docker Compose → K3s). IngressRoutes handle routing.

### Mobile ops roadmap (Tailscale + Termux + Crush)

**Track 1: Mobile Ops (1-2 days)** — Termux + Tailscale + kubectl from phone. Immediate value, no code changes.

**Track 2: Crush Contribution (medium-term)** — Learn Go via `charmbracelet/crush` contributions. The "OpenCode" Go project was renamed to Crush after a project split.

**Track 3: kubelab-mobile showcase (future)** — Termux + Crush + kubelab integration. Blog content for kubelab.live.

## Implementation

### Repo changes (this ADR)

1. `infra/k8s/overlays/prod/patches.yaml` — Kustomize patches overriding base staging domains with prod
2. `infra/k8s/overlays/prod/ingress.yaml` — CrowdSec middleware on public routes
3. `infra/k8s/overlays/prod/secrets.yaml` — Prod secrets template (populate from SOPS before deploy)
4. `infra/config/values/prod.yaml` — Full service inventory matching staging
5. `infra/k8s/overlays/prod/deployments.yaml` — API secretRef added

### VPS deployment sequence (B6)

1. Install K3s single-node on VPS (`INSTALL_K3S_VERSION=v1.34.4+k3s1`)
2. Set up kubeconfig from workstation (Tailscale IP: 100.64.0.2)
3. Populate prod secrets from SOPS
4. `kubectl apply -k infra/k8s/overlays/prod/`
5. Verify all IngressRoutes resolve
6. Update GitHub Actions deploy step
7. Decommission Docker Compose on VPS (keep files for rollback)

## Rationale

### Why not two VPS for HA

- Premature optimization — single node is the pragmatic starting point
- Better portfolio story: "started single, scaled to HA when needed"
- Hetzner CAX11 is only 3.79/month if HA is needed later
- HA K3s with embedded etcd needs 3 servers (or 2 + external DB)

### Why Loki is internal-only in prod

Loki stores raw application logs. Exposing it publicly adds attack surface with no interview value. Grafana (which IS public behind Authelia) queries Loki internally — the dashboards show the observability capability without exposing the data store.

### Why CrowdSec on all public routes

CrowdSec runs as a ForwardAuth middleware, checking each request against community-sourced IP blocklists before it reaches the application. On a public-facing single VPS, this is the first line of defense.

## Consequences

1. **B6 unblocked**: Prod overlay is complete and kustomize-validated
2. **VPS migration is a technology swap**: Same services, same domains, K3s replaces Compose
3. **Docker Compose preserved**: `infra/stacks/` stays for local dev; `edge/traefik/` archived after B6
4. **Secrets need population**: `prod/secrets.yaml` has placeholders — SOPS integration required before first deploy
5. **Mobile ops is a separate track**: Not blocking B6, but roadmapped

## Related

- [adr-011-k3s-homelab-staging](adr-011-k3s-homelab-staging.md) — Original K3s migration strategy (this ADR extends it)
- [adr-006-tailscale-over-wireguard](adr-006-tailscale-over-wireguard.md) — VPN decision
- [adr-010-headscale-over-tailscale-cloud](adr-010-headscale-over-tailscale-cloud.md) — VPN control plane
