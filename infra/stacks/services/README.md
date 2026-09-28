# Third-Party Services

Docker Compose definitions for the third-party services of the local dev stack, organized by category. Kubernetes manifests for staging and prod live in `infra/k8s/`, not here.

## Structure

```
infra/stacks/services/
├── automation/
│   └── github-runner/     GitHub Actions runner
├── core/
│   ├── gitea/             Git forge
│   ├── headscale/         Tailscale control server
│   ├── n8n/               Workflow automation
│   └── pihole/            DNS sinkhole
├── misc/
│   ├── calcom/            Scheduling
│   └── immich/            Photo management
├── observability/
│   ├── grafana/           Dashboards
│   ├── loki/              Log aggregation
│   └── uptime/            Uptime Kuma
└── security/
    ├── authelia/          SSO
    └── crowdsec/          Intrusion prevention
```

## Deployment

### Using the toolkit

```bash
# List all available services by category
poetry run toolkit services list

# Start, follow and stop a service
poetry run toolkit services up gitea --env dev
poetry run toolkit services logs gitea --follow
poetry run toolkit services down gitea
```

### Using Docker Compose directly

```bash
cd infra/stacks/services/core/gitea
docker compose -f compose.base.yml -f compose.dev.yml up -d
```

## Configuration

All configuration is centralized, not per-stack:

- **Values**: `infra/config/values/{common,dev,staging,prod}.yaml`
- **Secrets**: `infra/config/secrets/{env}.enc.yaml` (SOPS-encrypted)

## Adding a service

1. Create `infra/stacks/services/{category}/{service-name}/` with `compose.base.yml` and one overlay per environment (`compose.dev.yml`, ...).
2. Add its values under `apps.services.{category}.{service}` in `infra/config/values/`, and its name to the category tuple in `toolkit/config/constants.py`.
3. Add it to the tree above.

## Related

- Edge services: `edge/` (Traefik, DNS)
- Custom apps: `infra/stacks/apps/`
- Toolkit: `toolkit/cli/services.py`
