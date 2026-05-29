---
id: "kubelab-architecture"
type: adr
status: stale
stale_as_of: "2026-05-16"
superseded_by: adr-002-orchestrator-architecture
created: "2026-02-08"
owner: manu
---

# KubeLab Architecture

> Decisions made 2026-02-08.

## Architecture Decisions

### Pattern: SDK Distribution + Internal Developer Platform (IDP)

Generic toolkit published as a versioned package. Each consumer project
pins its own version and controls its upgrade timeline independently.

### Repos (under `github.com/mlorente/`)

```
kubelab-cli              → Generic Python CLI (Typer+Rich)
kubelab-platform         → Infrastructure monorepo
cubernautas-blog         → Cubernautas blog (separate identity)
sensortool               → B2B SaaS (FastAPI/Go + Astro), portable
future-static-sites      → Each static site in its own repo
```

### Key Decisions

| Decision | Choice | Reason |
|----------|--------|--------|
| Pattern | SDK Distribution + IDP | Versioned toolkit, consumers pin versions |
| Repos | 4+ (toolkit, platform, blog, sensortool) | Each portfolio-ready, independent lifecycle |
| Config file | `kubelab.yaml` per project | Namespaced, declarative |
| Package | `kubelab-cli` → command `kubelab` | PyPI + GitHub Packages |
| Shared infra | Platform services shared, data logically isolated | One PostgreSQL, separate DBs per app |
| Portability | Compose overrides (dev=local, prod=shared) | Env vars abstract the difference |
| Wiki | Not deployed as app | Auto-generated from kubelab.yaml, served locally |
| VPN | Headscale (self-hosted) + Tailscale clients | WireGuard underneath, self-owned |
| Users | `manu` on homelab, `deploy` on VPS | Avoids redundancy |
| K8s deploy | `kubectl apply -k` initially | Learn raw tools before abstractions |
| Config generation | Toolkit generates ALL environment configs | Single source of truth: common.yaml → toolkit |

### Domain Strategy

| Environment | Personal site | Platform services |
|-------------|--------------|-------------------|
| Local dev | `mlorente.test` | `*.kubelab.test` |
| Staging | `web.staging.kubelab.live` | `*.staging.kubelab.live` |
| Production | `mlorente.dev` | `*.kubelab.live` |

## Hardware Allocation

> **Updated 2026-02-19**: 2x Acemagic (Proxmox) + Beelink (Ollama) + VPS.

```
VPS Hetzner: Production (Docker Compose -> K3s)
Acemagic-1:  Proxmox VE (K3s server + agent VM)
Acemagic-2:  Proxmox VE (K3s agent VM)
Beelink:     Ollama (Bare metal)
RPi 4:       Gateway / VPN / DNS
RPi 3:       Monitoring (Uptime Kuma)
Jetson Nano: AI Workloads (Pollex)
```

### Deployment Flow

```
local dev      → toolkit → Docker Compose (workstation)
develop branch → kubectl apply -k overlays/staging → K3s staging
master branch  → kubectl apply -k overlays/prod → K3s VPS
```

## Related Documentation

- Architecture Decision Records — all ADRs
- Infrastructure docs — DNS and network topology
- [Service catalog](service-catalog.md)
- [Current architecture state](current-state-2026-03-22.md)
- [Platform architecture diagram](diagram.md)
- [Versioning strategy](versioning-strategy.md)
- [DASH-001: Homepage cockpit](dash-001-homepage-cockpit.md)
- [Homepage endpoints tab plan](../adr/2026-03-26-homepage-endpoints-tab.md)
