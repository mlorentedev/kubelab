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
> Created during the Gitea/N8N/MinIO deployment in Feb 2026.

## Prerequisites

- [ ] SOPS access configured (`make sops-check`)
- [ ] K3s cluster access via kubeconfig (`~/.kube/kubelab-config`)
- [ ] DNS wildcard `*.staging.kubelab.live` resolves to K3s ingress (100.64.0.4 via CoreDNS)
- [ ] Authelia running and healthy on the cluster
- [ ] Traefik running with CrowdSec bouncer middleware available
- [ ] Decide auth tier for the service (see ADR-016):
  - **OIDC** (Tier 1): Service has native OIDC support (e.g., MinIO, Gitea)
  - **Forward Auth** (Tier 2): No OIDC support, use Authelia middleware (e.g., N8N, Grafana)
  - **Bypass** (Tier 3): Public endpoint, no auth needed (e.g., API, blog)

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

For OIDC services, also add the client secret hash to Authelia's config:

```bash
# Generate argon2 hash of the client secret
docker run --rm authelia/authelia:latest authelia crypto hash generate argon2 --password '<plaintext-secret>'

# Add to Authelia OIDC clients in the appropriate config
```

If the service needs JWKS and it does not exist yet:

```bash
toolkit secrets jwks --env staging
```

> **Gotcha — Authelia OIDC JWKS key injection**: Use `issuer_private_key` (NOT `jwks[0].key`) in Authelia's configuration.yml. The `_FILE` env var suffix only works for flat config keys, not array-indexed ones. Set `AUTHELIA_IDENTITY_PROVIDERS_OIDC_ISSUER_PRIVATE_KEY_FILE=/run/secrets/oidc_jwks_key` to inject from a K8s Secret mount. See lesson `[2026-03-01] Authelia OIDC JWKS` in `90-lessons.md`.

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

This ensures `toolkit infra k8s apply-secrets` creates the K8s Secret from SOPS values.

### 5. Configure Authelia Access Control

Edit the Authelia configuration to add rules for the new service:

**For OIDC services (Tier 1)**:
- Add OIDC client definition to Authelia's `identity_providers.oidc.clients[]`
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

```bash
# Apply K8s manifests
kubectl apply -k infra/k8s/overlays/staging/

# Apply secrets from SOPS
toolkit infra k8s apply-secrets --env staging

# If the service has binary assets (logos, dashboards), verify configMapGenerator picked them up:
kubectl kustomize infra/k8s/overlays/staging/ | kubectl apply -f -
```

### 11. Verify

```bash
# Check pod is running
kubectl -n kubelab get pods -l app=<service>

# Check logs for errors
kubectl -n kubelab logs -l app=<service> --tail=50

# Verify HTTPS access
curl -I https://<service>.staging.kubelab.live

# Run E2E tests
pytest tests/e2e/ -k "<service>" -v

# Run full test suite to ensure no regressions
pytest tests/ -v
```

## Rollback

If the deployment fails or causes issues:

```bash
# Remove the service resources
kubectl delete -f infra/k8s/base/services/<service>.yaml

# Remove the associated secrets
kubectl -n kubelab delete secret <service>-secrets

# Remove the PVC (WARNING: destroys data)
kubectl -n kubelab delete pvc <service>-pvc
```

Then revert the changes in:
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
