# Applications — Source Code

Custom applications deployed on KubeLab infrastructure.

## Structure

```
apps/
├── api/           Go REST API (backend services)
└── wiki/          Generated docs output (not an app)
```

Error pages live in `edge/errors/` (edge service, not an app).
The web app was extracted to its own repository (ADR-053); its images arrive via the `web-image-receiver` workflow.

## Development

```bash
# Start local dev environment
make up-dev

# Build a specific app
poetry run toolkit services build api
```

## Configuration

Environment configuration is centralized in `infra/config/`:

- **Values**: `infra/config/values/{common,dev,staging,prod}.yaml`
- **Secrets**: `infra/config/secrets/{env}.enc.yaml` (SOPS-encrypted)

## Deployment

- **Staging (K3s)**: `make deploy-k8s ENV=staging` — Kustomize manifests
- **Production (K3s on VPS)**: promoted via Argo CD — see `docs/runbooks/gitops-delivery-promotion.md`

See each app's README for app-specific documentation.
