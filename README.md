 KubeLab

Personal platform monorepo - portfolio, blog, API, and self-hosted services.

Live: [kubelab.live](https://kubelab.live)

 Overview

This monorepo contains everything needed to run the KubeLab platform across three environments:
- Development (local) - For development and testing
- Staging (KubeLab homelab) - Pre-production on Raspberry Pi cluster
- Production (Hetzner VPS) - Live public platform

 Tech Stack

- Frontend: Astro + Tailwind CSS + HTMX
- Backend: Go (REST API)
- Blog: Jekyll (Ruby)
- Wiki: MkDocs Material (Python)
- Infrastructure: Docker Compose, Traefik, Nginx, Ansible, Terraform
- Automation: Python CLI toolkit (Typer + Rich)

 Quick Start

 Prerequisites

- Docker & Docker Compose (v+)
- Python .+ with Poetry
- Make (for shortcuts)
- Git

 Setup

```bash
 Clone repository
git clone https://github.com/mlorente/kubelab.live
cd kubelab.live

 Install Poetry (if not installed)
curl -sSL https://install.python-poetry.org | python -

 Install toolkit dependencies
poetry install

 Initialize environment files from examples
poetry run toolkit tools env-init dev

 Start development stack
make dev
```

 Access Services

Once running, services are available at:

| Service | URL | Description |
|---------|-----|-------------|
| Web | http://localhost: | Personal portfolio (Astro) |
| Blog | http://localhost: | Technical blog (Jekyll) |
| API | http://localhost: | REST API (Go) |
| Wiki | http://localhost: | Documentation (MkDocs) |
| Traefik | http://localhost: | Reverse proxy dashboard |

 Project Structure

```
kubelab.live/
├── apps/                     Application source code
│   ├── api/                  Go REST API
│   ├── blog/                 Jekyll blog
│   ├── web/                  Astro website
│   ├── wiki/                 MkDocs documentation
│   ├── nn/                  nn workflow definitions
│   └── workers/              Background workers
│
├── edge/                     Network edge services
│   ├── traefik/              Reverse proxy
│   ├── nginx/                Cache + error pages
│   └── dns-gateway/          CoreDNS + WireGuard (staging)
│
├── infra/
│   ├── stacks/              Docker Compose deployments
│   │   ├── apps/            App deployment configs
│   │   ├── services/        Third-party services (categorized)
│   │   │   ├── core/        portainer, gitea, vaultwarden
│   │   │   ├── observability/   grafana, loki, uptime
│   │   │   ├── data/        docmost, minio
│   │   │   ├── security/    authelia
│   │   │   ├── misc/        calcom, immich
│   │   │   └── ai/          ollama
│   │   └── edge/            traefik, nginx, dns-gateway
│   ├── ansible/             Server provisioning
│   ├── terraform/           DNS management
│   └── config/              Global configuration
│
├── toolkit/                  Python CLI (main tool)
│   ├── cli/                  Command definitions
│   ├── core/                 Core functionality
│   ├── features/             Feature implementations
│   └── config/               Toolkit configuration
│
├── docs/                     Documentation
│   ├── ARCHITECTURE.md       System architecture
│   ├── TOOLKIT.md            Toolkit usage guide
│   ├── HOW-TO.md             Quick command reference
│   ├── CI-CD.md              CI/CD documentation
│   └── ...
│
├── Makefile                  Development shortcuts
├── pyproject.toml            Python/Poetry configuration
└── CONTRIBUTING.md           Contributing guidelines
```

 Toolkit CLI

The `toolkit` CLI is the primary tool for managing the platform:

```bash
 Alias for convenience (add to ~/.bashrc or ~/.zshrc)
alias tk='poetry run toolkit'

 Apps and services management
tk services up web               Start web app
tk services logs api --follow    View API logs
tk services build blog           Build blog
tk services down wiki            Stop wiki
tk services list                 List all services by category
tk services up grafana           Start Grafana
tk services logs portainer       View Portainer logs

 Configuration
tk config generate traefik dev    Generate Traefik configs

 Environment tools
tk tools env-validate        Validate all .env files
tk tools env-examples dev    Generate .env..example files

 Deployment
ENVIRONMENT=staging tk deployment deploy
```

See `docs/TOOLKIT.md` for complete documentation.

 Environments

 Development (local)
- Purpose: Local development and testing
- Access: localhost
- Services: Basic stack (Traefik HTTP only)

 Staging (KubeLab homelab)
- Infrastructure: Raspberry Pi cluster
- Access: VPN (WireGuard) + `.staging.kubelab.live`
- Services: Full production-like stack
- Purpose: Pre-production testing

 Production (Hetzner VPS)
- Infrastructure: Cloud VPS
- Access: Public `.kubelab.live`
- Services: Full stack with HTTPS
- Purpose: Live production

 Development Workflow

 Working on Applications

. Edit source code in `apps/{app-name}/`
. Copy environment file for Docker build:
   ```bash
   cp infra/stacks/apps/web/.env.dev apps/web/.env.dev
   ```
. Build and test:
   ```bash
   tk services build web
   tk services up web
   tk services logs web
   ```

 Working on Services

```bash
 Navigate to service
cd infra/stacks/services/observability/grafana

 Update configuration
vim compose.dev.yml
vim .env.dev

 Test
tk services up grafana
tk services logs grafana
```

 Working on Toolkit

```bash
 Edit Python code
cd toolkit/
vim cli/services.py

 Format and type check
make format
make type

 Test
poetry run pytest
```

 Pre-commit Hooks

Install pre-commit hooks for automated local validation:

```bash
 Install hooks (first time only)
poetry run pre-commit install

 Run manually on all files
poetry run pre-commit run --all-files
```

Hooks run automatically before each commit:
- Secret detection with gitleaks
- Python linting (black, ruff, mypy)
- YAML/JSON validation
- Path consistency checks
- Environment file protection

 Deployment

 CI/CD Pipeline

GitHub Actions automatically:
. Detects changed applications
. Runs security scans (secrets, SAST, dependencies)
. Calculates semantic version
. Builds multi-arch Docker images
. Scans images with Trivy
. Pushes to Docker Hub
. Creates git tags

See `docs/CI-CD.md` for complete pipeline documentation.

 Manual Deployment

```bash
 Deploy to staging
make deploy-staging

 Deploy to production
make deploy-prod

 Check deployment status
tk deployment status
```

 Documentation

| Document | Description |
|----------|-------------|
| ARCHITECTURE.md | System architecture and design principles (planned) |
| TOOLKIT.md | Complete toolkit CLI guide |
| HOW-TO.md | Quick command reference |
| CONTRIBUTING.md | How to contribute |
| CI-CD.md | CI/CD pipeline documentation |
| KUBELAB.md | Homelab (staging) setup |
| TROUBLESHOOTING.md | Common issues and solutions |
| VERSIONING.md | Versioning strategy |

 Makefile Shortcuts

The Makefile provides convenience commands:

```bash
 Setup
make setup                   Complete first-time setup

 Development
make dev                     Start core services (Traefik + apps)
make up                      Start everything
make down                    Stop everything
make logs                    View all logs

 Apps
make app NAME=web ACTION=up      Start specific app
make app NAME=api ACTION=logs    View specific app logs

 Validation
make validate                Validate all configs
make type                    Run mypy type checking
make format                  Format Python code

 Deployment
make deploy-staging          Deploy to staging
make deploy-prod             Deploy to production
```

 Testing

```bash
 Validate environment files
tk tools env-validate

 Test builds
tk services build web
tk services build api

 Run toolkit tests
poetry run pytest

 Type checking
make type
```

 Docker

All applications and services run in Docker containers:

- Multi-stage builds for efficiency
- Non-root users for security
- Health checks for reliability
- Proper networking with Docker networks
- Volume management for persistence

 Services

 Core
- Gitea: Self-hosted Git (GitHub alternative)
- Portainer: Container management UI
- Vaultwarden: Password manager

 Observability
- Grafana: Metrics visualization
- Loki: Log aggregation
- Uptime Kuma: Uptime monitoring

 Data
- Docmost: Team documentation
- MinIO: S-compatible object storage

 Security
- Authelia: SSO and FA

 Miscellaneous
- Cal.com: Scheduling
- Immich: Photo management

 AI
- Ollama: Local LLM runtime

 Security

 Automated Security Scanning

Pre-commit Hooks (Local):
- Secret detection with gitleaks
- Path validation and consistency checks
- Prevents committing real environment files
- Python linting and type checking

CI/CD Pipeline:
- Secret scanning: gitleaks on every build
- SAST: bandit (Python), gosec (Go)
- Dependency scanning: pip-audit, govulncheck, npm audit
- Container scanning: Trivy scans Docker images
- Results uploaded to GitHub Security tab

 Infrastructure Security

- HTTPS everywhere (Let's Encrypt in staging/prod)
- Security headers via Traefik middleware
- HTTP Basic Auth for sensitive dashboards
- Secrets managed via .env files (gitignored)
- WireGuard VPN for staging access
- Environment templates sanitized (secrets → `CHANGE_ME`)
- Non-root containers with health checks
- Regular vulnerability scanning in CI/CD

 Contributing

Contributions welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) for:
- Development setup
- Code standards
- Pull request process
- Testing guidelines

 License

See [LICENSE](LICENSE) for details.

 Author

Manuel Lorente
- Website: [kubelab.live](https://kubelab.live)
- GitHub: [@mlorente](https://github.com/mlorente)

 Acknowledgments

Built with:
- [Astro](https://astro.build/) - Web framework
- [Jekyll](https://jekyllrb.com/) - Blog generator
- [MkDocs Material](https://squidfunk.github.io/mkdocs-material/) - Documentation
- [Traefik](https://traefik.io/) - Reverse proxy
- [Docker](https://www.docker.com/) - Containerization
- [Typer](https://typer.tiangolo.com/) - CLI framework
- [Rich](https://rich.readthedocs.io/) - Terminal formatting

---

Status: Active Development | Version: See git tags | Updated: November 
