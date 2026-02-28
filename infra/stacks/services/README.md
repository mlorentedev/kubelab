 Third-Party Services

This directory contains deployment configurations for third-party services, organized by category.

 Structure

```
infra/stacks/services/
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
cd infra/stacks/services/core/gitea

 Start in development
docker compose -f compose.base.yml -f compose.dev.yml up -d

 Start in production
docker compose -f compose.base.yml -f compose.prod.yml up -d
```

 Configuration

All configuration is centralized (not per-stack):

- **Values**: `infra/config/values/{common,dev,staging,prod}.yaml`
- **Secrets**: `infra/config/secrets/{env}.enc.yaml` (SOPS-encrypted)

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
   mkdir -p infra/stacks/services/{category}/{service-name}
   ```

. Add compose files:
   ```bash
   touch compose.base.yml
   touch compose.dev.yml
   touch compose.staging.yml
   touch compose.prod.yml
   ```

. Add configuration values to `infra/config/values/{env}.yaml` for the new service

. Update this README with service description

 Documentation

- `docs/ARCHITECTURE.md` - System architecture
- `docs/HOW-TO.md` - Quick command reference
- Individual service READMEs for service-specific docs

 Related

- Edge Services: `edge/` - Network edge (Traefik, Nginx, DNS)
- Custom Apps: `infra/stacks/apps/` - Custom application deployments
- Toolkit: `toolkit/cli/services.py` - Service management commands
