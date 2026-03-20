# Applications — Source Code

Custom applications deployed on KubeLab infrastructure.

## Structure

```
apps/
├── api/           Go REST API (backend services)
└── web/           Astro portfolio site (frontend)
```

Error pages live in `edge/errors/` (edge service, not an app).

## Development

```bash
# Start local dev environment
make dev

# Build a specific app
poetry run toolkit services build web
```

## Configuration

Environment configuration is centralized in `infra/config/`:

- **Values**: `infra/config/values/{common,dev,staging,prod}.yaml`
- **Secrets**: `infra/config/secrets/{env}.enc.yaml` (SOPS-encrypted)

## Deployment

- **Staging (K3s)**: `make deploy-k8s ENV=staging` — Kustomize manifests
- **Production (VPS)**: Docker Compose via Ansible (`make deploy TARGET=vps ENV=prod`)

See each app's README for app-specific documentation.
