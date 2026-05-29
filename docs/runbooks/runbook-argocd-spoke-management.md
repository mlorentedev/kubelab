---
id: runbook-argocd-spoke-management
type: runbook
status: active
created: "2026-03-23"
owner: manu
---

# Argo CD Spoke Management

> Register, rotate, and recover spoke clusters in the Argo CD hub.

## Architecture

```
Hub (aws1, 100.64.0.4)          Spokes (via Tailscale VPN)
┌──────────────────┐            ┌──────────────────┐
│ Argo CD          │──push──>   │ staging (ace1)   │
│ argocd namespace │            │ 100.64.0.11:6443 │
│                  │            └──────────────────┘
│ cluster-staging  │            ┌──────────────────┐
│ cluster-prod     │──push──>   │ prod (VPS)       │
│ (Secrets)        │            │ 100.64.0.2:6443  │
└──────────────────┘            └──────────────────┘
```

**Security model**: Scoped RBAC (NOT cluster-admin). Argo CD can only manage resources in the `kubelab` namespace. Cluster-wide access is read-only (namespaces, nodes, CRDs).

**SSOT**: Spoke API server URLs defined in `argocd.spokes` in `infra/config/values/common.yaml`.

## Operations

### Register a spoke

```bash
make register-spoke ENV=staging   # or ENV=prod
```

What it does:
1. Applies `infra/k8s/argocd/spoke-rbac.yaml` to the spoke (SA + RBAC + token)
2. Waits for K8s to populate the token Secret
3. Verifies RBAC scoping (can-i checks)
4. Extracts token + CA cert from spoke
5. Reads API server URL from common.yaml (SSOT)
6. Creates cluster Secret in hub's `argocd` namespace

### Unregister a spoke

```bash
make unregister-spoke ENV=staging
```

Removes hub cluster Secret + spoke RBAC resources.

### Check spoke health

```bash
make check-spokes
```

Verifies each registered spoke is reachable from the workstation. Note: checks from workstation, not from hub — if workstation can reach spokes via Tailscale, hub can too.

### Rotate spoke token

```bash
make rotate-spoke-token ENV=prod
```

Deletes the token Secret on the spoke, recreates it, and re-registers on hub. Zero downtime for workloads.

## Disaster Recovery

### Hub lost (Spot termination, AWS outage)

**Impact**: No GitOps reconciliation. Spokes keep running current state.

**Manual fallback** (immediate):
```bash
make deploy-k8s ENV=prod      # Direct kubectl, bypasses Argo CD
make deploy-k8s ENV=staging
```

**Full recovery** (when AWS available):
```bash
make tf-aws-apply             # Recreate Spot instance
# Wait ~5 min for cloud-init (K3s + Tailscale)
make fetch-kubeconfig-hub     # Get new kubeconfig
make deploy-argocd            # Reinstall Argo CD
make register-spoke ENV=staging
make register-spoke ENV=prod
```

Spoke RBAC persists — no need to re-provision spoke nodes.

### Spoke rebuilt (re-provisioned node)

```bash
make register-spoke ENV=staging   # Re-applies RBAC + new token
```

The old cluster Secret on hub gets overwritten (kubectl apply is idempotent).

### Stale token (spoke CA changed)

Symptom: Argo CD shows `x509: certificate signed by unknown authority`.

```bash
make rotate-spoke-token ENV=prod
```

## Files

| File | Purpose |
|------|---------|
| `infra/k8s/argocd/spoke-rbac.yaml` | SA + ClusterRoles + Bindings + Token Secret |
| `infra/k8s/argocd/cluster-secret.yaml.tpl` | Template for hub cluster Secret (sed-substituted) |
| `infra/config/values/common.yaml` | SSOT for spoke API server URLs (`argocd.spokes`) |
| `Makefile` | Targets: register-spoke, unregister-spoke, check-spokes, rotate-spoke-token |
