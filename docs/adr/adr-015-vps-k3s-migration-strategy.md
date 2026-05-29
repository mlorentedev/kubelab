---
id: "adr-015-vps-k3s-migration"
type: adr
status: active
tags: [k3s, migration, production, vps, headscale, traefik]
created: "2026-02-27"
owner: manu
---

# ADR-015: VPS K3s Migration Strategy — Side-by-Side Cutover

## Status

Accepted (2026-02-27). Extends ADR-011, ADR-012.

## Context

PROD-K3S-001 requires migrating the Hetzner VPS (CAX21, ARM64, 8GB) from Docker Compose to K3s single-node. The VPS currently runs Traefik on ports 80/443, Headscale (VPN control plane), and several web applications. Key constraints:

1. **Single server** — no second VPS available for true blue-green
2. **Headscale dependency** — K3s nodes communicate via Tailscale; Headscale is the control plane
3. **Port conflict** — Docker Compose Traefik holds 80/443; K3s Traefik needs those same ports
4. **Public-facing** — `mlorente.dev` and `*.kubelab.live` resolve to this VPS
5. **ARM architecture** — all images must support arm64

### Migration patterns evaluated

| Pattern | Description | Downtime | Fit |
|---------|-------------|----------|-----|
| **A: Big-Bang** | Stop Compose, install K3s, deploy, pray | Minutes–hours | High risk, no validation window |
| **B: Blue-Green (2nd VPS)** | Provision temporary VPS, DNS cutover | ~0 | Ideal but costs ~4€/month; overkill for single-user IDP |
| **C: Side-by-Side (alternate ports)** | K3s Traefik on 8080/8443, validate, swap | <5 min | Pragmatic for single VPS |
| **D: Incremental (wave)** | Migrate service-by-service | ~0 but complex | Overly complex for our service count |

### Headscale placement question

Should Headscale run inside K3s or remain in Docker Compose?

## Decision

### 1. Migration pattern: Side-by-Side with alternate ports (Pattern C)

Install K3s alongside Docker Compose. K3s Traefik starts on ports 8080/8443 while Compose Traefik holds 80/443. This provides a full validation window without affecting live traffic.

**Validation phase:** All IngressRoutes tested via `curl -H "Host: domain" http://VPS:8080`.

**Cutover window (<5 min):**
1. Stop Docker Compose Traefik (not Headscale)
2. Update K3s HelmChartConfig to ports 80/443
3. K3s reconciles automatically (~60s)

**Rollback:** `systemctl stop k3s && docker compose up -d` — immediate.

### 2. Headscale stays outside K3s (Docker Compose, permanent)

Headscale is a **bootstrapping dependency** — the cluster depends on VPN connectivity, which depends on Headscale. Running Headscale inside K3s creates a circular dependency:

```
K3s nodes communicate via → Tailscale (data plane)
Tailscale key exchange requires → Headscale (control plane)
If Headscale runs inside → K3s
Then K3s depends on → K3s  ← circular
```

If K3s fails (OOM, bad upgrade, etcd corruption):
- Existing Tailscale connections survive (cached keys)
- New key exchanges and node re-auth **fail**
- Cannot debug K3s remotely if VPN control plane died with it

**Industry principle:** Services that the cluster depends on must not run inside the cluster. Applies to: VPN control planes, DNS resolvers, identity providers for cluster auth, backup orchestrators.

**Permanent Docker Compose stack on VPS (post-migration):**

```yaml
# Infrastructure layer — never migrates to K3s
services:
  headscale:       # VPN control plane (port 8080 + 3478/UDP)
  headscale-ui:    # Admin UI (or Headplane when deployed)
```

Everything else (Traefik, apps, observability, Authelia, CrowdSec) migrates to K3s.

### 3. K3s configuration: defaults + TLS SAN

```yaml
# /etc/rancher/k3s/config.yaml
write-kubeconfig-mode: "0600"
tls-san:
  - "162.55.57.175"     # Public IPv4
  - "100.64.0.2"        # Tailscale IP
```

**Keep enabled (K3s defaults):**
- `traefik` — managed via HelmChartConfig, not installed separately
- `servicelb` (Klipper) — binds Traefik to host ports via DaemonSet hostPort
- `coredns` — cluster DNS (service discovery)
- `metrics-server` — `kubectl top`, low overhead

