---
id: "kubelab-runbook-pre-prod-verification"
type: runbook
status: active
tags: [runbook, kubelab, verification, production]
created: "2026-02-28"
owner: manu
---

# Pre-Production Verification Runbook

> Comprehensive verification before moving from staging to production K3s (B6 migration).
> Run this checklist in a single session. All checks must pass before proceeding.

## Phase 1: STAGE-008 Soak Test Verification

**Purpose**: Confirm 7-day soak test stability before closing STAGE-008.

### 1.1 Cluster Health

```bash
# Node status — all 3 must be Ready, no restarts in 7 days
kubectl --kubeconfig ~/.kube/kubelab-config get nodes -o wide

# Node resource usage — verify no memory pressure or disk pressure
kubectl --kubeconfig ~/.kube/kubelab-config top nodes

# All pods in kubelab namespace — must be Running, 0 restarts ideal
kubectl --kubeconfig ~/.kube/kubelab-config -n kubelab get pods -o wide

# Check for recent pod restarts (last 7 days)
kubectl --kubeconfig ~/.kube/kubelab-config -n kubelab get pods -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{range .status.containerStatuses[*]}{.restartCount}{"\t"}{end}{"\n"}{end}'

# Events — should be minimal, no warnings about OOM or evictions
kubectl --kubeconfig ~/.kube/kubelab-config -n kubelab get events --sort-by='.lastTimestamp' | tail -20
```

**Pass criteria**: All nodes Ready, all pods Running, zero OOM kills, zero evictions.

### 1.2 Application Health Checks

```bash
# Use toolkit health check (via Tailscale VPN)
tk services health --env staging

# Manual verification of each endpoint
curl -sf https://web.staging.kubelab.live -o /dev/null -w "%{http_code}\n"
curl -sf https://api.staging.kubelab.live/health -o /dev/null -w "%{http_code}\n"
curl -sf https://blog.staging.kubelab.live -o /dev/null -w "%{http_code}\n"
curl -sf https://auth.staging.kubelab.live/api/health -o /dev/null -w "%{http_code}\n"
curl -sf https://grafana.staging.kubelab.live/api/health -o /dev/null -w "%{http_code}\n"
```

**Pass criteria**: All return 200 (or 302 for auth-protected services).

### 1.3 Observability Stack

```bash
# Grafana — UI accessible, datasource connected
curl -sf https://grafana.staging.kubelab.live/api/health

# Loki — receiving logs (query last 1h)
# Via Grafana Explore → LogQL: {namespace="kubelab"} | count
# OR via API:
curl -sf "https://loki.staging.kubelab.live/loki/api/v1/query?query=count_over_time({namespace=\"kubelab\"}[1h])"

# Vector DaemonSet — running on all nodes
kubectl --kubeconfig ~/.kube/kubelab-config -n kubelab get ds vector -o wide
```

**Pass criteria**: Grafana accessible, Loki has recent logs, Vector running on all 3 nodes.

### 1.4 Security Services

```bash
# Authelia — accessible, login page renders
curl -sf https://auth.staging.kubelab.live -o /dev/null -w "%{http_code}\n"

# CrowdSec agent — running, parsing logs
kubectl --kubeconfig ~/.kube/kubelab-config -n kubelab get pods -l app=crowdsec

# CrowdSec bouncer — running as DaemonSet
kubectl --kubeconfig ~/.kube/kubelab-config -n kubelab get ds crowdsec-bouncer

# Redis — used by Authelia session store
kubectl --kubeconfig ~/.kube/kubelab-config -n kubelab get statefulset redis
```

**Pass criteria**: All security services running, no CrashLoopBackOff.

### 1.5 Automated E2E Test Suite

```bash
# Run E2E tests against staging (requires Tailscale VPN)
make test-e2e ENV=staging

# Run infrastructure health checks (SSH to all nodes)
make test-infra ENV=staging
```

**Pass criteria**: All E2E tests pass or skip with legitimate reasons (e.g., `headscale` skipped on dev, `crowdsec bouncer` skipped on dev). Zero failures.

**Expected skip reasons** (staging):
- None — all services should be testable in staging

### 1.6 Persistent Data

```bash
# PVCs — all bound
kubectl --kubeconfig ~/.kube/kubelab-config -n kubelab get pvc

# StatefulSets — all desired replicas ready
kubectl --kubeconfig ~/.kube/kubelab-config -n kubelab get statefulsets
```

**Pass criteria**: All PVCs Bound, all StatefulSets fully ready.

