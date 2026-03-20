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
                          │ Traefik     │──→ api, web, errors,
                          │ Headscale   │   grafana, gitea, n8n,
                          │ (Docker     │   loki, portainer
                          │  Compose)   │──→ Uptime Kuma (RPi3)
                          └──────┬──────┘   via Tailscale proxy
                                 │
                    Headscale VPN mesh (WireGuard)
                    ┌────────────┼────────────────────┐
                    │            │                     │
          ┌────────┴───┐  ┌─────┴──────┐    ┌────────┴────────┐
          │   RPi4     │  │   ace1     │    │  Other nodes    │
          │  Gateway   │  │  Staging   │    │                 │
          ├────────────┤  ├────────────┤    │ ace2: GH Runner │
          │ Pi-hole    │  │ K3s single │    │       + MinIO   │
          │ CoreDNS    │  │ 13 pods:   │    │ Beelink: Ollama │
          │ DHCP       │  │ api, web,  │    │ RPi3: Uptime    │
          │            │  │ authelia,  │    │       Kuma      │
          │ Split DNS: │  │ grafana,   │    │ Jetson: Pollex  │
          │ *.staging  │  │ crowdsec,  │    │  (llama.cpp)    │
          │ .kubelab   │  │ gitea, n8n │    │                 │
          │ .live      │  │ loki, minio│    │                 │
          └────────────┘  │ redis,     │    └─────────────────┘
                          │ vector     │
                          └────────────┘
                   *.staging.kubelab.live
                   staging.mlorente.dev
```

**Production:** Hetzner VPS running Docker Compose (migrating to K3s in Phase 2), public via `*.kubelab.live` and `mlorente.dev`.
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
| CI/CD | GitHub Actions, multi-arch Docker builds |
| IaC | Terraform, Ansible, Python toolkit |

### Applications

| App | Stack | Description |
|-----|-------|------------|
| [Web](apps/web/) | Astro + TypeScript + Tailwind | Portfolio and landing page |
| [API](apps/api/) | Go + Gin | Backend services (newsletter, lead magnets) |
| [Errors](edge/errors/) | HTML + Nginx | Custom Traefik error pages |

### Self-hosted services

Grafana, Loki, Authelia, CrowdSec, Gitea, MinIO, n8n, Redis.

## Project Structure

```
kubelab/
├── apps/                        Application source code
│   ├── api/                     Go REST API
│   └── web/                     Astro portfolio site
│
├── infra/
│   ├── k8s/                     Kubernetes manifests
│   │   ├── base/                Base manifests (staging defaults)
│   │   └── overlays/            Kustomize overlays (staging, prod)
│   ├── stacks/                  Docker Compose stacks (dev environment)
│   ├── terraform/               Terraform DNS (Cloudflare)
│   ├── ansible/                 Server provisioning playbooks
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
make dev
```

Services available at `*.kubelab.test` (requires `/etc/hosts` entries — see `make setup-local-dns`).

## Environments

| Environment | Infrastructure | Access | Domains |
|-------------|---------------|--------|---------|
| Development | Docker Compose (local) | localhost | `*.kubelab.test` |
| Staging | K3s on ace1 (bare metal) | Headscale VPN | `*.staging.kubelab.live`, `staging.mlorente.dev` |
| Production | Docker Compose on VPS (→ K3s Phase 2) | Public internet | `*.kubelab.live`, `mlorente.dev` |

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
Hetzner VPS (ARM)      — Production: Docker Compose + Headscale
Acemagic-1 (bare metal)— K3s staging (13 pods, all-in-one)
Acemagic-2 (bare metal)— Platform node (GH Runner + MinIO)
Beelink (bare metal)   — Ollama (LLM inference)
RPi 4 (8GB)            — Network gateway: Pi-hole, CoreDNS, DHCP
RPi 3 (1GB)            — External monitoring (Uptime Kuma)
Jetson Nano (4GB)      — Pollex (llama.cpp, GPU inference)
```

All nodes connected via Headscale VPN mesh (WireGuard protocol, 8 nodes).

## License

See [LICENSE](LICENSE) for details.

## Author

Manuel Lorente — [mlorente.dev](https://mlorente.dev) | [GitHub](https://github.com/mlorentedev)
