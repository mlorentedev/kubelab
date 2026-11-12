---
id: "runbook-deploy-k3s-service"
type: runbook
status: active
tags: [k3s, deployment, services, staging]
owner: manu
created: "2026-03-28"
---

# Runbook: Deploy a New Service to K3s Staging

> Step-by-step guide for adding a new service to the KubeLab K3s staging cluster.
> Created during the Gitea and n8n deployments in Feb 2026.

## Prerequisites

- [ ] SOPS access configured (`make secrets-audit` decrypts every env vault and lists missing keys; a vault it cannot decrypt reads as every key missing)
- [ ] K3s cluster access via kubeconfig (`~/.kube/kubelab-staging-config`)
- [ ] DNS wildcard `*.staging.kubelab.live` resolves to K3s ingress (100.64.0.4 via CoreDNS)
- [ ] Authelia running and healthy on the cluster
- [ ] Traefik running with CrowdSec bouncer middleware available
- [ ] Decide auth tier for the service (see ADR-016):
  - **OIDC** (Tier 1): Service has native OIDC support (e.g., Gitea, Grafana)
  - **Forward Auth** (Tier 2): No OIDC support, use Authelia middleware (e.g., N8N, Grafana)
  - **Bypass** (Tier 3): Public endpoint, no auth needed (e.g., API, web)

## Steps

### 1. Add Secrets to SOPS

If the service requires secrets (credentials, API keys, OIDC client secrets):

```bash
# Edit staging secrets
toolkit secrets edit --env staging

# Add secrets under the appropriate path:
# apps.services.<category>.<service>.*
# Example for gitea:
# apps.services.platform.gitea.db_password: "..."
# apps.services.platform.gitea.oidc_client_secret: "..."
```

Register every new key in `SECRET_CATALOG` (`toolkit/features/secrets_manager.py`)
with the envs that must have it, so `make secrets-audit` reports a missing one.

For OIDC services, the client is declared once and generated (SSOT-017, ADR-040):

1. Add an entry to `apps.services.security.authelia.oidc_clients` in
   `infra/config/values/common.yaml`. Follow an existing client; every entry
   declares its own `token_endpoint_auth_method`.
2. Store the client secret in SOPS as `oidc_client_secret_<id>`, then generate its
   stored digest with `toolkit secrets hash`.
3. Render the client files for each environment and commit them:

```bash
make sync-oidc-hashes ENV=staging
make sync-oidc-hashes ENV=prod
```

Never add a `clients:` block to `configuration.yml` or edit `oidc-clients.yml` by
hand: `tests/test_oidc_clients.py` compares the committed files with the SSOT.

If the service needs JWKS and it does not exist yet:

```bash
toolkit secrets jwks --env staging
```

> **Gotcha — Authelia OIDC JWKS key injection**: the signing key is `jwks[0].key`, read from the K8s Secret mount by Authelia's template filter in `authelia-config/oidc-jwks.yml` (`X_AUTHELIA_CONFIG_FILTERS=template`). A `_FILE` env var only fills flat config keys, not list elements. See lesson-096 and #2377.

### 2. Create K8s Manifest

Create the service manifest at `infra/k8s/base/services/<service>.yaml`.

Follow the pattern established in `grafana.yaml`:

```yaml
# infra/k8s/base/services/<service>.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: <service>
  namespace: kubelab
spec:
  replicas: 1
  selector:
    matchLabels:
      app: <service>
  template:
    metadata:
      labels:
        app: <service>
    spec:
      containers:
        - name: <service>
          image: <image>:<tag>
          ports:
            - containerPort: <port>
          envFrom:
            - secretRef:
                name: <service>-secrets
            - configMapRef:
                name: <service>-config
          volumeMounts:
            - name: data
              mountPath: /data
      volumes:
        - name: data
          persistentVolumeClaim:
            claimName: <service>-pvc
---
apiVersion: v1
kind: Service
metadata:
  name: <service>
  namespace: kubelab
spec:
  selector:
    app: <service>
  ports:
    - port: <port>
      targetPort: <port>
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: <service>-pvc
  namespace: kubelab
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 1Gi
```

### 3. Add to Kustomization

Edit `infra/k8s/base/kustomization.yaml`:

```yaml
resources:
  # ... existing resources
  - services/<service>.yaml
```

A new workload has to be declared in a few more places, and a test fails until it is:

- **Ingress NetworkPolicy** in `infra/k8s/base/governance/networkpolicies.yaml`,
  naming every in-cluster caller (`tests/test_networkpolicy_coverage.py`, NET-002).
- **State classification** for a stateful service in `common.yaml`
  (`tests/test_stateful_service_classification.py`).
- **Backup ruling** for a prod PVC in `backup.sources.vps` or `backup.excluded.vps`
  (`tests/test_backup_pvc_coverage.py`).
- **Write permission** for any new kind in `infra/k8s/argocd/spoke-rbac.yaml`
  (`tests/test_spoke_rbac_covers_manifests.py`).

### 4. Add SecretMapping to Toolkit

Edit `toolkit/features/k8s_secrets.py` to add the secret mapping for the new service:

```python
SecretMapping(
    k8s_secret_name="<service>-secrets",
    sops_mappings={
        "KEY_NAME": "apps.services.<category>.<service>.key_path",
        # ... all secret key mappings
    },
),
```

This ensures `make apply-secrets ENV=<env>` creates the K8s Secret from SOPS values.