---

## Phase 2: CI Pipeline Verification

**Purpose**: Confirm the CI pipeline produces correct artifacts.

### 2.1 Branch State

```bash
# Only master and develop should exist
git branch -a

# develop is up to date with remote
git log --oneline -3 develop
git log --oneline -3 origin/develop
```

### 2.2 Tag Baseline

```bash
# Should be empty (clean slate after VER-001)
git tag -l

# GitHub releases should also be empty
gh release list
```

### 2.3 Trigger a Clean Build (optional, from feature branch)

```bash
# Create a minimal feature branch to test CI end-to-end
git checkout -b feature/verify-ci develop
# Make a trivial change to apps/api/
# Push and verify CI runs: validate → detect-changes → build → Docker push
# Do NOT merge — delete after verification
```

**Pass criteria**: CI pipeline runs without errors, Docker images tagged as `0.0.0-dev.{sha}`.

---

## Phase 3: Pre-Migration Checks (before PROD-K3S-001)

### 3.1 VPS Access

```bash
# SSH access
ssh user@162.55.57.175 "hostname && uname -a && df -h / && free -h"

# Docker is running
ssh user@162.55.57.175 "docker ps --format '{{.Names}}\t{{.Status}}' | sort"

# Tailscale connected
ssh user@162.55.57.175 "tailscale status"
```

### 3.2 Backups (PREP-002 + PREP-004)

```bash
# PREP-002: VPS snapshot (via Hetzner Cloud Console or API)
# Verify snapshot exists and is recent (< 24h)

# PREP-004: Docker volume backups
ssh user@162.55.57.175 "ls -la /backups/ 2>/dev/null || echo 'No backup dir'"
# Must backup: Headscale SQLite, acme.json, any app data volumes
```

### 3.3 DNS Rollback Ready

```bash
# Terraform state is valid
cd infra/terraform/dns && terraform plan -var-file=prod.tfvars 2>&1 | tail -5
# Should show "No changes. Your infrastructure matches the configuration."

# DNS TTL is 300s (set during PREP-001/PREP-003)
dig +short -t A api.kubelab.live | head -1
dig +noall +answer api.kubelab.live | awk '{print $2}'  # Should show 300
```

### 3.4 Prod Overlay Validation

```bash
# Dry-run prod overlay — must produce valid YAML
kubectl kustomize infra/k8s/overlays/prod/ > /dev/null 2>&1 && echo "OK" || echo "FAIL"

# Inspect generated resources
kubectl kustomize infra/k8s/overlays/prod/ | grep "kind:" | sort | uniq -c

# Verify prod domains in IngressRoutes
kubectl kustomize infra/k8s/overlays/prod/ | grep -A2 "rule:" | grep "Host"
```

### 3.5 Secrets Pipeline

```bash
# SOPS decryption works
tk infra k8s apply-secrets --env prod --dry-run

# All 5 secrets resolve correctly
# Expected: authelia-secrets, authelia-users, grafana-admin, crowdsec-bouncer, api-secrets
```

**Pass criteria**: All secrets resolve, no missing values.

---

## Phase 4: First Clean Release Cycle (VER-003)

**Purpose**: Validate versioning pipeline produces correct tags after master merge.

### 4.1 Process

1. Create PR: `develop → master`
2. Merge (all CI checks must pass)
3. Verify per-app tags created: `api-v0.1.0`, `blog-v0.1.0`, `web-v0.1.0`
4. Verify global release created: `v{YYYY.MM.DD}`
5. Verify Docker images tagged as stable (`:latest` + `:0.1.0`)
6. Verify GitOps update committed to `prod.yaml`

### 4.2 Verification

```bash
# Tags created
git fetch --tags && git tag -l

# Releases created
gh release list

# Docker images exist (check DockerHub)
# kubelab-api:0.1.0, kubelab-blog:0.1.0, kubelab-web:0.1.0
```

**Pass criteria**: Tags follow `{app}-v{version}` convention, release follows `v{YYYY.MM.DD}`, Docker images tagged correctly.

---

## Decision Log

| Check | Status | Date | Notes |
|-------|--------|------|-------|
| STAGE-008 soak test (7 days) | | | |
| CI pipeline clean run | | | |
| VPS snapshot (PREP-002) | | | |
| Docker volume backups (PREP-004) | | | |
| DNS TTL 300s verified | | | |
| Prod overlay dry-run | | | |
| Secrets dry-run | | | |
| First clean release cycle | | | |
