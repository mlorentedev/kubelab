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
# Check container status
make status ENV=production

# View service logs
toolkit apps logs api -f
```

### Solution

```bash
# Restart specific service
make restart APP=api ENV=production

# Emergency rollback
make emergency-rollback ENV=production
```

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

### Complete System Down

```bash
# Quick restart
make down && make up

# Nuclear option (kills all containers)
docker kill $(docker ps -q)
docker rm $(docker ps -aq)
make clean && make up
```

### Rollback Deployment

```bash
make emergency-rollback ENV=production
```

### Restore from Backup

```bash
make restore BACKUP=backup-<date>.tar.gz ENV=production
```

### Emergency Contacts

- Production down: Follow emergency procedures above first
- Security incident: Rotate credentials immediately, investigate logs
- Data loss: Restore from latest backup (see Runbooks)
