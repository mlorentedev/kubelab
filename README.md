# KubeLab

Personal Internal Developer Platform (IDP) — a hybrid-cloud infrastructure powering a portfolio of web services across homelab and cloud environments.

## Architecture

```
                          Internet
                             |
                     Cloudflare DNS (Terraform)
                             |
                    +--------+--------+
                    |                 |
             Hetzner VPS         Homelab (LAN)
          (production K3s)     (staging K3s cluster)
           single-node          3 nodes on Proxmox
                    |                 |
                    +--------+--------+
                             |
                      Headscale VPN mesh
                       (9 nodes, WireGuard)
```

**Production:** Hetzner VPS running K3s single-node, public via `*.kubelab.live` and `*.mlorente.dev`.
**Staging:** 3-node K3s cluster on Proxmox VMs (Acemagic mini PCs), accessible via Headscale VPN.
**Development:** Docker Compose on localhost with `*.kubelab.test` domains.

### Key architectural decisions

- **K3s over full K8s** — lightweight, single-binary, built-in Traefik and Helm controller
- **Kustomize overlays** — base manifests (staging domains) + prod overlay patches, no Helm charts for custom apps
- **SOPS for secrets** — age-encrypted YAML committed to Git, toolkit injects into K8s at deploy time
- **Headscale self-hosted VPN** — replaces Tailscale SaaS, WireGuard-based mesh across all nodes
- **Terraform for DNS** — Cloudflare zones managed declaratively, 28 records, one-command IP migration
- **Split DNS** — public DNS via Cloudflare, internal via Pi-hole + CoreDNS on RPi4

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Orchestration | K3s v1.34, Kustomize |
| Reverse proxy | Traefik v3 (K3s HelmChartConfig) |
| Auth | Authelia (SSO + OIDC) |
| Security | CrowdSec (IDS + Traefik bouncer) |
| Observability | Grafana + Loki + Vector |
| Monitoring | Uptime Kuma (external, RPi3) |
| DNS | Cloudflare + Terraform |
| VPN | Headscale + Tailscale clients |
| Secrets | SOPS (age encryption) |
| CI/CD | GitHub Actions, multi-arch Docker builds |
| IaC | Terraform, Ansible, Python toolkit |

### Applications

| App | Stack | Description |
|-----|-------|------------|
| [Web](apps/web/) | Astro + TypeScript + Tailwind | Portfolio and landing page |
| [API](apps/api/) | Go + Gin | Backend services (newsletter, lead magnets) |
| [Blog](apps/blog/) | Jekyll | Technical blog |
| [Wiki](apps/wiki/) | MkDocs Material | Project documentation |

### Self-hosted services

Grafana, Loki, Authelia, CrowdSec, Gitea, MinIO, n8n, Portainer, Redis.

## Project Structure

```
kubelab/
├── apps/                        Application source code
│   ├── api/                     Go REST API
│   ├── blog/                    Jekyll blog
│   ├── web/                     Astro portfolio site
│   └── wiki/                    MkDocs documentation
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
├── edge/                        Network edge (Traefik, Nginx, CoreDNS)
├── toolkit/                     Python CLI for platform management
├── Makefile                     Development shortcuts
└── CONTRIBUTING.md              Contributing guidelines
```

See each directory's `README.md` for module-specific documentation.

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

Services available at `*.kubelab.test` (requires `/etc/hosts` entries — see `make hosts`).

## Environments

| Environment | Infrastructure | Access | Domains |
|-------------|---------------|--------|---------|
| Development | Docker Compose (local) | localhost | `*.kubelab.test` |
| Staging | K3s cluster (3 nodes, Proxmox) | Headscale VPN | `*.staging.kubelab.live` |
| Production | K3s single-node (Hetzner VPS) | Public internet | `*.kubelab.live`, `*.mlorente.dev` |

## CI/CD Pipeline

GitHub Actions with Gitflow branching (`feature/* -> develop -> master`):

- **Change detection** — only builds affected apps (blog, api, web)
- **Security scanning** — gitleaks, gosec, bandit, npm audit, Trivy
- **Multi-arch builds** — `linux/amd64` + `linux/arm64` Docker images
- **Semantic versioning** — automatic from conventional commits
- **Three-tier tags** — `dev.{sha}` (feature) / `rc.N` (develop) / `X.Y.Z` (master)

## Toolkit CLI

The `toolkit` CLI manages the entire platform lifecycle:

```bash
alias tk='poetry run toolkit'

# Services
tk services list                          # List all services
tk services up grafana                    # Start a service

# Infrastructure
tk infra k8s deploy --env staging         # Deploy K8s manifests
tk infra k8s apply-secrets --env prod     # Inject SOPS secrets into K8s
tk infra terraform plan --env prod        # Plan DNS changes
tk infra terraform apply --env prod       # Apply DNS changes

# Configuration
tk config generate --env dev              # Generate configs for environment
tk config validate                        # Validate all configs
```

See [`toolkit/README.md`](toolkit/README.md) for full command reference.

## Hardware Topology

```
Hetzner VPS (ARM)      — Production K3s + Headscale (Docker Compose)
Acemagic-1 (Proxmox)   — K3s server + agent-1 VMs
Acemagic-2 (Proxmox)   — K3s agent-2 VM
Beelink (bare metal)   — Ollama (LLM inference)
RPi 4 (8GB)            — Network gateway: Pi-hole, CoreDNS, Headscale relay
RPi 3 (1GB)            — External monitoring (Uptime Kuma)
```

All nodes connected via Headscale VPN mesh (WireGuard protocol, 9 nodes).

## License

See [LICENSE](LICENSE) for details.

## Author

Manuel Lorente — [kubelab.live](https://kubelab.live) | [GitHub](https://github.com/mlorentedev)
