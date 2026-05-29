---
id: rollback-k3s-to-compose
type: runbook
status: active
created: "2026-03-22"
owner: manu
---

# Rollback: K3s → Docker Compose on VPS

> **PROD-K3S-006** — Emergency procedure to revert VPS from K3s to Docker Compose if K3s becomes unrecoverable.

## When to use

- K3s is down and won't restart after troubleshooting
- K3s Traefik is broken and services are unreachable
- Cluster corruption that can't be fixed quickly
- **NOT** for temporary outages — K3s self-heals most issues within minutes

## Pre-conditions

- SSH access to VPS (`ssh manu@162.55.57.175`) — uses public IP, not Tailscale
- Headscale is still running in Docker Compose (ADR-015 — never part of K3s)
- ACME certificates exist at `/opt/traefik/certs/acme.json` (preserved from pre-cutover)
- Docker Compose config exists at `/opt/traefik/docker-compose.yml`

## Critical warnings

- **Headscale must NEVER be stopped** — all VPN nodes depend on it
- **ACME rate limit**: Let's Encrypt allows 5 certs per domain set per 168h. Don't delete `acme.json`
- **Data loss risk**: K3s PVCs (authelia, gitea, grafana, minio, n8n, loki) are on local storage. Back up before uninstalling K3s
- **Downtime**: Expect 5-15 minutes total

## Procedure

### Step 1: Assess and back up

```bash
# SSH to VPS
ssh manu@162.55.57.175

# Check K3s status
sudo systemctl status k3s
sudo k3s kubectl get nodes
sudo k3s kubectl get pods -n kubelab

# Back up PVCs (if K3s is partially functional)
make backup-pvc ENV=prod

# Back up etcd snapshot
sudo k3s etcd-snapshot save --name emergency-rollback
```

### Step 2: Stop K3s (free ports 80/443)

```bash
# Stop K3s service — Traefik releases ports 80/443
sudo systemctl stop k3s
sudo systemctl disable k3s

# Verify ports are free
sudo ss -tlnp | grep -E ':80 |:443 '
# Should show nothing — if still bound, wait 10s and retry
```

### Step 3: Remove VPS from k3s_servers group

Edit `infra/config/values/prod.yaml` on your workstation:

```yaml
networking:
  vps:
    ansible_groups: ["docker_hosts"]  # Remove "k3s_servers"
```

Regenerate Ansible inventory:

```bash
make generate-config ENV=prod
```

This makes `deploy-vps` run the traefik_vps and errors roles again (the `when: "'k3s_servers' not in group_names"` condition).

### Step 4: Deploy Docker Compose stack

```bash
# From workstation — deploys Traefik + errors via Ansible
make deploy TARGET=vps ENV=prod
```

This will:
- Start Docker Compose Traefik on ports 80/443
- Deploy error pages container
- Configure all service routes (api, web, n8n, grafana, etc.)
- Headscale route is already in the Traefik config

### Step 5: Verify services

```bash
# Quick health check from workstation
curl -sI https://api.kubelab.live | head -5
curl -sI https://vpn.kubelab.live | head -5
curl -sI https://auth.kubelab.live | head -5

# Full E2E suite
make test-e2e ENV=prod
```

### Step 6: Verify Headscale connectivity

```bash
# Headscale should still be running (never stopped)
ssh manu@162.55.57.175 "docker inspect --format '{{.State.Health.Status}}' headscale"
# Expected: healthy

# Verify VPN mesh from workstation
tailscale status
```

## Rollback the rollback (return to K3s)

Once the root cause is fixed:

1. Restore `k3s_servers` in prod.yaml ansible_groups
2. `sudo systemctl enable k3s && sudo systemctl start k3s`
3. Wait for pods to come up: `kubectl get pods -n kubelab -w`
4. Docker Compose Traefik will be skipped on next `make deploy TARGET=vps ENV=prod`
5. Verify: `make test-e2e ENV=prod`

## Services inventory

| Service | K3s (normal) | Docker Compose (rollback) |
|---------|-------------|--------------------------|
| Traefik | K3s bundled (80/443) | Docker Compose (80/443) |
| API, Web | K3s Deployment | Docker container |
| Authelia | K3s Deployment | Docker container |
| Gitea, n8n, MinIO | K3s Deployment | Docker container |
| Grafana, Loki | K3s Deployment | Docker container |
| CrowdSec | K3s Deployment | Not available (security gap) |
| Headscale | Docker Compose always | Docker Compose always |
| Error pages | K3s Deployment | Docker container (Ansible errors role) |

## Known gaps in rollback mode

- **CrowdSec** not available in Docker Compose — no DDoS protection
- **OIDC SSO** won't work — Authelia config differs between K3s and Docker Compose
- **PVC data** may not be available to Docker containers (different storage paths)
- **Monitoring** (Grafana/Loki/Vector) requires separate Docker Compose setup

## Related

- ADR-015: Headscale stays in Docker Compose (bootstrap dependency)
- ADR-020: IaC lifecycle — Pattern C side-by-side migration
- ADR-023: Hub-and-Spoke Multi-Cloud GitOps
- `40-runbooks/pvc-backup-restore.md`: PVC backup/restore procedure
