---
id: pvc-backup-restore
type: runbook
status: active
created: "2026-03-21"
owner: manu
---


# PVC Backup & Restore Runbook

> Ref: ADR-024. Prod only.

## Architecture

CronJob `pvc-backup` runs daily at 03:00 UTC. Backs up gitea-data, n8n-data, authelia-data to MinIO bucket `kubelab-backups` with 7-day retention.

SQLite databases use `sqlite3 .backup` for application-consistent snapshots.

## Backup

### Automatic (daily)

CronJob runs automatically. No action needed.

### Manual trigger

```sh
make backup-pvc ENV=prod
```

### Monitor backup status

```sh
# Check recent jobs
kubectl get jobs -n kubelab --kubeconfig ~/.kube/kubelab-prod-config

# Check CronJob schedule
kubectl get cronjob pvc-backup -n kubelab --kubeconfig ~/.kube/kubelab-prod-config

# View backup logs
kubectl logs job/pvc-backup-manual-TIMESTAMP -n kubelab --kubeconfig ~/.kube/kubelab-prod-config
```

### List backups in MinIO

```sh
# Using mc from any machine with MinIO access
mc alias set prod-minio https://minio.kubelab.live MINIO_ROOT_USER MINIO_ROOT_PASSWORD
mc ls prod-minio/kubelab-backups/gitea/
mc ls prod-minio/kubelab-backups/authelia/
mc ls prod-minio/kubelab-backups/n8n/
```

## Restore

### Prerequisites

- kubectl access to prod cluster
- MinIO root credentials (from SOPS: `toolkit secrets show apps.services.data.minio --env prod`)

### Procedure

**1. Identify the backup to restore**

```sh
mc ls prod-minio/kubelab-backups/gitea/
# Example output:
# [2026-03-21] gitea-2026-03-21.tar.gz
# [2026-03-22] gitea-2026-03-22.tar.gz
```

**2. Scale down the service**

```sh
KUBECONFIG=~/.kube/kubelab-prod-config
SERVICE=gitea  # or: authelia, n8n
kubectl scale deploy $SERVICE --replicas=0 -n kubelab --kubeconfig $KUBECONFIG
kubectl wait --for=delete pod -l app.kubernetes.io/name=$SERVICE -n kubelab --kubeconfig $KUBECONFIG --timeout=60s
```

**3. Run restore Job**

```sh
DATE=2026-03-21  # backup date to restore
PVC=gitea-data   # PVC name

kubectl run restore-$SERVICE --image=alpine:3.21 --restart=Never \
  --namespace=kubelab --kubeconfig $KUBECONFIG \
  --overrides='{
    "spec": {
      "containers": [{
        "name": "restore",
        "image": "alpine:3.21",
        "command": ["sh", "-c",
          "apk add --no-cache sqlite > /dev/null 2>&1 && ARCH=$(uname -m | sed \"s/x86_64/amd64/;s/aarch64/arm64/\") && wget -q https://dl.min.io/client/mc/release/linux-${ARCH}/mc -O /usr/local/bin/mc && chmod +x /usr/local/bin/mc && mc alias set backup http://minio:9000 $MINIO_ROOT_USER $MINIO_ROOT_PASSWORD && mc cp backup/kubelab-backups/'$SERVICE'/'$SERVICE'-'$DATE'.tar.gz /tmp/ && rm -rf /restore/* && tar xzf /tmp/'$SERVICE'-'$DATE'.tar.gz -C /restore/ && echo Restore complete"
        ],
        "env": [
          {"name": "MINIO_ROOT_USER", "valueFrom": {"secretKeyRef": {"name": "minio-secrets", "key": "MINIO_ROOT_USER"}}},
          {"name": "MINIO_ROOT_PASSWORD", "valueFrom": {"secretKeyRef": {"name": "minio-secrets", "key": "MINIO_ROOT_PASSWORD"}}}
        ],
        "volumeMounts": [{"name": "data", "mountPath": "/restore"}]
      }],
      "volumes": [{"name": "data", "persistentVolumeClaim": {"claimName": "'$PVC'"}}],
      "restartPolicy": "Never"
    }
  }'
```

**4. Wait for restore to complete**

```sh
kubectl wait --for=condition=Ready pod/restore-$SERVICE -n kubelab --kubeconfig $KUBECONFIG --timeout=300s
kubectl logs restore-$SERVICE -n kubelab --kubeconfig $KUBECONFIG
```

**5. Cleanup and scale up**

```sh
kubectl delete pod restore-$SERVICE -n kubelab --kubeconfig $KUBECONFIG
kubectl scale deploy $SERVICE --replicas=1 -n kubelab --kubeconfig $KUBECONFIG
```

**6. Verify service health**

```sh
kubectl get pods -l app.kubernetes.io/name=$SERVICE -n kubelab --kubeconfig $KUBECONFIG
# Check the service URL in browser
```

## Troubleshooting

### Backup job fails with "mc: command not found"

MinIO CDN unreachable. The job will retry (backoffLimit: 2). If persistent, check network from VPS.

### Backup job fails with "database is locked"

SQLite .backup should handle concurrent access. If this occurs, the service may have an exclusive lock. Try again outside peak hours or restart the service first.

### PVC mount fails on CronJob

RWO PVCs can only mount on one node. Verify the CronJob pod is scheduled on the same node as the service pods:

```sh
kubectl get pods -n kubelab -o wide --kubeconfig $KUBECONFIG
```

### Restore produces corrupted data

The tar includes the sqlite3 .backup copy, which is consistent. If data appears corrupted after restore, verify you're restoring the correct date and that the service was fully stopped before restore.

## What is NOT backed up

| Data | Reason | Mitigation |
|------|--------|------------|
| minio-data | Circular (backup target = source) | Hetzner VPS snapshots. Phase 5: Velero + B2 |
| grafana-data | Dashboards in ConfigMap, regenerable | Re-deploy via kustomize |
| loki-data | Logs, not critical | Accept data loss |
| crowdsec-db/config | Regenerable on restart | CrowdSec re-syncs hub data |
