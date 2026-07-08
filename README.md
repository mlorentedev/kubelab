# KubeLab

Personal Internal Developer Platform (IDP) — a hybrid-cloud infrastructure powering a portfolio of web services across homelab and cloud environments.

## Architecture

```
                              Internet
                                 │
                        Cloudflare DNS (Terraform)
                         *.kubelab.live, mlorente.dev
                                 │
                          ┌──────┴──────┐
                          │  Hetzner VPS │  162.55.57.175
                          │  (ARM, prod) │
                          ├─────────────┤
                          │ K3s: Traefik│──→ api, web, errors,
                          │  apps, obs, │   grafana, loki, gitea,
                          │  postgres   │   authelia, n8n, redis
                          │ Headscale   │──→ Uptime Kuma (RPi3)
                          │ (Compose)   │   via Tailscale proxy
                          └──────┬──────┘
                                 │
                 Headscale VPN mesh (WireGuard, 8 nodes)
                 Argo CD hub on AWS (aws1) syncs both spokes
                    ┌────────────┼────────────────────┐
                    │            │                     │
          ┌────────┴───┐  ┌─────┴──────┐    ┌────────┴────────┐
          │   RPi4     │  │   ace1     │    │  Other nodes    │
          │  Gateway   │  │  Staging   │    │                 │
          ├────────────┤  ├────────────┤    │ aws1: Argo CD   │
          │ Pi-hole    │  │ K3s single │    │       hub       │
          │ CoreDNS    │  │ node: api, │    │ ace2: Ollama    │
          │ DHCP       │  │ web, auth- │    │ Beelink: GH     │
          │            │  │ elia, graf-│    │  Runner + MinIO │
          │ Split DNS: │  │ ana, loki, │    │ RPi3: Uptime    │
          │ *.staging  │  │ postgres,  │    │       Kuma      │
          │ .kubelab   │  │ gitea, n8n,│    │ Jetson: Pollex  │
          │ .live      │  │ redis, ... │    │  (llama.cpp)    │
          └────────────┘  └────────────┘    └─────────────────┘
                   *.staging.kubelab.live
                   staging.mlorente.dev
```

**Production:** K3s single-node on the Hetzner VPS (Headscale stays in Docker Compose per ADR-015), public via `*.kubelab.live` and `mlorente.dev`. Delivery is GitOps: an Argo CD hub on AWS (aws1) syncs the prod and staging spokes.
**Staging:** K3s single-node on ace1 (bare metal), accessible via Headscale VPN at `*.staging.kubelab.live` and `staging.mlorente.dev`.
**Development:** Docker Compose on localhost with `*.kubelab.test` domains.

### Key architectural decisions

- **K3s over full K8s** — lightweight, single-binary, built-in Traefik and Helm controller
- **Hybrid K8s packaging (ADR-021 Rev2)** — Kustomize for custom apps (simpler YAML), Helm official charts for third-party services
- **SOPS for secrets** — age-encrypted YAML committed to Git, toolkit injects into K8s at deploy time
- **Headscale self-hosted VPN** — replaces Tailscale SaaS, WireGuard-based mesh across all nodes
- **Terraform for DNS** — Cloudflare zones managed declaratively, prod domains only
- **Split DNS** — staging zones in `networking.staging_zones` (SSOT) → Headscale split DNS → RPi4 Pi-hole → CoreDNS

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Orchestration | K3s v1.34, Kustomize, Helm (third-party) |
| Reverse proxy | Traefik v3 (K3s HelmChartConfig) |
| Auth | Authelia (SSO + OIDC) |
| Security | CrowdSec (IDS + Traefik bouncer) |
| Observability | Grafana + Loki + Vector |
| Monitoring | Uptime Kuma (standalone on RPi3) |
| DNS | Cloudflare (prod) + CoreDNS (staging) |
| VPN | Headscale + Tailscale clients |
| Secrets | SOPS (age encryption) |
| Data | PostgreSQL (shared), Redis, MinIO |
| GitOps | Argo CD (hub on AWS, spokes staging/prod) |
| CI/CD | GitHub Actions, multi-arch Docker builds |
| IaC | Terraform, Ansible, Python toolkit |

### Applications

| App | Stack | Description |
|-----|-------|------------|
| Web | Astro + TypeScript + Tailwind | Extracted to its own repository (ADR-053); images arrive via the `web-image-receiver` workflow |
| [API](apps/api/) | Go + Gin | Backend services (newsletter, lead magnets) |
| [Errors](edge/errors/) | HTML + Nginx | Custom Traefik error pages |

