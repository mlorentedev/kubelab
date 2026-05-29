---
id: "kubelab-runbook-new-service"
type: runbook
status: active
tags: [runbook, kubelab]
created: "2026-02-09"
owner: manu
---

# Adding a New Service

## Overview

End-to-end procedure for adding a new third-party service to KubeLab. Covers compose files, configuration, secrets, Traefik routing, and verification.

## Prerequisites

- Local environment working (`make up-dev` succeeds)
- SOPS configured (see [sops-and-secrets](sops-and-secrets.md))
- Understanding of the service category (core, observability, security, data, misc, ai)

## Steps

### 1. Create service directory

```bash
# Pick the right category
CATEGORY=observability   # core | observability | security | data | misc | ai
SERVICE=prometheus

mkdir -p infra/stacks/services/$CATEGORY/$SERVICE
```

### 2. Create compose files

```bash
cd infra/stacks/services/$CATEGORY/$SERVICE
```

**compose.base.yml** — service defaults (image, networks, restart policy):

```yaml
services:
  prometheus:
    image: prom/prometheus:v2.51.0
    container_name: prometheus
    restart: unless-stopped
    networks:
      - kubelab

networks:
  kubelab:
    external: true
```

**compose.dev.yml** — dev overrides (ports, volumes, relaxed settings):

```yaml
services:
  prometheus:
    ports:
      - "9090:9090"
    volumes:
      - prometheus-data:/prometheus
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.prometheus.rule=Host(`prometheus.kubelab.test`)"

volumes:
  prometheus-data:
```

**compose.staging.yml** and **compose.prod.yml** — same pattern with environment-specific domains.

### 3. Add configuration values

Edit `infra/config/values/common.yaml`:

```yaml
apps:
  prometheus:
    name: prometheus
    # Add common config here
```

Edit `infra/config/values/dev.yaml`:

```yaml
apps:
  prometheus:
    host: prometheus.kubelab.test
    port: 9090
```

Repeat for `staging.yaml` and `prod.yaml` with appropriate domains.

### 4. Add secrets (if needed)

```bash
# Generate secret values
python3 -c "import secrets; print(secrets.token_urlsafe(32))"

# Edit SOPS file
sops infra/config/secrets/dev.enc.yaml

# Add under the right path:
# apps:
#   services:
#     observability:
#       prometheus:
#         admin_password: "generated_value"
```

### 5. Add local DNS entry

Edit the Makefile `setup-local-dns` target to include the new domain:

```bash
echo "127.0.0.1 prometheus.kubelab.test" | sudo tee -a /etc/hosts
```

Or re-run: `make setup-local-dns` (after updating the Makefile).

### 6. Regenerate configs

```bash
make config-generate
make validate
```

### 7. Test locally

```bash
# Build and start
toolkit services up $SERVICE --env dev

# Verify container is running
docker ps --filter "name=$SERVICE"

# Check logs
toolkit services logs $SERVICE

# Test HTTP endpoint
curl -v https://$SERVICE.kubelab.test
```

### 8. Update documentation

- Add service to `infra/stacks/services/README.md` under the correct category
- Add to `up-dev` / `down-dev` targets in Makefile if it should start by default
- Update `apps/README.md` if it's a user-facing service

## Verification

```bash
# Container healthy
docker ps --filter "name=$SERVICE" --format "{{.Names}} {{.Status}}"

# Traefik routing works
curl -sI https://$SERVICE.kubelab.test | head -1

# Logs clean (no errors)
toolkit services logs $SERVICE --no-follow | tail -20
```

## Rollback

```bash
# Stop and remove
toolkit services down $SERVICE --env dev

# Remove compose files
rm -rf infra/stacks/services/$CATEGORY/$SERVICE

# Remove from values/*.yaml and secrets
# Revert Makefile DNS changes
# Regenerate: make config-generate
```

## Checklist

- [ ] Compose files created (base + dev + staging + prod)
- [ ] Values added to `common.yaml` and env-specific `*.yaml`
- [ ] Secrets in SOPS (if needed)
- [ ] Local DNS entry added
- [ ] `make config-generate && make validate` passes
- [ ] Container starts and responds
- [ ] Traefik routes correctly
- [ ] Documentation updated

## Last tested

2026-02-09
