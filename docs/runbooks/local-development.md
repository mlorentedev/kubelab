---
id: "kubelab-runbook-local-development"
type: runbook
status: active
tags: [runbook, kubelab]
created: "2026-02-08"
owner: manu
---

# Local Development

## Overview

Set up and manage the KubeLab local development environment. All services run on Docker with Traefik routing and local TLS certificates (mkcert).

## Prerequisites

- Docker and Docker Compose installed
- Python 3.12+ with Poetry
- `make` available
- `mkcert` for local TLS (installed via `make setup-certs`)

## Initial Setup (first time only)

```bash
# 1. Install toolkit and dependencies
make setup

# 2. Configure local DNS (/etc/hosts)
make setup-local-dns

# 3. Install local TLS certificates
make setup-certs

# 4. Generate credentials (Authelia, Grafana, MinIO, etc.)
make credentials-generate

# 5. Generate all configuration files
make config-generate

# 6. Validate everything
make validate
```

## Local Domains

After `make setup-local-dns`, these domains resolve to `127.0.0.1`.
**Domains are declared in `DEV_DOMAINS` in the Makefile** — add new services there.

| Domain | Service | Auth |
|--------|---------|------|
| `mlorente.test` | Personal website (web) | — |
| `api.kubelab.test` | Go API | — |
| `blog.kubelab.test` | Jekyll blog | — |
| `traefik.kubelab.test` | Traefik dashboard | Authelia |
| `grafana.kubelab.test` | Grafana | Authelia |
| `auth.kubelab.test` | Authelia SSO | — |
| `portainer.kubelab.test` | Portainer (Docker UI) | Portainer own |
| `gitea.kubelab.test` | Gitea (Git server) | Gitea own |
| `n8n.kubelab.test` | n8n (workflow automation) | n8n own |
| `status.kubelab.test` | Uptime Kuma | — |
| `minio.kubelab.test` | MinIO S3 API | MinIO root creds |
| `console.minio.kubelab.test` | MinIO web console | MinIO root creds |
| `loki.kubelab.test` | Loki logs | Authelia |
| `crowdsec.kubelab.test` | CrowdSec (internal) | — |

> **Note:** `console.minio.kubelab.test` requires an explicit SAN in the TLS cert (wildcards only cover one subdomain level). Run `make regen-certs` if you see a cert error.

## First-Run Service Setup

Some services require a one-time manual setup after first start:

### Portainer
Visit `https://portainer.kubelab.test` → set admin password in the welcome screen (must be done within 5 minutes of first start, or restart the container).

### Gitea
On first start, the `GITEA_ADMIN_*` env vars only work if no DB exists yet. If the volume was pre-existing:

```bash
docker exec --user git gitea gitea admin user create \
  --admin --username admin --password 645610515 \
  --email mlorentedev@gmail.com --must-change-password=false
```

### n8n
Visit `https://n8n.kubelab.test` → create owner account on first login. The encryption key is set via `APPS_SERVICES_CORE_N8N_ENCRYPTION_KEY` — do not change it after creating credentials.

### MinIO
Visit `https://console.minio.kubelab.test` → login with root credentials from SOPS (`apps.services.data.minio.root_user` / `root_password`).

## Daily Usage

### Start full environment

```bash
make up-dev
# Starts: blog, api, web, nginx, portainer, gitea, n8n, uptime, loki,
#         grafana, authelia, crowdsec, minio, github-runner, traefik
```

### Start individual services

```bash
toolkit services up web
toolkit services up api
toolkit services up grafana
```

### View logs

```bash
toolkit services logs web
toolkit services logs api --no-follow
toolkit services logs traefik
```

### Stop everything

```bash
make down-dev
```

### Stop individual services

```bash
toolkit services down web
toolkit services down grafana
```

## Build Images

```bash
# Build all custom apps (blog, api, web)
make build-dev

# Build individual app
toolkit services build web --env dev --no-cache
```

## Rebuild from Scratch

```bash
# Stop all and remove volumes
make down-dev

# Clean Docker (careful: removes ALL Docker data)
docker system prune -af --volumes

# Regenerate credentials and configs
make credentials-generate
make config-generate

# Build and start
make build-dev
make up-dev
```

## Configuration Changes

When you modify `infra/config/values/*.yaml`:

```bash
# Regenerate all configs (Traefik, Authelia, etc.)
make config-generate

# Validate
make validate

# Restart affected services
toolkit services down web && toolkit services up web
```

## Add a New Local Domain

1. Edit the `setup-local-dns` target in `Makefile`
2. Run `make setup-local-dns`
3. Verify: `grep kubelab /etc/hosts`

## Verification

```bash
# All containers running
docker ps --format "table {{.Names}}\t{{.Status}}"

# No unhealthy containers
docker ps --filter "health=unhealthy" --format "{{.Names}}"

# HTTP smoke tests
curl -sk https://mlorente.test | head -1
curl -sk https://api.kubelab.test/health
curl -sk https://blog.kubelab.test | head -1
curl -sk https://traefik.kubelab.test/dashboard/ | head -1
```

## Troubleshooting

### "Service directory not found"

Check compose files exist:

```bash
ls infra/stacks/apps/web/
# Should show: compose.base.yml, compose.dev.yml
```

### "Configuration file not found"

Regenerate configs:

```bash
make config-generate
make validate
```

### Containers restarting

Check logs:

```bash
toolkit services logs <service-name>
docker inspect <container-name> --format '{{.State.ExitCode}}'
```

### Permission denied on bind mounts

Docker containers running as root create files owned by root. Fix:

```bash
sudo find apps/ -user root -exec chown $USER:$USER {} +
```

Dev compose files include `user: "${UID:-1000}:${GID:-1000}"` to prevent this.

## Rollback

Stop all services and clean Docker state:

```bash
make down-dev
docker system prune -af --volumes
```

Then re-run the initial setup steps.

## Add a New Service (checklist)

When adding a new Docker Compose service to dev:

1. `infra/stacks/services/<category>/<name>/compose.base.yml` — base config
2. `infra/stacks/services/<category>/<name>/compose.dev.yml` — dev overrides
3. `infra/config/values/common.yaml` — add service entry with name, image, domain, port, health_path
4. `infra/config/values/dev.yaml` — add domain override and any dev-specific config
5. `toolkit/config/constants.py` — add to appropriate `SERVICES_*` list if not already there
6. `Makefile` — add domain to `DEV_DOMAINS`, add service to `up-dev` / `down-dev` lists
7. `make setup-local-dns` — adds missing DNS entries automatically
8. `make regen-certs` — required if domain has two subdomain levels (e.g. `console.service.kubelab.test`)
9. SOPS — add any secrets to `infra/config/secrets/dev.enc.yaml` via `sops`
10. Document first-run steps above if service needs manual setup

## Last tested

2026-02-25