### Self-hosted services

Grafana, Loki, Vector, Authelia, CrowdSec, Gitea, MinIO, n8n, Redis, PostgreSQL, Apprise, Homepage. Argo CD runs on the AWS hub; Ollama is external (ace2) behind a K3s EndpointSlice.

## Project Structure

```
kubelab/
├── apps/                        Application source code
│   ├── api/                     Go REST API
│   └── wiki/                    Generated docs output (not an app)
│
├── infra/
│   ├── k8s/                     Kubernetes manifests
│   │   ├── base/                Base manifests (staging defaults)
│   │   └── overlays/            Kustomize overlays (staging, prod)
│   ├── stacks/                  Docker Compose stacks (dev environment)
│   ├── terraform/               Terraform: DNS (Cloudflare) + AWS hub
│   ├── ansible/                 Server provisioning playbooks
│   ├── helm/                    Helm values for third-party services (Argo CD)
│   ├── n8n/                     n8n workflow definitions
│   └── config/
│       ├── values/              Environment config (YAML per env)
│       └── secrets/             SOPS-encrypted secrets
│
├── edge/                        Network edge (Traefik config, error pages)
├── toolkit/                     Python CLI for platform management
├── Makefile                     Development shortcuts
└── CONTRIBUTING.md              Contributing guidelines
```

## Quick Start

```bash
# Prerequisites: Docker, Python 3.12+, Poetry, Make

# Install toolkit
poetry install

# Initialize dev environment
make setup

# Start development stack
make up-dev
```

Services available at `*.kubelab.test` (requires `/etc/hosts` entries — see `make setup-local-dns`).

## Environments

| Environment | Infrastructure | Access | Domains |
|-------------|---------------|--------|---------|
| Development | Docker Compose (local) | localhost | `*.kubelab.test` |
| Staging | K3s on ace1 (bare metal) | Headscale VPN | `*.staging.kubelab.live`, `staging.mlorente.dev` |
| Production | K3s single-node on VPS (Argo CD synced) | Public internet | `*.kubelab.live`, `mlorente.dev` |

## CI/CD Pipeline

Trunk-based development (`feature/*` / `fix/*` → `master`, squash merge):

- **Change detection** — only builds affected apps (api, web, errors)
- **Multi-arch builds** — `linux/amd64` + `linux/arm64` Docker images
- **Per-app SemVer** — `{app}-v{X.Y.Z}` tags via Release Please
- **RC tags** — `{version}-rc.{N}` on PRs, auto-cleaned on merge

## Toolkit CLI

The `toolkit` CLI manages the entire platform lifecycle:

```bash
alias tk='poetry run toolkit'

# Deploy
make deploy-k8s ENV=staging              # Deploy K8s manifests (Kustomize)
make deploy TARGET=vps ENV=prod          # Deploy VPS services (Ansible)
make deploy TARGET=dns ENV=staging       # Deploy DNS gateway (Ansible)
make provision NODE=ace1 ENV=staging     # Provision a node (Ansible)

# Secrets & config
tk infra k8s apply-secrets --env staging # Inject SOPS secrets into K8s
tk infra terraform plan                  # Plan DNS changes
tk infra terraform apply                 # Apply DNS changes
```

See [`toolkit/README.md`](toolkit/README.md) for full command reference.

## Hardware Topology

```
Hetzner VPS (ARM)      — Production: K3s + Headscale (Docker Compose)
AWS t4g.small (aws1)   — Argo CD hub (management plane)
Acemagic-1 (ace1)      — K3s staging (all-in-one)
Acemagic-2 (ace2)      — Ollama bare metal (LLM compute)
Beelink (bare metal)   — Platform node: GH Runner + MinIO
RPi 4 (8GB)            — Network gateway: Pi-hole, CoreDNS, DHCP
RPi 3 (1GB)            — External monitoring (Uptime Kuma)
Jetson Nano (4GB)      — Pollex (llama.cpp, GPU inference)
```

All nodes connected via Headscale VPN mesh (WireGuard protocol, 8 nodes).

## License

See [LICENSE](LICENSE) for details.

## Author

Manuel Lorente — [mlorente.dev](https://mlorente.dev) | [GitHub](https://github.com/mlorentedev)

## Documentation

Project-bound knowledge lives in [`docs/`](docs/) (docs-as-code): ADRs, architecture, runbooks, troubleshooting, and lessons.
