---
id: "kubelab-runbook-deployment"
type: runbook
status: active
tags: [runbook, kubelab]
created: "2026-02-08"
updated: "2026-02-27"
owner: manu
---

# Deployment

> **Current state (2026-02-28):**
> - **Staging**: K3s cluster (3 nodes). Deploy via `kubectl apply -k infra/k8s/overlays/staging/`
> - **Production**: Docker Compose on VPS (162.55.57.175). Migrating to K3s in B6
> - After B6 migration, production will also use K8s manifests + kustomize overlays
>
> **Release flow** (Gitflow): verify staging → PR develop→master → merge (creates tags + release) → deploy to prod with stable images
>
> **Pre-prod verification**: See [pre-prod-verification](pre-prod-verification.md) runbook for comprehensive checklist.
>
> The Docker Compose procedures below are **current for VPS production**. K8s procedures are in [k3s-setup](k3s-setup.md) and the kustomize overlay docs.

## Overview

Deploy new versions of KubeLab to staging and production environments using the toolkit CLI, verify deployment status, and perform emergency rollbacks.

## Prerequisites

- SSH access to target environment (staging homelab or production VPS)
- Toolkit installed and configured (`make setup`)
- Configuration generated for the target environment
- SOPS keys available for secret decryption
- Access to kubelab.live endpoints for verification

## Steps

### 1. Pre-deployment checklist

Before deploying, ensure configuration is up to date and valid:

```bash
# Generate configuration for the target environment
ENVIRONMENT=staging toolkit config generate
# or
ENVIRONMENT=prod toolkit config generate

# Validate configuration (checks values/*.yaml + compose overlay resolution)
make validate
```

### 2. Deploy to staging (MiniPC B via Tailscale)

Staging runs on MiniPC B (`kubelab-ace-staging`), accessible via Tailscale VPN.

```bash
# Via Ansible (recommended)
cd infra/ansible/generated/staging
ansible-playbook -i hosts.yml playbooks/deploy.yml

# Or via toolkit
ENVIRONMENT=staging toolkit deployment deploy

# Check deployment status
ENVIRONMENT=staging toolkit deployment status
```

**Deployment order** (dependencies):

1. Docker network + volumes (prerequisites)
2. Traefik + Nginx (edge — TLS termination)
3. Authelia + Redis (SSO — others depend on it)
4. CrowdSec + Bouncer (WAF — integrates with Traefik)
5. Apps: API, Web, Blog (pull from Docker Hub)
6. Observability: Grafana, Loki + Vector, Uptime Kuma
7. Core: Portainer
8. Data: MinIO

### 3. Verify staging

```bash
# Verify staging endpoints (accessible via Tailscale)
curl -f https://web.staging.kubelab.live
curl -f https://api.staging.kubelab.live/health
curl -f https://blog.staging.kubelab.live
curl -f https://auth.staging.kubelab.live/api/health
curl -f https://grafana.staging.kubelab.live/api/health

# View service logs if needed
ENVIRONMENT=staging toolkit services logs web
ENVIRONMENT=staging toolkit services logs api
```

### 4. Deploy to production

Once staging is verified, deploy to production:

```bash
# Full deployment pipeline to production
ENVIRONMENT=prod toolkit deployment deploy

# Or via Makefile shortcut
make deploy-prod
```

### 5. Verify production

```bash
# Check deployment status
ENVIRONMENT=prod toolkit deployment status

# Verify production endpoints
curl -f https://mlorente.dev
curl -f https://api.kubelab.live/health
curl -f https://blog.kubelab.live

# View container status
ENVIRONMENT=prod toolkit services logs web --no-follow
ENVIRONMENT=prod toolkit services logs api --no-follow
```

## Verification

```bash
# Production health checks
curl -f https://mlorente.dev
curl -f https://api.kubelab.live/health
curl -f https://blog.kubelab.live

# Deployment status
ENVIRONMENT=prod toolkit deployment status
```

## Rollback

### Quick rollback (restart previous containers)

```bash
# Restart specific service with previous image
ENVIRONMENT=prod toolkit services down web
ENVIRONMENT=prod toolkit services up web

# Or restart all services
ENVIRONMENT=prod toolkit services down web api blog
ENVIRONMENT=prod toolkit services up web api blog
```

### Manual rollback (deploy previous known-good version)

```bash
# Check git tags for previous versions
git tag --sort=-version:refname | head -5

# Checkout previous version and redeploy
git checkout <previous-tag>
ENVIRONMENT=prod toolkit config generate
ENVIRONMENT=prod toolkit deployment deploy
```

### Emergency rollback (SSH direct)

If the toolkit is unavailable, SSH to the server and use Docker directly:

```bash
ssh user@162.55.57.175

# Stop broken service
docker compose -f infra/stacks/apps/web/compose.base.yml \
  -f infra/stacks/apps/web/compose.prod.yml down

# Pull previous image and restart
docker compose -f infra/stacks/apps/web/compose.base.yml \
  -f infra/stacks/apps/web/compose.prod.yml up -d
```

## Last tested

2026-02-09
