---
id: "kubelab-troubleshooting-deployment"
type: troubleshooting
status: active
tags: [troubleshooting, kubelab]
created: "2026-02-08"
owner: manu
---

# Deployment Issues

Problems related to deploying KubeLab services to staging and production environments.

## Deploy Fails

### Problem

Deployment process fails to complete successfully.

### Diagnostic Steps

```bash
# Check server connection
ssh mlorente-prod "docker ps"

# Check environment on server
ssh mlorente-prod "cat /opt/kubelab.live/.env.production"
```

### Solution

```bash
# Manual deploy
ssh mlorente-prod
cd /opt/kubelab.live
git pull
make deploy ENV=production
```

### Prevention

- Always verify SSH connectivity before triggering deploys
- Keep deployment credentials and SSH keys up to date
- Test deploys in staging before production

## Services Down After Deploy

### Problem

One or more services fail to start or become unhealthy after a deployment.

### Diagnostic Steps

```bash
# Check pod and deployment status in the kubelab namespace
poetry run toolkit infra k8s status --env prod

# View service logs (Loki keeps history across pod restarts)
poetry run toolkit obs logs --env prod --service api
```

### Solution

```bash
# Restart specific service
make restart-service SVC=api ENV=prod
```

To roll back, revert the deploy or promotion PR's merge commit on `master`. Argo CD then reconciles the env back to the previous immutable tag. See `docs/runbooks/gitops-delivery-promotion.md`, section Rollback. No make target does this: the rollback is a git change, so it is reviewed like any other.

### Prevention

- Implement health checks on all services
- Use blue-green or rolling deployment strategies
- Always have a rollback plan tested and ready

## CrowdSec Agent CrashLoopBackOff — "No Datasource Enabled"

### Root Cause

CrowdSec agent exits fatally on startup when `acquis.yaml` contains no active datasource entries. A config file with only YAML comments is equivalent to an empty file — CrowdSec treats it as misconfigured and refuses to start.

```
level=fatal msg="no datasource enabled"
```

### Solution

Ensure `acquis.yaml` has at least one active (non-commented) datasource block. A safe default is a `filePath` source paired with an `emptyDir` volume:

```yaml
# acquis.yaml ConfigMap
filenames:
  - /var/log/traefik/access.log
labels:
  type: traefik
---
source: file
```

```yaml
# Deployment: mount emptyDir so the path exists even if no logs yet
volumes:
  - name: traefik-logs
    emptyDir: {}
volumeMounts:
  - name: traefik-logs
    mountPath: /var/log/traefik
```

### Prevention

- Always validate `acquis.yaml` has at least one uncommented datasource before applying.
- When deploying CrowdSec before Traefik log forwarding is configured, use an `emptyDir` volume at the log path so the agent starts successfully and begins processing once logs appear.

---

## Emergency Procedures

### Complete System Down (local dev stack)

```bash
# Quick restart
make down-dev && make up-dev

# Nuclear option: stop the stack, then prune EVERY unused Docker volume and
# container on this host (`docker volume prune -f`), not only the dev stack's
make dev-full-clean && make up-dev
```

### Rollback Deployment

Revert the deploy or promotion PR's merge commit on `master`. Argo CD reconciles back to the previous tag (`docs/runbooks/gitops-delivery-promotion.md`, section Rollback).

### Restore from Backup

Node backups are restic snapshots in Cloudflare R2, not a tarball. Restore one with `docs/runbooks/offsite-backup-restore.md`, section "Restoring — normal case".

### Emergency Contacts

- Production down: Follow emergency procedures above first
- Security incident: Rotate credentials immediately, investigate logs
- Data loss: Restore from latest backup (see Runbooks)