### 5. Configure Authelia Access Control

Edit the access rules in `infra/k8s/base/services/authelia-config/configuration.yml`
(the prod overlay has its own copy under `infra/k8s/overlays/prod/authelia-config/`):

**For OIDC services (Tier 1)**:
- The client itself comes from step 1, never from this file
- Add `bypass` rule in `access_control.rules` (forward-auth not needed, OIDC handles auth)

**For forward-auth services (Tier 2)**:
- Add `one_factor` (or `two_factor`) rule in `access_control.rules`
- No OIDC client needed

**For public services (Tier 3)**:
- Add `bypass` rule in `access_control.rules`

### 6. Create IngressRoute with Middleware Chain

Add the IngressRoute to the service manifest (or as a separate resource):

```yaml
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  name: <service>
  namespace: kubelab
spec:
  entryPoints:
    - websecure
  routes:
    - match: Host(`<service>.staging.kubelab.live`)
      kind: Rule
      middlewares:
        - name: secure-headers    # Always include
        - name: error-pages       # Always include
        - name: crowdsec-bouncer  # Always include
        # - name: authelia        # Include ONLY for Tier 2 (forward-auth) services
      services:
        - name: <service>
          port: <port>
  tls:
    certResolver: letsencrypt
```

**Middleware chain by auth tier**:

| Tier | Middlewares |
|------|------------|
| 1 (OIDC) | `secure-headers`, `error-pages`, `crowdsec-bouncer` |
| 2 (Forward Auth) | `secure-headers`, `error-pages`, `crowdsec-bouncer`, `authelia` |
| 3 (Bypass) | `secure-headers`, `error-pages`, `crowdsec-bouncer` |

### 7. Add Prod Overlay Patches

Edit `infra/k8s/overlays/prod/patches.yaml` to override staging-specific values for production:

```yaml
# Patch IngressRoute domain
- target:
    kind: IngressRoute
    name: <service>
  patch: |
    - op: replace
      path: /spec/routes/0/match
      value: Host(`<service>.kubelab.live`)
```

Also patch any ConfigMap or Deployment values that differ between staging and prod (e.g., URLs, feature flags).

### 8. Update DNS (if needed)

If the service requires a non-wildcard DNS record or a custom subdomain:

- Edit CoreDNS Corefile on RPi4 to add the record
- Or add a Terraform DNS record in `infra/terraform/dns/`

For most services, the existing wildcard `*.staging.kubelab.live` is sufficient and no DNS changes are needed.

### 9. Update E2E Test Expectations

Edit `tests/e2e/expectations.py` to add the new service:

```python
ServiceExpectation(
    name="<service>",
    url="https://<service>.staging.kubelab.live",
    health_status=(200,),           # Expected HTTP status codes
    health_path="/",                # Health check endpoint
    content_type="text/html",       # Expected content type
    skip_in_envs=(),                # Add ("staging",) if not deployed to staging yet
),
```

**Important**: Use underscores in the YAML config key (e.g., `uptime_kuma` not `uptime-kuma`).

### 10. Deploy

Validate on staging from your branch before merging:

```bash
# Secrets, middleware secrets and the overlay, applied as Argo CD's service account
make deploy-k8s ENV=staging
```

A deploy from a worktree lasts only until the next commit lands on `master`, from
any PR: Argo CD then reapplies `master` and your change disappears without a word.
For anything longer than a quick check, point staging at your branch and point it
back after the merge:

```bash
make argo-set-revision APP=kubelab-staging REV=<your-branch>
make argo-set-revision APP=kubelab-staging REV=master
```

Prod receives the service when the PR merges: Argo CD syncs `master`.

### 11. Verify

```bash
# Check pod is running
kubectl --kubeconfig ~/.kube/kubelab-staging-config -n kubelab get pods -l app=<service>

# Verify HTTPS access
curl -I https://<service>.staging.kubelab.live

# E2E against staging, then the full local suite
make test-e2e ENV=staging
make test
```

Read logs from Loki first (`toolkit obs logs`): it keeps history across pod restarts.

## Rollback

Before merge, point staging back at `master`
(`make argo-set-revision APP=kubelab-staging REV=master`). Argo CD reapplies `master`.
After merge, revert the PR. Argo CD prunes the resources it tracks in both
environments, and prod self-heals to the previous state. A PVC and its data go with
the revert, so check the backup ruling first.

The revert covers:
- `infra/k8s/base/kustomization.yaml`
- `toolkit/features/k8s_secrets.py`
- Authelia access control rules
- `tests/e2e/expectations.py`

## Checklist Summary

- [ ] Secrets added to SOPS
- [ ] K8s manifest created in `infra/k8s/base/services/`
- [ ] Added to `kustomization.yaml`
- [ ] SecretMapping added to `k8s_secrets.py`
- [ ] Authelia access control configured
- [ ] IngressRoute with correct middleware chain
- [ ] Prod overlay patches added
- [ ] DNS updated (if needed)
- [ ] E2E expectations updated
- [ ] Deployed and secrets applied
- [ ] Verified: pod running, HTTPS accessible, tests passing

## References

- ADR-016: OIDC Centralized Authentication via Authelia
- ADR-014: Secrets Management Strategy
- ADR-015: VPS K3s Migration Strategy
- `infra/k8s/base/services/grafana.yaml` — reference implementation
- `toolkit/features/k8s_secrets.py` — secret mapping definitions