**Nothing to disable** for single-node. K3s defaults are designed for this exact use case.

### 4. TLS/ACME: Traefik ACME now, cert-manager deferred

Traefik's built-in ACME with Cloudflare DNS-01 challenge. Same pattern as Docker Compose, proven and familiar. Certificates stored in a PVC (`acme.json`).

cert-manager deferred as a future optimization (certs as K8s Secrets, better observability). Not needed for initial migration.

### 5. Rollback tiers

| Tier | When | How | RTO |
|------|------|-----|-----|
| **T1: Compose resume** | First 24h (Compose paused, not removed) | `systemctl stop k3s && docker compose unpause` | <5 min |
| **T2: VPS snapshot** | Any time | Restore Hetzner snapshot, repoint DNS (TTL=300s) | <30 min |
| **T3: Full rebuild** | Snapshot expired/corrupted | Fresh VPS + K3s install + SOPS secrets + `kubectl apply -k` | <2h |
| **T4: VPN always up** | Any scenario | Headscale in Docker Compose survives K3s failures | Continuous |

### 6. Pre-migration checklist

| Step | When | Why |
|------|------|-----|
| Terraform DNS automation | Before migration | Automated DNS rollback capability |
| Hetzner VPS snapshot | Day of migration | Nuclear rollback in <5 min |
| Cloudflare TTL → 300s | 24h before cutover | Fast DNS propagation on rollback |
| Backup Docker volumes | Day of migration | Headscale SQLite, acme.json, app data |
| Validate prod overlay | Before migration | `kubectl kustomize overlays/prod/` clean |

## Rationale

### Why Pattern C over Pattern B (Blue-Green)

Pattern B (second VPS, DNS cutover) is the industry gold standard for zero-downtime migrations. We chose Pattern C because:

- Single-user IDP — brief downtime is acceptable
- The VPS public IP doesn't change — no DNS migration needed, only port swap
- Second VPS adds operational complexity (sync data, coordinate DNS) for a ~4€ saving of 5 minutes downtime
- Pattern C provides the same validation window (alternate ports) without the second server

If this were a multi-tenant SaaS, Pattern B would be mandatory.

### Why not disable ServiceLB

Some single-node operators use `--disable=servicelb` with `hostNetwork: true` on Traefik. We keep ServiceLB because:
- It's K3s's purpose-built solution for this use case
- Confirmed working on Hetzner ARM (community validated)
- hostNetwork trades CNI isolation for marginal simplicity
- ServiceLB is the default — boring tech wins

### Why Traefik ACME over cert-manager (for now)

cert-manager is the industry recommendation for production K3s. We defer it because:
- Traefik ACME is already our proven pattern
- Adding cert-manager during migration increases risk surface
- Migration should change one thing (Compose → K3s), not two
- cert-manager tracked as future task for when we need it

## Consequences

1. **Headscale permanently in Docker Compose** — update PROD-K3S-005 to reflect this
2. **Pre-migration tasks required** — Terraform DNS, snapshot, TTL, backups before PROD-K3S-001
3. **Port swap is the cutover** — not a DNS change; Cloudflare records stay pointing at same IP
4. **K3s Traefik port conflict** — HelmChartConfig must start on 8080/8443, swap to 80/443 at cutover
5. **Soak test respected** — B6 execution starts 2026-02-28 (day 7 of staging validation per ADR-011)
6. **Day-2 ops needed** — etcd backups, upgrade strategy, Headscale lifecycle, DR runbook (new backlog section)
7. **cert-manager deferred** — tracked as future task in Stream D

## Related

- [adr-011-k3s-homelab-staging](adr-011-k3s-homelab-staging.md) — K3s migration strategy (this ADR implements Phase 2)
- [adr-012-environment-strategy](adr-012-environment-strategy.md) — Prod single-node design, service distribution
- [adr-013-vpn-consolidation](adr-013-vpn-consolidation.md) — Headscale as single VPN control plane
- [adr-014-secrets-management-strategy](adr-014-secrets-management-strategy.md) — SOPS + toolkit for prod secrets
