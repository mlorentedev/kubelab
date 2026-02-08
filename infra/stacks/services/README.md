 Third-Party Services

This directory contains deployment configurations for third-party services, organized by category.

 Structure

```
infra/compose/services/
├── core/                  Essential platform services
│   ├── gitea/             Git hosting
│   ├── portainer/         Container management
│   └── vaultwarden/       Password manager
├── observability/         Monitoring and logging
│   ├── grafana/           Metrics visualization
│   ├── loki/              Log aggregation
│   └── uptime/            Uptime monitoring
├── data/                  Data management
│   ├── docmost/           Documentation wiki
│   └── minio/             S-compatible storage
├── security/              Authentication & security
│   └── authelia/          SSO authentication
├── misc/                  Productivity tools
│   ├── calcom/            Scheduling
│   └── immich/            Photo management
└── ai/                    AI/ML services
    └── ollama/            Local LLM runtime
```

 Deployment

 Using Toolkit

```bash
 List all available services by category
poetry run toolkit services list

 Start a service
poetry run toolkit services up gitea
poetry run toolkit services up grafana

 View logs
poetry run toolkit services logs portainer --follow

 Stop a service
poetry run toolkit services down vaultwarden
```

 Using Docker Compose Directly

```bash
 Navigate to service directory
cd infra/compose/services/core/gitea

 Start in development
docker compose -f docker-compose.dev.yml --env-file .env.dev up -d

 Start in production
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d
```

 Environment Files

Each service has environment files per environment:

- `.env.dev` - Development
- `.env.staging` - Staging (CubeLab)
- `.env.prod` - Production (Hetzner)
- `.env..example` - Templates (in git)

 Service Categories

 Core
Essential services required for platform operation:
- gitea: Self-hosted Git service (GitHub alternative)
- portainer: Docker container management UI
- vaultwarden: Password manager (Bitwarden-compatible)

 Observability
Monitoring, logging, and uptime tracking:
- grafana: Metrics dashboards and visualization
- loki: Centralized log aggregation
- uptime: Service uptime monitoring (Uptime Kuma)

 Data
Data storage and management:
- docmost: Team documentation and wiki
- minio: Object storage (S-compatible)

 Security
Authentication and access control:
- authelia: Single sign-on (SSO) and FA

 Misc
Productivity and utility tools:
- calcom: Scheduling and calendar management
- immich: Self-hosted photo and video backup

 AI
AI and machine learning services:
- ollama: Local large language model runtime

 Adding New Services

. Create service directory in appropriate category:
   ```bash
   mkdir -p infra/compose/services/{category}/{service-name}
   ```

. Add docker-compose files:
   ```bash
   touch docker-compose.dev.yml
   touch docker-compose.staging.yml
   touch docker-compose.prod.yml
   ```

. Create environment files:
   ```bash
   cp .env.dev.example .env.dev
    Edit with actual values
   ```

. Update this README with service description

 Documentation

- `docs/ARCHITECTURE.md` - System architecture
- `docs/HOW-TO.md` - Quick command reference
- Individual service READMEs for service-specific docs

 Related

- Edge Services: `edge/` - Network edge (Traefik, Nginx, DNS)
- Custom Apps: `infra/compose/apps/` - Custom application deployments
- Toolkit: `toolkit/cli/services.py` - Service management commands
